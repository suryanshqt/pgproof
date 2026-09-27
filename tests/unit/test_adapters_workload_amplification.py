"""`adapters.workload.amplification.annotate_amplifications` over a captured
event stream. `docs/TECHNICAL_DESIGN.md` section 23: parent then repeated
child fingerprint in one operation, binds varying with parent identities, a
configurable repetition threshold defaulting to 5.
"""

from __future__ import annotations

import hashlib

from pgproof.adapters.workload.amplification import annotate_amplifications
from pgproof.adapters.workload.reconstruct import reconstruct_workload
from pgproof.domain.capture_event import CapturedQueryEvent
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    SchemaIR,
    SchemaProvenance,
    TableIR,
)
from pgproof.domain.ir.workload import (
    AmplificationClass,
    AmplificationIR,
    OperationIR,
    OperationPhase,
    WorkloadCoverage,
)
from pgproof.domain.sources import SourceRef

_P = SchemaProvenance.PHYSICAL_CATALOG
_ORDERS = table_id("public", "orders")
_ORDER_ITEMS = table_id("public", "order_items")
_DIGEST = "sha256:" + "a" * 64

_PARENT_SQL = "SELECT id FROM orders WHERE tenant_id = $1"
_CHILD_SQL = "SELECT id FROM order_items WHERE order_id = $1"


def _column(table: str, name: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name), name=name, data_type="integer", nullable=True, provenance=_P
    )


def _table(identity: str, name: str, *columns: str) -> TableIR:
    return TableIR(
        id=identity,
        schema_name="public",
        name=name,
        provenance=_P,
        columns=tuple(_column(identity, column) for column in columns),
    )


_FOREIGN_KEY = ConstraintIR(
    name="order_items_order_id_fkey",
    kind=ConstraintKind.FOREIGN_KEY,
    table=_ORDER_ITEMS,
    columns=(column_id(_ORDER_ITEMS, "order_id"),),
    referenced_table=_ORDERS,
    referenced_columns=(column_id(_ORDERS, "id"),),
    provenance=_P,
)

_SCHEMA = SchemaIR(
    provenance=_P,
    tables=(
        _table(_ORDERS, "orders", "id", "tenant_id"),
        _table(_ORDER_ITEMS, "order_items", "id", "order_id"),
    ),
    constraints=(_FOREIGN_KEY,),
)

_SCHEMA_WITHOUT_FOREIGN_KEY = _SCHEMA.model_copy(update={"constraints": ()})


def _site(path: str = "app/repositories.py", line: int = 10) -> SourceRef:
    return SourceRef(path=path, line=line, content_hash=_DIGEST)


def _bind(value: str) -> dict[str, object]:
    return {
        "position": 1,
        "python_type": "int",
        "value_hash": f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}",
    }


def _event(**overrides: object) -> CapturedQueryEvent:
    defaults: dict[str, object] = {
        "sequence": 1,
        "duration_us": 100,
        "statement": _CHILD_SQL,
        "dialect": "postgresql",
        "parameters": (),
        "rowcount": 1,
        "node_id": "tests/test_orders.py::test_totals",
        "phase": OperationPhase.CALL,
        "call_sites": (_site(),),
        "process_id": 1,
        "thread_id": 1,
    }
    defaults.update(overrides)
    return CapturedQueryEvent.model_validate(defaults)


def _children(count: int, *, vary_binds: bool = True) -> list[CapturedQueryEvent]:
    return [
        _event(
            sequence=index + 2,
            parameters=(_bind(str(index) if vary_binds else "same"),),
        )
        for index in range(count)
    ]


def _only(operations: tuple[OperationIR, ...]) -> AmplificationIR:
    return operations[0].amplifications[0]


def _annotate(
    events: list[CapturedQueryEvent],
    *,
    schema: SchemaIR = _SCHEMA,
    min_repetitions: int = 5,
) -> tuple[OperationIR, ...]:
    workload = reconstruct_workload(
        events,
        schema=schema,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
    )
    return annotate_amplifications(
        events, workload, schema=schema, min_repetitions=min_repetitions
    ).operations


def _parent(**overrides: object) -> CapturedQueryEvent:
    defaults: dict[str, object] = {
        "sequence": 1,
        "statement": _PARENT_SQL,
        "parameters": (_bind("tenant"),),
        "rowcount": 5,
        "call_sites": (_site("app/repositories.py", 30),),
    }
    defaults.update(overrides)
    return _event(**defaults)


def test_repeated_children_with_varying_binds_under_a_matching_parent_are_observed_n_plus_one() -> (
    None
):
    operations = _annotate([_parent(), *_children(5)])
    assert len(operations) == 1
    assert len(operations[0].amplifications) == 1
    amplification = _only(operations)
    assert amplification.classification is AmplificationClass.OBSERVED_N_PLUS_ONE
    assert amplification.repetitions == 5
    assert amplification.relationship_name == "order_items_order_id_fkey"
    assert amplification.call_site is not None
    assert amplification.call_site.line == 10


def test_parent_and_child_query_ids_identify_the_two_distinct_fingerprints() -> None:
    events = [_parent(), *_children(5)]
    workload = reconstruct_workload(
        events,
        schema=_SCHEMA,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
    )
    by_relation = {query.relations: query.id for query in workload.queries}
    amplification = _only(annotate_amplifications(events, workload, schema=_SCHEMA).operations)
    assert amplification.parent_query == by_relation[(_ORDERS,)]
    assert amplification.child_query == by_relation[(_ORDER_ITEMS,)]


def test_a_missing_foreign_key_leaves_the_relationship_name_unnamed() -> None:
    operations = _annotate([_parent(), *_children(5)], schema=_SCHEMA_WITHOUT_FOREIGN_KEY)
    amplification = _only(operations)
    assert amplification.classification is AmplificationClass.OBSERVED_N_PLUS_ONE
    assert amplification.relationship_name is None


def test_a_parent_spanning_two_relations_leaves_the_relationship_name_unnamed() -> None:
    parent = _parent(
        statement="SELECT o.id FROM orders o JOIN order_items i ON i.order_id = o.id "
        "WHERE o.tenant_id = $1"
    )
    operations = _annotate([parent, *_children(5)])
    assert _only(operations).relationship_name is None


def test_identical_binds_across_every_occurrence_are_a_repeated_query_only() -> None:
    operations = _annotate([_parent(), *_children(5, vary_binds=False)])
    assert _only(operations).classification is AmplificationClass.REPEATED_QUERY


def test_a_repetition_with_no_parameters_at_all_is_a_repeated_query_only() -> None:
    children = [_event(sequence=index + 2, statement=_CHILD_SQL) for index in range(5)]
    operations = _annotate([_parent(), *children])
    assert _only(operations).classification is AmplificationClass.REPEATED_QUERY


def test_varying_binds_without_a_matching_parent_rowcount_are_only_a_possible_amplification() -> (
    None
):
    operations = _annotate([_parent(rowcount=2), *_children(5)])
    assert _only(operations).classification is AmplificationClass.POSSIBLE_AMPLIFICATION


def test_an_unknown_parent_rowcount_is_only_a_possible_amplification() -> None:
    operations = _annotate([_parent(rowcount=None), *_children(5)])
    assert _only(operations).classification is AmplificationClass.POSSIBLE_AMPLIFICATION


def test_a_write_parent_is_never_an_observed_n_plus_one() -> None:
    parent = _parent(statement="UPDATE orders SET tenant_id = $1 WHERE id = $2")
    operations = _annotate([parent, *_children(5)])
    assert _only(operations).classification is AmplificationClass.POSSIBLE_AMPLIFICATION


def test_repetitions_exactly_at_the_threshold_are_reported() -> None:
    operations = _annotate([_parent(rowcount=3), *_children(3)], min_repetitions=3)
    assert _only(operations).repetitions == 3


def test_one_repetition_below_the_threshold_reports_nothing() -> None:
    operations = _annotate([_parent(rowcount=2), *_children(2)], min_repetitions=3)
    assert operations[0].amplifications == ()


def test_four_repetitions_are_below_the_default_threshold() -> None:
    operations = _annotate([_parent(rowcount=4), *_children(4)])
    assert operations[0].amplifications == ()


def test_a_repetition_with_no_preceding_distinct_query_is_skipped() -> None:
    operations = _annotate(_children(5))
    assert operations[0].amplifications == ()


def test_the_nearest_preceding_distinct_query_is_chosen_as_the_parent() -> None:
    events = [
        _event(sequence=1, statement="SELECT id FROM orders WHERE id = $1", rowcount=1),
        _parent(sequence=2),
        *_children(5),
    ]
    workload = reconstruct_workload(
        events,
        schema=_SCHEMA,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
    )
    amplification = _only(annotate_amplifications(events, workload, schema=_SCHEMA).operations)
    parent = next(query for query in workload.queries if query.id == amplification.parent_query)
    assert "tenant_id" in parent.normalized_sql


def test_repetitions_are_counted_per_operation_not_across_the_whole_run() -> None:
    events = [
        _parent(sequence=1, node_id="tests/test_orders.py::test_a"),
        *[
            _event(
                sequence=index + 2,
                node_id="tests/test_orders.py::test_a",
                parameters=(_bind(str(index)),),
            )
            for index in range(3)
        ],
        _parent(sequence=10, node_id="tests/test_orders.py::test_b"),
        *[
            _event(
                sequence=index + 11,
                node_id="tests/test_orders.py::test_b",
                parameters=(_bind(str(index)),),
            )
            for index in range(3)
        ],
    ]
    operations = annotate_amplifications(
        events,
        reconstruct_workload(
            events,
            schema=_SCHEMA,
            coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
            boundary_note="capture completed for the selected test command",
        ),
        schema=_SCHEMA,
    ).operations
    assert len(operations) == 2
    assert all(operation.amplifications == () for operation in operations)


def test_non_contiguous_occurrences_still_count_toward_one_repetition() -> None:
    events = [
        _parent(),
        *_children(3),
        _event(sequence=20, statement=_PARENT_SQL, parameters=(_bind("other"),), rowcount=1),
        *[_event(sequence=index + 21, parameters=(_bind(f"late-{index}"),)) for index in range(2)],
    ]
    operations = _annotate(events)
    assert _only(operations).repetitions == 5


def test_an_operation_with_no_captured_events_keeps_its_empty_amplifications() -> None:
    events = [_parent(), *_children(5)]
    workload = reconstruct_workload(
        events,
        schema=_SCHEMA,
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
    )
    annotated = annotate_amplifications((), workload, schema=_SCHEMA)
    assert annotated.operations[0].amplifications == ()
