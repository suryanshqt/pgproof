"""Raw per-query capture events, one per NDJSON line written by the pytest
capture plugin (`pgproof.adapters.pytest_capture.plugin`) while it runs
inside the isolated runner. `docs/TECHNICAL_DESIGN.md` section 10.

Distinct from `domain.ir.workload.QueryIR`: a `QueryIR` is BE-19's *parsed,
fingerprinted, de-duplicated* statement; a `CapturedQueryEvent` is one raw
DBAPI cursor execution as SQLAlchemy observed it, before parsing or grouping
(BE-21's job). Not part of the generated JSON Schema / TypeScript contract
set, matching `domain.events.StageEvent`: this is a backend-internal record,
not a versioned public artifact.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from pgproof.domain.ir.workload import OperationPhase
from pgproof.domain.primitives import Contract, Microseconds, NonEmptyText, Sha256
from pgproof.domain.sources import SourceRef


class CapturedParameter(Contract):
    """One bind value's shape, captured without its value by default.

    `docs/TECHNICAL_DESIGN.md:467`: captured test binds are hashed/redacted by
    default; `redacted_value` is populated only when the plugin ran with its
    unsafe-values opt-in set.
    """

    position: int | NonEmptyText
    python_type: NonEmptyText
    value_hash: Sha256 | None = None
    is_redacted: bool = True
    redacted_value: NonEmptyText | None = None


class CapturedQueryEvent(Contract):
    """One `before_cursor_execute`/`after_cursor_execute` pair, or a failed
    execution reported through SQLAlchemy's `handle_error` hook instead.

    `sequence` (not a wall-clock timestamp) is what section 12's "order events
    by monotonic sequence" reconstructs operations from — a per-run counter
    the plugin increments, meaningful only within one capture file.
    """

    sequence: int
    duration_us: Microseconds
    statement: NonEmptyText
    dialect: NonEmptyText
    parameters: tuple[CapturedParameter, ...] = ()
    executemany: bool = False
    batch_size: int | None = None
    rowcount: int | None = None
    transaction_id: NonEmptyText | None = None
    node_id: NonEmptyText
    phase: OperationPhase
    call_sites: tuple[SourceRef, ...] = ()
    error_class: NonEmptyText | None = None
    process_id: int
    thread_id: int
    task_id: NonEmptyText | None = None


def parse_capture_ndjson(raw: bytes) -> tuple[tuple[CapturedQueryEvent, ...], int]:
    """Parse one capture file's full content.

    A line that fails to decode or validate is counted, not raised: the
    roadmap's "failed tests preserve bounded capture" means one bad line must
    never discard every event that parsed correctly around it.
    """
    events: list[CapturedQueryEvent] = []
    malformed = 0
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            events.append(CapturedQueryEvent.model_validate(payload))
        except (json.JSONDecodeError, ValidationError):
            malformed += 1
    return tuple(events), malformed
