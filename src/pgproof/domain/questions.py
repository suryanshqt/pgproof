"""Material questions.

`docs/TECHNICAL_DESIGN.md` section 15 requires a question to carry why it matters
and what it changes, so a questionnaire cannot become decorative. `unknown` is a
valid answer and is never replaced by a fabricated guess.

`docs/PRODUCT_SPEC.md` section 8 names the seven core questions the first
interview asks; `CORE_QUESTIONS` and `apply_core_answer` are that interview's
fixed content and the one deterministic mapping from a raw answer to the
`ContextIR` field it resolves. Anything beyond these seven (a rule-emitted
clarification attached to an ambiguous finding, per the same section) is a
plain `MaterialQuestion` this module does not need to know the shape of —
its answer lives only in `ContextIR.answers`, never in a derived field.
"""

from __future__ import annotations

from pgproof.domain.evidence import EvidenceKind
from pgproof.domain.identifiers import QuestionId, RecommendationId
from pgproof.domain.ir.context import (
    AnswerState,
    ConsistencyRequirement,
    ContextAnswer,
    ContextIR,
    TableScale,
    TenantModel,
)
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum


class AnswerSchema(SnakeCaseEnum):
    """The shape an answer may take."""

    FREE_TEXT = "free_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DURATION = "duration"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TABLE_SCALE = "table_scale"


class MaterialQuestion(Contract):
    """A question asked only because an answer changes a decision."""

    id: QuestionId
    prompt: NonEmptyText
    answer_schema: AnswerSchema
    choices: tuple[NonEmptyText, ...] = ()
    why_it_matters: NonEmptyText
    affected_recommendations: tuple[RecommendationId, ...] = ()
    derived_from: EvidenceKind = EvidenceKind.INFERRED
    unknown_is_acceptable: bool = True


CORE_CRITICAL_OPERATIONS: NonEmptyText = "core_critical_operations"
CORE_TABLE_SCALE: NonEmptyText = "core_table_scale"
CORE_READ_WRITE_MIX: NonEmptyText = "core_read_write_mix"
CORE_TENANT_MODEL: NonEmptyText = "core_tenant_model"
CORE_READ_AFTER_WRITE: NonEmptyText = "core_read_after_write"
CORE_RPO_RTO: NonEmptyText = "core_rpo_rto"
CORE_RETENTION: NonEmptyText = "core_retention"

CORE_QUESTIONS: tuple[MaterialQuestion, ...] = (
    MaterialQuestion(
        id=CORE_CRITICAL_OPERATIONS,
        prompt="Which operations are latency-critical? (comma-separated)",
        answer_schema=AnswerSchema.FREE_TEXT,
        why_it_matters="Latency-sensitive operations get priority for index and query rules.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_TABLE_SCALE,
        prompt="What are the present and 12-month row counts for the largest tables?",
        answer_schema=AnswerSchema.TABLE_SCALE,
        why_it_matters="Growth rules depend on where a table is headed, not just where it is.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_READ_WRITE_MIX,
        prompt=(
            "What is the approximate read/write ratio and peak requests per second? "
            "(format: 'ratio, peak', e.g. '80:20, 100')"
        ),
        answer_schema=AnswerSchema.FREE_TEXT,
        why_it_matters="A write-heavy workload changes which index trade-offs are worth it.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_TENANT_MODEL,
        prompt="What is the tenant and isolation model?",
        answer_schema=AnswerSchema.SINGLE_CHOICE,
        choices=tuple(m.value for m in TenantModel if m is not TenantModel.UNKNOWN),
        why_it_matters="Tenant isolation rules only apply once the model is known.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_READ_AFTER_WRITE,
        prompt="Which flows need immediate read-after-write consistency? (comma-separated)",
        answer_schema=AnswerSchema.FREE_TEXT,
        why_it_matters="A flow that must see its own write cannot tolerate replica lag.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_RPO_RTO,
        prompt="What RPO and RTO matter? (format: 'RPO, RTO', e.g. '5m, 30m')",
        answer_schema=AnswerSchema.FREE_TEXT,
        why_it_matters="Backup and failover recommendations depend on the recovery targets.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
    MaterialQuestion(
        id=CORE_RETENTION,
        prompt=(
            "What retention, deletion, audit, or regulatory constraints apply? (comma-separated)"
        ),
        answer_schema=AnswerSchema.FREE_TEXT,
        why_it_matters="A retention obligation can outrank an otherwise-sound cleanup rule.",
        derived_from=EvidenceKind.USER_CONFIRMED,
    ),
)


def _has_tenant_shaped_column(schema: SchemaIR) -> bool:
    return any(column.name == "tenant_id" for table in schema.tables for column in table.columns)


def applicable_core_questions(schema: SchemaIR) -> tuple[MaterialQuestion, ...]:
    """The core interview, minus questions no evidence makes relevant.

    `docs/PRODUCT_SPEC.md` section 8: "Questions are dynamic." The only skip
    implemented is `core_tenant_model` when no column anywhere is named
    `tenant_id` — a structural fact, not a guess about the answer, so the
    question is dropped rather than answered on the developer's behalf.
    """
    if _has_tenant_shaped_column(schema):
        return CORE_QUESTIONS
    return tuple(q for q in CORE_QUESTIONS if q.id != CORE_TENANT_MODEL)


def _split_two(raw: str) -> tuple[str, str | None]:
    """`"a, b"` to `("a", "b")`; a single part is returned with `None`, never guessed."""
    parts = [part.strip() for part in raw.split(",", 1)]
    if len(parts) == 2 and parts[1]:
        return parts[0], parts[1]
    return raw.strip(), None


def _split_list(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def apply_core_answer(
    context: ContextIR, question_id: str, *, state: AnswerState, value: str | None = None
) -> ContextIR:
    """Record one core-question answer, deriving its `ContextIR` field when answered.

    An `unknown`/`not_asked` state is recorded in `answers` alone: a derived
    field never receives a fabricated value just because a question was asked.
    """
    answers = (
        *(a for a in context.answers if a.question != question_id),
        ContextAnswer(question=question_id, state=state, value=value),
    )
    context = context.model_copy(update={"answers": answers})
    if state is not AnswerState.ANSWERED or value is None:
        return context

    if question_id == CORE_CRITICAL_OPERATIONS:
        return context.model_copy(update={"critical_operations": _split_list(value)})
    if question_id == CORE_READ_WRITE_MIX:
        ratio, peak = _split_two(value)
        update: dict[str, object] = {"read_write_ratio": ratio}
        if peak is not None and peak.isdigit():
            update["peak_requests_per_second"] = int(peak)
        return context.model_copy(update=update)
    if question_id == CORE_TENANT_MODEL:
        try:
            tenant_model = TenantModel(value)
        except ValueError:
            return context
        return context.model_copy(update={"tenant_model": tenant_model})
    if question_id == CORE_READ_AFTER_WRITE:
        requirements = tuple(
            ConsistencyRequirement(operation_label=label, requires_read_after_write=True)
            for label in _split_list(value)
        )
        return context.model_copy(update={"consistency_requirements": requirements})
    if question_id == CORE_RPO_RTO:
        rpo, rto = _split_two(value)
        update = {"rpo": rpo}
        if rto is not None:
            update["rto"] = rto
        return context.model_copy(update=update)
    if question_id == CORE_RETENTION:
        return context.model_copy(update={"retention_constraints": _split_list(value)})
    return context


def apply_table_scale_answer(
    context: ContextIR, table_scales: tuple[TableScale, ...], *, state: AnswerState
) -> ContextIR:
    """`core_table_scale`'s dedicated setter: a row-count table has no honest
    single-string representation, so it bypasses `apply_core_answer`'s generic
    value-string parsing entirely.
    """
    answers = (
        *(a for a in context.answers if a.question != CORE_TABLE_SCALE),
        ContextAnswer(question=CORE_TABLE_SCALE, state=state),
    )
    context = context.model_copy(update={"answers": answers})
    if state is not AnswerState.ANSWERED:
        return context
    return context.model_copy(update={"table_scales": table_scales})
