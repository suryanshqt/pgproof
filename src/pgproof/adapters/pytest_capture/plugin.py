"""Standalone SQLAlchemy/pytest capture plugin.

Injected as raw source text (`pgproof.adapters.pytest_capture.load_plugin_source`)
into the isolated runner's staged workspace, `docs/TECHNICAL_DESIGN.md` section
10. It executes inside the TARGET project's own virtual environment, which
never has pgproof installed in it — only stdlib, SQLAlchemy, and pytest, the
same three the target project already depends on. No `pgproof` import is
permitted anywhere in this module for that reason; it emits plain JSON lines,
parsed back into typed `CapturedQueryEvent`s host-side by
`pgproof.domain.capture_event.parse_capture_ndjson`.

`before_cursor_execute`/`after_cursor_execute` are observation-only hooks: this
module never returns a replacement statement/parameters and never reads
`cursor`'s pending result rows, only `cursor.rowcount` after execution — the
listener cannot change what a test observes.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import traceback
from collections.abc import Iterable
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.interfaces import DBAPICursor, ExceptionContext, ExecutionContext

_CAPTURE_FILE_ENV = "PGPROOF_CAPTURE_FILE"
_UNSAFE_VALUES_ENV = "PGPROOF_CAPTURE_UNSAFE_VALUES"
_WORKSPACE_ROOT = str(Path.cwd())

_state = threading.local()
_sequence_lock = threading.Lock()
_sequence = 0
_write_lock = threading.Lock()
_content_hash_cache: dict[str, str] = {}


def pytest_runtest_setup(item: pytest.Item) -> None:
    _state.node_id = item.nodeid
    _state.phase = "setup"


def pytest_runtest_call(item: pytest.Item) -> None:
    _state.node_id = item.nodeid
    _state.phase = "call"


def pytest_runtest_teardown(item: pytest.Item) -> None:
    _state.node_id = item.nodeid
    _state.phase = "teardown"


def _current_node() -> tuple[str | None, str | None]:
    return getattr(_state, "node_id", None), getattr(_state, "phase", None)


def _next_sequence() -> int:
    global _sequence
    with _sequence_lock:
        _sequence += 1
        return _sequence


def _content_hash(path: str) -> str | None:
    if path in _content_hash_cache:
        return _content_hash_cache[path]
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    digest = f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
    _content_hash_cache[path] = digest
    return digest


def _filtered_stack() -> list[dict[str, object]]:
    """Only frames under the project's own workspace root, matching neither a
    `site-packages` install nor this module itself — `docs/TECHNICAL_DESIGN.md:265`'s
    "filtered application stack". Inclusion-based, not a library denylist: a
    test dependency vendored under the workspace would otherwise leak in.
    """
    frames: list[dict[str, object]] = []
    for frame in traceback.extract_stack():
        if frame.filename == __file__:
            continue
        try:
            relative = os.path.relpath(frame.filename, _WORKSPACE_ROOT)
        except ValueError:
            continue
        if relative.startswith("..") or "site-packages" in relative:
            continue
        content_hash = _content_hash(frame.filename)
        if content_hash is None:
            continue
        frames.append(
            {
                "path": relative.replace(os.sep, "/"),
                "line": frame.lineno,
                "content_hash": content_hash,
                "symbol": frame.name,
            }
        )
    return frames


def _describe_parameters(parameters: object) -> list[dict[str, object]]:
    if not parameters:
        return []
    unsafe = os.environ.get(_UNSAFE_VALUES_ENV) == "1"
    values: object = parameters
    # `executemany`: every row shares the same bind shape; describing the
    # first row is representative and avoids an unbounded per-row fan-out.
    if (
        isinstance(parameters, list)
        and parameters
        and isinstance(parameters[0], dict | tuple | list)
    ):
        values = parameters[0]
    items: Iterable[tuple[object, object]]
    if isinstance(values, dict):
        items = values.items()
    elif isinstance(values, tuple | list):
        items = enumerate(values, start=1)
    else:
        items = ()
    described: list[dict[str, object]] = []
    for position, value in items:
        text = repr(value)
        described.append(
            {
                "position": position,
                "python_type": type(value).__name__,
                "value_hash": f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
                "is_redacted": not unsafe,
                "redacted_value": text if unsafe else None,
            }
        )
    return described


def _write_event(payload: dict[str, object]) -> None:
    raw_path = os.environ.get(_CAPTURE_FILE_ENV)
    if not raw_path:
        return
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with _write_lock, path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _base_payload(
    *, statement: str, dialect: str, parameters: object, executemany: bool, duration_us: int
) -> dict[str, object] | None:
    node_id, phase = _current_node()
    if node_id is None or phase is None:
        # A query outside any test's setup/call/teardown window — a
        # session-scoped fixture's own teardown at interpreter exit, for
        # instance — has nothing to correlate it to.
        return None
    batch_size = len(parameters) if executemany and isinstance(parameters, list) else None
    return {
        "sequence": _next_sequence(),
        "duration_us": duration_us,
        "statement": statement,
        "dialect": dialect,
        "parameters": _describe_parameters(parameters),
        "executemany": executemany,
        "batch_size": batch_size,
        "node_id": node_id,
        "phase": phase,
        "call_sites": _filtered_stack(),
        "process_id": os.getpid(),
        "thread_id": threading.get_ident(),
        "task_id": None,
    }


@event.listens_for(Engine, "before_cursor_execute")
def _before_cursor_execute(
    _conn: Connection,
    _cursor: DBAPICursor,
    _statement: str,
    _parameters: object,
    context: ExecutionContext | None,
    _executemany: bool,
) -> None:
    if context is not None:
        setattr(context, "_pgproof_started", time.monotonic())  # noqa: B010


@event.listens_for(Engine, "after_cursor_execute")
def _after_cursor_execute(
    conn: Connection,
    cursor: DBAPICursor,
    statement: str,
    parameters: object,
    context: ExecutionContext | None,
    executemany: bool,
) -> None:
    started = getattr(context, "_pgproof_started", None)
    duration_us = int((time.monotonic() - started) * 1_000_000) if started is not None else 0
    payload = _base_payload(
        statement=statement,
        dialect=conn.dialect.name,
        parameters=parameters,
        executemany=bool(executemany),
        duration_us=duration_us,
    )
    if payload is None:
        return
    try:
        rowcount = cursor.rowcount
    except Exception:  # DBAPI cursors may raise reading rowcount for some statements
        rowcount = None
    payload["rowcount"] = rowcount if isinstance(rowcount, int) and rowcount >= 0 else None
    transaction = conn.get_transaction()
    payload["transaction_id"] = str(id(transaction)) if transaction is not None else None
    payload["error_class"] = None
    _write_event(payload)


@event.listens_for(Engine, "handle_error")
def _handle_error(exception_context: ExceptionContext) -> None:
    execution_context = exception_context.execution_context
    started = getattr(execution_context, "_pgproof_started", None) if execution_context else None
    duration_us = int((time.monotonic() - started) * 1_000_000) if started is not None else 0
    statement = exception_context.statement or "<unknown statement>"
    connection = exception_context.connection
    payload = _base_payload(
        statement=statement,
        dialect=connection.dialect.name if connection is not None else "unknown",
        parameters=exception_context.parameters,
        executemany=bool(getattr(execution_context, "executemany", False)),
        duration_us=duration_us,
    )
    if payload is None:
        return
    payload["rowcount"] = None
    payload["transaction_id"] = None
    payload["error_class"] = type(exception_context.original_exception).__name__
    _write_event(payload)
