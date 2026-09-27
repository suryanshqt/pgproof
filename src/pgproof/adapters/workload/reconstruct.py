"""Operation/transaction/query/table reconstruction from a captured query
event stream. `docs/TECHNICAL_DESIGN.md` section 12.

Depends on `adapters.sql.parser` (BE-19's pure parser) for query identity,
which is why this lives under `adapters` rather than `application` —
`application` may not import `adapters` (`tests/unit/test_dependency_boundaries.py`).
Otherwise pure: no filesystem, no database, no subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pgproof.adapters.sql.parser import parse_query
from pgproof.domain.capture_event import CapturedQueryEvent
from pgproof.domain.identifiers import QueryId, TableId, operation_id
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.ir.workload import (
    OperationIR,
    OperationPhase,
    QueryIR,
    StatementClass,
    TransactionIR,
    WorkloadCoverage,
    WorkloadIR,
)
from pgproof.domain.sources import SourceRef

# The only adapter this reconstruction runs over today; BE-20 captures pytest
# alone, so this is the operation identity's `kind`
# (`docs/TECHNICAL_DESIGN.md` section 12: "primary operation boundary: pytest
# node id + phase").
_ADAPTER_KIND = "pytest"


@dataclass
class _OperationBuilder:
    """Accumulates one (node id, phase) operation's events in sequence order."""

    phase: OperationPhase
    entry_point: SourceRef | None = None
    query_counts: dict[QueryId, int] = field(default_factory=dict)
    tables_read: set[TableId] = field(default_factory=set)
    tables_written: set[TableId] = field(default_factory=set)
    observed_duration_us: int = 0
    transaction_order: list[str] = field(default_factory=list)
    transaction_queries: dict[str, list[QueryId]] = field(default_factory=dict)

    def add(self, event: CapturedQueryEvent, query: QueryIR) -> None:
        if self.entry_point is None and query.call_sites:
            self.entry_point = query.call_sites[0]
        self.query_counts[query.id] = self.query_counts.get(query.id, 0) + 1
        if query.statement_class is StatementClass.READ:
            self.tables_read.update(query.relations)
        elif query.statement_class is StatementClass.WRITE:
            self.tables_written.update(query.relations)
        self.observed_duration_us += event.duration_us
        if event.transaction_id is not None:
            if event.transaction_id not in self.transaction_queries:
                self.transaction_order.append(event.transaction_id)
                self.transaction_queries[event.transaction_id] = []
            self.transaction_queries[event.transaction_id].append(query.id)

    def build(
        self, operation_id_value: str, transaction_outcomes: Mapping[str, bool]
    ) -> OperationIR:
        transactions = tuple(
            TransactionIR(
                correlation_id=correlation_id,
                queries=tuple(self.transaction_queries[correlation_id]),
                # A transaction never explicitly committed or rolled back before
                # capture ended (still open, or handled below SQLAlchemy) is
                # treated as not committed — `domain.capture_event.CaptureSummary`'s
                # same "state the honest boundary, never guess" default.
                committed=transaction_outcomes.get(correlation_id, False),
            )
            for correlation_id in self.transaction_order
        )
        return OperationIR(
            id=operation_id_value,
            phase=self.phase,
            transactions=transactions,
            query_counts=dict(self.query_counts),
            tables_read=tuple(sorted(self.tables_read)),
            tables_written=tuple(sorted(self.tables_written)),
            observed_duration_us=self.observed_duration_us or None,
            entry_point=self.entry_point,
        )


def reconstruct_workload(
    events: Sequence[CapturedQueryEvent],
    *,
    schema: SchemaIR,
    transaction_outcomes: Mapping[str, bool] = {},
    coverage: WorkloadCoverage,
    boundary_note: str,
    selected_tests: int = 0,
    passed_tests: int = 0,
    failed_tests: int = 0,
) -> WorkloadIR:
    """Order events by monotonic sequence, parse and fingerprint each
    statement, group identical fingerprints, and build the operation ->
    transaction -> query -> relation edges `docs/TECHNICAL_DESIGN.md` section
    12 requires — one `OperationIR` per distinct (pytest node id, phase).
    """
    queries: dict[QueryId, QueryIR] = {}
    operations: dict[str, _OperationBuilder] = {}
    operation_order: list[str] = []

    for event in sorted(events, key=lambda captured: captured.sequence):
        query = parse_query(event.statement, schema=schema, call_sites=event.call_sites)
        existing = queries.get(query.id)
        if existing is None:
            queries[query.id] = query
        else:
            merged_sites = tuple(dict.fromkeys((*existing.call_sites, *query.call_sites)))
            if merged_sites != existing.call_sites:
                queries[query.id] = existing.model_copy(update={"call_sites": merged_sites})

        op_key = operation_id(_ADAPTER_KIND, event.node_id, event.phase.value)
        builder = operations.get(op_key)
        if builder is None:
            builder = _OperationBuilder(phase=event.phase)
            operations[op_key] = builder
            operation_order.append(op_key)
        # The per-event `query` (this event's own call sites), not the merged
        # dict entry: an operation's `entry_point` must reflect its own stack,
        # never one merged in from a different operation's occurrence of the
        # same fingerprint.
        builder.add(event, query)

    return WorkloadIR(
        coverage=coverage,
        boundary_note=boundary_note,
        queries=tuple(queries.values()),
        operations=tuple(
            operations[op_key].build(op_key, transaction_outcomes) for op_key in operation_order
        ),
        selected_tests=selected_tests,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
    )
