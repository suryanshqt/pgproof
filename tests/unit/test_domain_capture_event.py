"""`CapturedQueryEvent`/`CapturedParameter` validation and NDJSON parsing."""

from __future__ import annotations

import json

from pgproof.domain.capture_event import CapturedQueryEvent, parse_capture_ndjson
from pgproof.domain.ir.workload import OperationPhase


def _payload(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "sequence": 1,
        "duration_us": 500,
        "statement": "SELECT 1",
        "dialect": "postgresql",
        "parameters": [],
        "executemany": False,
        "batch_size": None,
        "rowcount": 1,
        "transaction_id": None,
        "node_id": "tests/test_orders.py::test_x",
        "phase": "call",
        "call_sites": [],
        "error_class": None,
        "process_id": 123,
        "thread_id": 456,
        "task_id": None,
    }
    defaults.update(overrides)
    return defaults


def test_a_well_formed_event_validates() -> None:
    event = CapturedQueryEvent.model_validate(_payload())
    assert event.phase is OperationPhase.CALL
    assert event.statement == "SELECT 1"


def test_a_captured_parameter_defaults_to_redacted() -> None:
    event = CapturedQueryEvent.model_validate(
        _payload(
            parameters=[
                {
                    "position": 1,
                    "python_type": "int",
                    "value_hash": "sha256:" + "a" * 64,
                    "is_redacted": True,
                    "redacted_value": None,
                }
            ]
        )
    )
    assert event.parameters[0].is_redacted is True
    assert event.parameters[0].redacted_value is None


def test_parse_ndjson_returns_every_valid_event_in_order() -> None:
    raw = "\n".join(json.dumps(_payload(sequence=n)) for n in (1, 2, 3))
    events, malformed = parse_capture_ndjson(raw.encode("utf-8"))
    assert [event.sequence for event in events] == [1, 2, 3]
    assert malformed == 0


def test_parse_ndjson_skips_blank_lines() -> None:
    raw = json.dumps(_payload()) + "\n\n" + json.dumps(_payload(sequence=2)) + "\n"
    events, malformed = parse_capture_ndjson(raw.encode("utf-8"))
    assert len(events) == 2
    assert malformed == 0


def test_parse_ndjson_counts_unparseable_json_without_raising() -> None:
    raw = "not json\n" + json.dumps(_payload())
    events, malformed = parse_capture_ndjson(raw.encode("utf-8"))
    assert len(events) == 1
    assert malformed == 1


def test_parse_ndjson_counts_a_line_that_fails_validation() -> None:
    bad = _payload()
    del bad["statement"]  # required field missing
    raw = json.dumps(bad) + "\n" + json.dumps(_payload())
    events, malformed = parse_capture_ndjson(raw.encode("utf-8"))
    assert len(events) == 1
    assert malformed == 1


def test_parse_ndjson_on_empty_bytes_is_empty_not_an_error() -> None:
    events, malformed = parse_capture_ndjson(b"")
    assert events == ()
    assert malformed == 0
