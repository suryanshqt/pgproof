"""ContextIR: what the developer confirmed, which code cannot reveal.

`docs/PRODUCT_SPEC.md` section 8 makes `unknown` a first-class answer, so an
unanswered question is represented explicitly rather than by absence. A guessed
default is never written.
"""

from __future__ import annotations

import hashlib

from pgproof.domain.identifiers import QuestionId, TableId
from pgproof.domain.primitives import (
    Contract,
    DecimalString,
    NonEmptyText,
    Sha256,
    SnakeCaseEnum,
)


class AnswerState(SnakeCaseEnum):
    ANSWERED = "answered"
    UNKNOWN = "unknown"
    NOT_ASKED = "not_asked"


class TenantModel(SnakeCaseEnum):
    SINGLE_TENANT = "single_tenant"
    SHARED_SCHEMA_TENANT_ID = "shared_schema_tenant_id"
    SCHEMA_PER_TENANT = "schema_per_tenant"
    DATABASE_PER_TENANT = "database_per_tenant"
    UNKNOWN = "unknown"


class ContextAnswer(Contract):
    """One interview answer, with the state that makes 'unknown' explicit."""

    question: QuestionId
    state: AnswerState
    value: NonEmptyText | None = None
    note: NonEmptyText | None = None


class TableScale(Contract):
    """Present and expected row counts. Decimal strings keep exactness."""

    table: TableId
    current_rows: DecimalString | None = None
    rows_in_twelve_months: DecimalString | None = None


class ConsistencyRequirement(Contract):
    """An operation that must read its own writes immediately."""

    operation_label: NonEmptyText
    requires_read_after_write: bool
    lag_tolerance_seconds: int | None = None


class ContextIR(Contract):
    """Confirmed requirements. Anything absent stays unknown, never assumed."""

    answers: tuple[ContextAnswer, ...] = ()
    critical_operations: tuple[NonEmptyText, ...] = ()
    table_scales: tuple[TableScale, ...] = ()
    read_write_ratio: NonEmptyText | None = None
    peak_requests_per_second: int | None = None
    tenant_model: TenantModel = TenantModel.UNKNOWN
    consistency_requirements: tuple[ConsistencyRequirement, ...] = ()
    rpo: NonEmptyText | None = None
    rto: NonEmptyText | None = None
    retention_constraints: tuple[NonEmptyText, ...] = ()


def context_cache_key(context: ContextIR) -> Sha256:
    """A content hash of the confirmed context, so a stage that declares this as
    an input invalidates exactly when an answer actually changes — never when an
    unrelated stage reruns. Same `sha256:`-prefixed shape as `domain.cache` and
    `store.artifacts`, computed independently since `domain` may not import `store`.
    """
    digest = hashlib.sha256(context.canonical_json().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
