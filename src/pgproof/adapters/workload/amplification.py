"""Repeated-query, possible-amplification, and observed-N+1 classification.
`docs/TECHNICAL_DESIGN.md` section 23.

Beside `reconstruct.py` for the same reason: classification reads per-occurrence
bind hashes and row counts off the raw `CapturedQueryEvent` stream, which
`WorkloadIR`'s aggregated `query_counts` no longer carries, and it reuses
BE-19's parser for query identity (`application` may not import `adapters`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pgproof.adapters.sql.parser import parse_query
from pgproof.domain.capture_event import CapturedQueryEvent
from pgproof.domain.identifiers import QueryId, TableId, operation_id
from pgproof.domain.ir.schema import ConstraintKind, SchemaIR
from pgproof.domain.ir.workload import (
    AmplificationClass,
    AmplificationIR,
    QueryIR,
    StatementClass,
    WorkloadIR,
)
from pgproof.domain.sources import SourceRef

_ADAPTER_KIND = "pytest"


@dataclass(frozen=True)
class _Occurrence:
    """One cursor execution, reduced to what classification compares."""

    query_id: QueryId
    statement_class: StatementClass
    relations: tuple[TableId, ...]
    bind_signature: tuple[str | None, ...]
    rowcount: int | None
    call_site: SourceRef | None


def _occurrence(event: CapturedQueryEvent, query: QueryIR) -> _Occurrence:
    return _Occurrence(
        query_id=query.id,
        statement_class=query.statement_class,
        relations=query.relations,
        bind_signature=tuple(parameter.value_hash for parameter in event.parameters),
        rowcount=event.rowcount,
        # This event's own call sites, never `QueryIR.call_sites` from
        # `workload.queries`: those are merged across operations, so the
        # deduplicated entry can name a frame from a different test.
        call_site=event.call_sites[0] if event.call_sites else None,
    )


def _classify(parent: _Occurrence, children: Sequence[_Occurrence]) -> AmplificationClass:
    if len({child.bind_signature for child in children}) == 1:
        return AmplificationClass.REPEATED_QUERY
    if parent.statement_class is StatementClass.READ and parent.rowcount == len(children):
        return AmplificationClass.OBSERVED_N_PLUS_ONE
    return AmplificationClass.POSSIBLE_AMPLIFICATION


def _relationship_name(schema: SchemaIR, parent: _Occurrence, child: _Occurrence) -> str | None:
    """The physical foreign key linking child to parent, or `None` rather than
    a guess when either side is not exactly one relation or the match is not
    unique.
    """
    if len(parent.relations) != 1 or len(child.relations) != 1:
        return None
    names = [
        constraint.name
        for constraint in schema.constraints
        if constraint.kind is ConstraintKind.FOREIGN_KEY
        and constraint.table == child.relations[0]
        and constraint.referenced_table == parent.relations[0]
    ]
    return names[0] if len(names) == 1 else None


def _amplifications(
    occurrences: Sequence[_Occurrence], *, schema: SchemaIR, min_repetitions: int
) -> tuple[AmplificationIR, ...]:
    positions: dict[QueryId, list[int]] = {}
    for index, occurrence in enumerate(occurrences):
        positions.setdefault(occurrence.query_id, []).append(index)

    found: list[AmplificationIR] = []
    for query_id, indexes in positions.items():
        if len(indexes) < min_repetitions:
            continue
        parent = next(
            (
                earlier
                for earlier in reversed(occurrences[: indexes[0]])
                if earlier.query_id != query_id
            ),
            None,
        )
        # ponytail: a repetition with no distinct query before it in the
        # operation is dropped, since there is nothing honest to name as
        # `parent_query`; give it a self-referential parent if real captures
        # turn out to hit this.
        if parent is None:
            continue
        children = [occurrences[index] for index in indexes]
        found.append(
            AmplificationIR(
                classification=_classify(parent, children),
                parent_query=parent.query_id,
                child_query=query_id,
                repetitions=len(children),
                relationship_name=_relationship_name(schema, parent, children[0]),
                call_site=children[0].call_site,
            )
        )
    return tuple(found)


def annotate_amplifications(
    events: Sequence[CapturedQueryEvent],
    workload: WorkloadIR,
    *,
    schema: SchemaIR,
    # ponytail: section 23 calls the threshold configurable; there is no config
    # plumbing for it yet, so the upgrade path is a `pgproof capture` flag.
    min_repetitions: int = 5,
) -> WorkloadIR:
    """Return `workload` with each operation's `amplifications` populated: one
    `AmplificationIR` per query repeated at least `min_repetitions` times
    within that operation, attributed to the nearest distinct query that ran
    before the repetition started.
    """
    parsed: dict[str, QueryIR] = {}
    by_operation: dict[str, list[_Occurrence]] = {}
    for event in sorted(events, key=lambda captured: captured.sequence):
        # Keyed by statement alone: call sites vary per occurrence but change
        # neither the fingerprint nor the relations this reads.
        query = parsed.get(event.statement)
        if query is None:
            query = parse_query(event.statement, schema=schema)
            parsed[event.statement] = query
        key = operation_id(_ADAPTER_KIND, event.node_id, event.phase.value)
        by_operation.setdefault(key, []).append(_occurrence(event, query))

    operations = tuple(
        operation.model_copy(
            update={
                "amplifications": _amplifications(
                    by_operation.get(operation.id, ()),
                    schema=schema,
                    min_repetitions=min_repetitions,
                )
            }
        )
        for operation in workload.operations
    )
    return workload.model_copy(update={"operations": operations})
