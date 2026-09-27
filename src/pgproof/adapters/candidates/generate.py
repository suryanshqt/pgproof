"""Index candidate generation. `docs/TECHNICAL_DESIGN.md` section 21: single
and composite (equality prefix, then one range/order column) B-tree
candidates, structurally deduplicated against the physical schema, capped at
five per query.

v1 generates no partial/expression/include/unique indexes — only plain
ascending B-tree — so dedup only needs to check whether an existing index (or
a PRIMARY KEY/UNIQUE constraint, which creates one implicitly:
`adapters.postgres.catalog`'s own "not separately represented" convention)
already covers a candidate's exact column *prefix*: a real index on
`(a, b, c)` already serves every query `(a)` or `(a, b)` would, so generating
either is redundant, not merely similar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pgproof.adapters.parameters.extract import ExtractedPredicate, PredicateKind
from pgproof.domain.identifiers import ColumnId, TableId, column_names, table_names
from pgproof.domain.ir.schema import ConstraintKind, IndexMethod, SchemaIR, SortDirection

_MAX_CANDIDATES: Final = 5


@dataclass(frozen=True)
class IndexCandidate:
    table: TableId
    columns: tuple[ColumnId, ...]
    apply_sql: str
    revert_sql: str
    supports: tuple[ExtractedPredicate, ...]


@dataclass(frozen=True)
class DiscardedCandidate:
    table: TableId
    columns: tuple[ColumnId, ...]
    reason: str


@dataclass(frozen=True)
class CandidateGenerationResult:
    candidates: tuple[IndexCandidate, ...]
    discarded: tuple[DiscardedCandidate, ...]


def _existing_key_sequences(
    schema: SchemaIR, table: TableId
) -> list[tuple[str, tuple[ColumnId, ...]]]:
    """Every existing plain, full-table, ascending B-tree key sequence that
    could make a same-prefix candidate redundant — name paired with columns,
    for an honest discard reason. A partial or expression index is
    *understood*, not blindly treated as a duplicate: v1 cannot tell whether
    its predicate or expression already covers what a candidate would.
    """
    sequences: list[tuple[str, tuple[ColumnId, ...]]] = []
    for index in schema.indexes:
        if index.table != table or index.method is not IndexMethod.BTREE:
            continue
        if index.predicate is not None:
            continue
        columns: list[ColumnId] = []
        for key in index.keys:
            if key.column is None or key.direction is not SortDirection.ASC:
                columns = []
                break
            columns.append(key.column)
        if columns:
            sequences.append((index.name, tuple(columns)))
    for constraint in schema.constraints:
        if constraint.table != table:
            continue
        if constraint.kind not in (ConstraintKind.PRIMARY_KEY, ConstraintKind.UNIQUE):
            continue
        if constraint.expression is not None or not constraint.columns:
            continue
        sequences.append((constraint.name, constraint.columns))
    return sequences


def _duplicate_of(
    columns: tuple[ColumnId, ...], existing: Sequence[tuple[str, tuple[ColumnId, ...]]]
) -> str | None:
    for name, sequence in existing:
        if sequence[: len(columns)] == columns:
            return name
    return None


def _index_name(table: TableId, columns: tuple[ColumnId, ...]) -> str:
    _, table_name = table_names(table)
    parts = [column_names(column)[2] for column in columns]
    return f"ix_{table_name}_{'_'.join(parts)}"


def _ddl(table: TableId, columns: tuple[ColumnId, ...]) -> tuple[str, str, str]:
    schema_name, table_name = table_names(table)
    name = _index_name(table, columns)
    column_list = ", ".join(column_names(column)[2] for column in columns)
    apply_sql = f'CREATE INDEX {name} ON "{schema_name}"."{table_name}" ({column_list})'
    revert_sql = f'DROP INDEX "{schema_name}"."{name}"'
    return name, apply_sql, revert_sql


def _candidate_shapes(
    predicates: Sequence[ExtractedPredicate],
) -> list[tuple[tuple[ColumnId, ...], tuple[ExtractedPredicate, ...]]]:
    """Single-column candidates for every predicate, plus composites:
    equality-only when >= 2 equality predicates exist, and equality-prefix +
    one range column when both kinds exist on the same table. Composites come
    first — they are the more specific, usually more valuable shape, and the
    five-candidate budget should give them priority over redundant singles.
    """
    equality = [p for p in predicates if p.kind is PredicateKind.EQUALITY]
    ranges = [p for p in predicates if p.kind is not PredicateKind.EQUALITY]
    shapes: list[tuple[tuple[ColumnId, ...], tuple[ExtractedPredicate, ...]]] = []

    if equality and ranges:
        columns = (*(p.column for p in equality), ranges[0].column)
        shapes.append((columns, (*equality, ranges[0])))
    if len(equality) >= 2:
        columns = tuple(p.column for p in equality)
        shapes.append((columns, tuple(equality)))
    for predicate in predicates:
        shapes.append(((predicate.column,), (predicate,)))
    return shapes


def generate_candidates(
    schema: SchemaIR, predicates: Sequence[ExtractedPredicate]
) -> CandidateGenerationResult:
    by_table: dict[TableId, list[ExtractedPredicate]] = {}
    for predicate in predicates:
        by_table.setdefault(predicate.table, []).append(predicate)

    candidates: list[IndexCandidate] = []
    discarded: list[DiscardedCandidate] = []
    seen_columns: set[tuple[TableId, tuple[ColumnId, ...]]] = set()

    for table, table_predicates in by_table.items():
        existing = _existing_key_sequences(schema, table)
        for columns, supports in _candidate_shapes(table_predicates):
            key = (table, columns)
            if key in seen_columns:
                continue
            seen_columns.add(key)
            duplicate_name = _duplicate_of(columns, existing)
            if duplicate_name is not None:
                discarded.append(
                    DiscardedCandidate(
                        table=table,
                        columns=columns,
                        reason=f"duplicate_of_existing_index:{duplicate_name}",
                    )
                )
                continue
            if len(candidates) >= _MAX_CANDIDATES:
                discarded.append(
                    DiscardedCandidate(table=table, columns=columns, reason="over_candidate_budget")
                )
                continue
            _, apply_sql, revert_sql = _ddl(table, columns)
            candidates.append(
                IndexCandidate(
                    table=table,
                    columns=columns,
                    apply_sql=apply_sql,
                    revert_sql=revert_sql,
                    supports=supports,
                )
            )

    return CandidateGenerationResult(candidates=tuple(candidates), discarded=tuple(discarded))
