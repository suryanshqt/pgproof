"""Orchestrates the core interview: which questions remain, and recording an answer.

Pure coordination over `pgproof.domain.questions`/`pgproof.domain.ir.context`;
no filesystem or Click import belongs here — `cli.commands.configure` reads and
writes `pgproof.toml` through a `ConfigReaderPort`/`ConfigWriterPort` and does
the interactive prompting, then calls back into this module for every decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgproof.domain.ir.context import AnswerState, ContextIR, TableScale
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.questions import (
    CORE_TABLE_SCALE,
    MaterialQuestion,
    applicable_core_questions,
    apply_core_answer,
    apply_table_scale_answer,
)


@dataclass(frozen=True)
class InterviewState:
    """The core interview at one point in time: what applies, and what is left."""

    applicable: tuple[MaterialQuestion, ...]
    remaining: tuple[MaterialQuestion, ...]
    context: ContextIR


def build_state(schema: SchemaIR, context: ContextIR) -> InterviewState:
    """Dynamic skipping plus already-answered questions, combined into one list."""
    applicable = applicable_core_questions(schema)
    answered = {answer.question for answer in context.answers}
    remaining = tuple(question for question in applicable if question.id not in answered)
    return InterviewState(applicable=applicable, remaining=remaining, context=context)


def missing_decision(state: InterviewState) -> MaterialQuestion | None:
    """The next unanswered question, or `None` when the interview is complete.

    `docs/TECHNICAL_DESIGN.md`: "Non-interactive mode never prompts and fails
    with the missing decision" — this is that decision.
    """
    return state.remaining[0] if state.remaining else None


def record_answer(
    context: ContextIR, question: MaterialQuestion, *, state: AnswerState, value: str | None = None
) -> ContextIR:
    if question.id == CORE_TABLE_SCALE:
        raise ValueError("core_table_scale answers must go through record_table_scale")
    return apply_core_answer(context, question.id, state=state, value=value)


def record_table_scale(
    context: ContextIR, table_scales: tuple[TableScale, ...], *, state: AnswerState
) -> ContextIR:
    return apply_table_scale_answer(context, table_scales, state=state)
