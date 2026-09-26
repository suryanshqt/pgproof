"""The standalone capture plugin's pure logic, exercised directly and through
a real SQLAlchemy engine — this module has zero `pgproof` imports itself and
must work standalone inside a target project's own venv, so it is tested the
same way: only stdlib, SQLAlchemy, and pytest.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Engine, create_engine, text

from pgproof.adapters.pytest_capture import CAPTURE_FILE_ENV, UNSAFE_VALUES_ENV, load_plugin_source
from pgproof.adapters.pytest_capture import plugin as capture_plugin


class _FakeItem:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid


def _as_item(fake: _FakeItem) -> pytest.Item:
    return cast(pytest.Item, fake)


def _enter_call_phase(node_id: str) -> None:
    capture_plugin.pytest_runtest_call(_as_item(_FakeItem(node_id)))


@pytest.fixture(autouse=True)
def _reset_node_state() -> Iterator[None]:
    capture_plugin._state.node_id = None
    capture_plugin._state.phase = None
    yield
    capture_plugin._state.node_id = None
    capture_plugin._state.phase = None


@pytest.fixture
def engine() -> Iterator[Engine]:
    made = create_engine("sqlite:///:memory:")
    yield made
    made.dispose()


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_load_plugin_source_returns_this_files_own_text() -> None:
    source = load_plugin_source()
    assert "before_cursor_execute" in source
    assert "import pgproof" not in source


def test_pytest_hooks_set_node_and_phase() -> None:
    item = _as_item(_FakeItem("tests/test_orders.py::test_x"))
    capture_plugin.pytest_runtest_setup(item)
    assert capture_plugin._current_node() == ("tests/test_orders.py::test_x", "setup")
    capture_plugin.pytest_runtest_call(item)
    assert capture_plugin._current_node() == ("tests/test_orders.py::test_x", "call")
    capture_plugin.pytest_runtest_teardown(item)
    assert capture_plugin._current_node() == ("tests/test_orders.py::test_x", "teardown")


def test_a_query_outside_any_test_phase_is_not_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    assert _read_events(capture_file) == []


def test_a_query_during_a_tests_call_phase_is_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    _enter_call_phase("tests/test_orders.py::test_x")
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    events = _read_events(capture_file)
    assert len(events) == 1
    event = events[0]
    assert event["node_id"] == "tests/test_orders.py::test_x"
    assert event["phase"] == "call"
    assert event["statement"] == "SELECT 1"
    assert event["dialect"] == "sqlite"
    assert event["error_class"] is None
    assert isinstance(event["duration_us"], int)
    assert event["sequence"] >= 1


def test_bound_parameters_are_hashed_not_stored_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    _enter_call_phase("tests/test_orders.py::test_x")
    with engine.connect() as conn:
        conn.execute(text("SELECT :value"), {"value": "a-secret"})
    event = _read_events(capture_file)[0]
    parameter = event["parameters"][0]
    assert parameter["is_redacted"] is True
    assert parameter["redacted_value"] is None
    assert "a-secret" not in json.dumps(event)


def test_unsafe_values_opt_in_reveals_the_redacted_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    monkeypatch.setenv(UNSAFE_VALUES_ENV, "1")
    _enter_call_phase("tests/test_orders.py::test_x")
    with engine.connect() as conn:
        conn.execute(text("SELECT :value"), {"value": "a-secret"})
    parameter = _read_events(capture_file)[0]["parameters"][0]
    assert parameter["is_redacted"] is False
    assert parameter["redacted_value"] == "'a-secret'"


def test_a_failed_statement_is_captured_through_handle_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    _enter_call_phase("tests/test_orders.py::test_x")
    with engine.connect() as conn, pytest.raises(Exception, match="no such table"):
        conn.execute(text("SELECT * FROM nonexistent_table"))
    events = _read_events(capture_file)
    assert len(events) == 1
    assert events[0]["error_class"] is not None
    assert "OperationalError" in events[0]["error_class"]


def test_the_listener_does_not_change_the_query_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: Engine
) -> None:
    capture_file = tmp_path / "events.ndjson"
    monkeypatch.setenv(CAPTURE_FILE_ENV, str(capture_file))
    _enter_call_phase("tests/test_orders.py::test_x")
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 + 1")).scalar_one()
    assert result == 2


def test_describe_parameters_handles_dict_tuple_list_and_none() -> None:
    assert capture_plugin._describe_parameters(None) == []
    assert capture_plugin._describe_parameters(()) == []
    described = capture_plugin._describe_parameters((1, "two"))
    assert [item["position"] for item in described] == [1, 2]
    described = capture_plugin._describe_parameters({"a": 1})
    assert described[0]["position"] == "a"


def test_describe_parameters_on_an_executemany_batch_describes_the_first_row() -> None:
    described = capture_plugin._describe_parameters([(1, "x"), (2, "y"), (3, "z")])
    assert [item["position"] for item in described] == [1, 2]
    assert described[0]["python_type"] == "int"


def test_content_hash_returns_none_for_an_unreadable_path() -> None:
    assert capture_plugin._content_hash("/does/not/exist.py") is None
