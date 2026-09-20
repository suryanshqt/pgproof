"""Workload/index: a foreign key column with no covering index.

`docs/TECHNICAL_DESIGN.md` section 14's workload/index family: "unindexed FK
stays advisory." Deliberately conservative: when any migration index operation
was not statically resolvable at all (`schema.unsupported`), this rule stays
silent for the whole schema rather than risk a false positive against an index
it simply could not see — an expression/composite index BE-08's parser could
not interpret is reported as `UnsupportedConstruct`, not as a missing `IndexIR`,
so treating that schema's absence of a resolved index as "no index exists"
would be a guess, not a finding.
"""

from __future__ import annotations

from pgproof.domain.identifiers import column_names, table_names
from pgproof.domain.ir.schema import ConstraintKind
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
)
from pgproof.rules.base import RuleContext

RULE_ID = "workload.unindexed_foreign_key"
_UNRESOLVED_INDEX_MARKER = "create_index"


def _covered_leading_columns(ctx: RuleContext) -> frozenset[str]:
    covered = {
        index.keys[0].column
        for index in ctx.physical.indexes
        if index.keys and index.keys[0].column
    }
    covered |= {
        constraint.columns[0]
        for constraint in ctx.physical.constraints
        if constraint.columns
        and constraint.kind in (ConstraintKind.PRIMARY_KEY, ConstraintKind.UNIQUE)
    }
    return frozenset(covered)


def _index_data_incomplete(ctx: RuleContext) -> bool:
    return any(_UNRESOLVED_INDEX_MARKER in item.reason for item in ctx.physical.unsupported)


def unindexed_foreign_key(ctx: RuleContext) -> RecommendationSet:
    if _index_data_incomplete(ctx):
        return RecommendationSet(
            unsupported_reasons=(
                "index-candidate analysis skipped: an index operation in the migration "
                "history was not statically resolvable, so absence of a covering index "
                "cannot be confirmed",
            )
        )
    covered = _covered_leading_columns(ctx)
    foreign_keys = [
        constraint
        for constraint in ctx.physical.constraints
        if constraint.kind is ConstraintKind.FOREIGN_KEY
        and len(constraint.columns) == 1
        and constraint.columns[0] not in covered
    ]
    recommendations = []
    for sequence, constraint in enumerate(
        sorted(foreign_keys, key=lambda c: c.columns[0]), start=1
    ):
        table_name = table_names(constraint.table)[1]
        column_id = constraint.columns[0]
        column_name = column_names(column_id)[2]
        recommendations.append(
            Recommendation(
                id=f"IDX-{sequence:03d}",
                rule=RULE_ID,
                rule_version=1,
                title=f"Index {table_name}.{column_name}",
                priority=RecommendationPriority.WORTH_EVALUATING,
                category=RecommendationCategory.QUERY,
                statement=(
                    f"{table_name}.{column_name} is a foreign key with no covering index; "
                    "lookups and cascading operations on it scan the table."
                ),
                affected_objects=(column_id,),
                proposed_change=ProposedChange(
                    kind=ChangeKind.ADD_INDEX,
                    summary=f"Add a btree index on {table_name}.{column_name}.",
                ),
            )
        )
    return RecommendationSet(recommendations=tuple(recommendations))
