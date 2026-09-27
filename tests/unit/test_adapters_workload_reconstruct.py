"""`adapters.workload.reconstruct.reconstruct_workload` against a captured
event stream. `docs/TECHNICAL_DESIGN.md` section 12: order by sequence, group
identical fingerprints, build operation -> transaction -> query -> relation
edges.
"""

from __future__ import annotations

from pgproof.adapters.workload.reconstruct import reconstruct_workload
from pgproof.domain.capture_event import CapturedQueryEvent
from pgproof.domain.identifiers import column_id, operation_id, table_id
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.ir.workload import (
    OperationPhase,
    StatementClass,
    WorkloadCoverage,
    WorkloadIR,
)
from pgproof.domain.sources import SourceRef

_P = SchemaProvenance.PHYSICAL_CATALOG
_ORDERS = table_id("public", "orders")
_DIGEST = "sha256:" + "a" * 64


def _column(table: str, name: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name), name=name, data_type="integer", nullable=True, provenance=_P
    )


_SCHEMA = SchemaIR(
    provenance=_P,
    tables=(
        TableIR(
            id=_ORDERS,
            schema_name="public",
            name="orders",
            provenance=_P,
            columns=(_column(_ORDERS, "id"), _column(_ORDERS, "tenant_id")),
        ),
    ),
)


def _site(path: str = "app/repo.py", line: int = 10) -> SourceRef:
    return SourceRef(path=path, line=line, content_hash=_DIGEST)


def _event(**overrides: object) -> CapturedQueryEvent:
    defaults: dict[str, object] = {
        "sequence": 1,
        "duration_us": 100,
        "statement": "SELECT id FROM orders",
        "dialect": "postgresql",
        "parameters": (),
        "executemany": False,
        "batch_size": None,
        "rowcount": 1,
        "transaction_id": None,
        "node_id": "tests/test_orders.py::test_x",
        "phase": OperationPhase.CALL,
        "call_sites": (_site(),),
        "error_class": None,
        "process_id": 1,
        "thread_id": 1,
        "task_id": None,
    }
    defaults.update(overrides)
    return CapturedQueryEvent.model_validate(defaults)


def _reconstruct(
    events: list[CapturedQueryEvent],
    *,
    transaction_outcomes: dict[str, bool] | None = None,
    coverage: WorkloadCoverage = WorkloadCoverage.COMPLETE_FOR_SELECTION,
    boundary_note: str = "capture completed for the selected test command",
    selected_tests: int = 0,
    passed_tests: int = 0,
    failed_tests: int = 0,
) -> WorkloadIR:
    return reconstruct_workload(
        events,
        schema=_SCHEMA,
        transaction_outcomes=transaction_outcomes or {},
        coverage=coverage,
        boundary_note=boundary_note,
        selected_tests=selected_tests,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
    )


def test_a_read_query_is_classified_and_its_relation_resolved() -> None:
    workload = _reconstruct([_event()])
    assert len(workload.queries) == 1
    query = workload.queries[0]
    assert query.statement_class is StatementClass.READ
    assert query.relations == (_ORDERS,)


def test_repeated_identical_statements_group_into_one_query_and_increment_the_count() -> None:
    workload = _reconstruct([_event(sequence=1), _event(sequence=2)])
    assert len(workload.queries) == 1
    assert len(workload.operations) == 1
    assert workload.operations[0].query_counts[workload.queries[0].id] == 2


def test_call_sites_merge_across_repeated_occurrences_of_the_same_query() -> None:
    workload = _reconstruct(
        [
            _event(sequence=1, call_sites=(_site("app/a.py", 1),)),
            _event(sequence=2, call_sites=(_site("app/b.py", 2),)),
        ]
    )
    assert len(workload.queries) == 1
    assert {site.path for site in workload.queries[0].call_sites} == {"app/a.py", "app/b.py"}


def test_a_different_node_id_or_phase_is_a_different_operation() -> None:
    workload = _reconstruct(
        [
            _event(sequence=1, node_id="tests/test_orders.py::test_x", phase=OperationPhase.SETUP),
            _event(sequence=2, node_id="tests/test_orders.py::test_x", phase=OperationPhase.CALL),
            _event(sequence=3, node_id="tests/test_orders.py::test_y", phase=OperationPhase.CALL),
        ]
    )
    assert len(workload.operations) == 3
    assert {op.id for op in workload.operations} == {
        operation_id("pytest", "tests/test_orders.py::test_x", "setup"),
        operation_id("pytest", "tests/test_orders.py::test_x", "call"),
        operation_id("pytest", "tests/test_orders.py::test_y", "call"),
    }


def test_a_write_statement_populates_tables_written_not_tables_read() -> None:
    workload = _reconstruct([_event(statement="UPDATE orders SET tenant_id = 1 WHERE id = 1")])
    operation = workload.operations[0]
    assert operation.tables_written == (_ORDERS,)
    assert operation.tables_read == ()


def test_entry_point_is_the_first_events_own_call_site_not_a_later_merge() -> None:
    workload = _reconstruct(
        [
            _event(
                sequence=1,
                node_id="tests/test_orders.py::test_x",
                call_sites=(_site("app/first.py", 1),),
            ),
            _event(
                sequence=2,
                node_id="tests/test_orders.py::test_y",
                call_sites=(_site("app/second.py", 2),),
            ),
        ]
    )
    by_node = {op.id: op for op in workload.operations}
    x_op = by_node[operation_id("pytest", "tests/test_orders.py::test_x", "call")]
    y_op = by_node[operation_id("pytest", "tests/test_orders.py::test_y", "call")]
    assert x_op.entry_point is not None
    assert x_op.entry_point.path == "app/first.py"
    assert y_op.entry_point is not None
    assert y_op.entry_point.path == "app/second.py"


def test_a_transactions_queries_are_grouped_and_committed_state_is_looked_up() -> None:
    workload = _reconstruct(
        [
            _event(sequence=1, transaction_id="tx-1"),
            _event(sequence=2, transaction_id="tx-1"),
        ],
        transaction_outcomes={"tx-1": True},
    )
    operation = workload.operations[0]
    assert len(operation.transactions) == 1
    transaction = operation.transactions[0]
    assert transaction.correlation_id == "tx-1"
    assert len(transaction.queries) == 2
    assert transaction.committed is True


def test_a_transaction_with_no_recorded_outcome_defaults_to_not_committed() -> None:
    workload = _reconstruct([_event(transaction_id="tx-1")])
    assert workload.operations[0].transactions[0].committed is False


def test_events_are_ordered_by_sequence_regardless_of_input_order() -> None:
    workload = _reconstruct(
        [
            _event(sequence=2, node_id="tests/test_orders.py::test_b"),
            _event(sequence=1, node_id="tests/test_orders.py::test_a"),
        ]
    )
    assert [op.id for op in workload.operations] == [
        operation_id("pytest", "tests/test_orders.py::test_a", "call"),
        operation_id("pytest", "tests/test_orders.py::test_b", "call"),
    ]


def test_coverage_boundary_and_test_counts_pass_through() -> None:
    workload = _reconstruct(
        [_event()],
        coverage=WorkloadCoverage.PARTIAL,
        boundary_note="test command exited 1; 1 query event(s) captured before it stopped",
        selected_tests=3,
        passed_tests=2,
        failed_tests=1,
    )
    assert workload.coverage is WorkloadCoverage.PARTIAL
    assert workload.boundary_note.startswith("test command exited")
    assert (workload.selected_tests, workload.passed_tests, workload.failed_tests) == (3, 2, 1)


def test_no_events_produces_an_empty_but_valid_workload() -> None:
    workload = _reconstruct([])
    assert workload.queries == ()
    assert workload.operations == ()
