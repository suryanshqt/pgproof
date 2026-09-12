"""Material questions.

`docs/TECHNICAL_DESIGN.md` section 15 requires a question to carry why it matters
and what it changes, so a questionnaire cannot become decorative. `unknown` is a
valid answer and is never replaced by a fabricated guess.
"""

from __future__ import annotations

from pgproof.domain.evidence import EvidenceKind
from pgproof.domain.identifiers import QuestionId, RecommendationId
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
