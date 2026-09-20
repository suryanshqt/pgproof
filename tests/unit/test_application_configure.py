"""The interview orchestration: which questions remain, and recording an answer."""

import pytest

from pgproof.application.configure import (
    build_state,
    missing_decision,
    record_answer,
    record_table_scale,
)
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.context import AnswerState, ContextIR
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.questions import (
    CORE_QUESTIONS,
    CORE_TABLE_SCALE,
    CORE_TENANT_MODEL,
    MaterialQuestion,
)


def _schema(*column_names: str) -> SchemaIR:
    columns = tuple(
        ColumnIR(
            id=column_id(table_id("public", "orders"), name),
            name=name,
            data_type="int",
            nullable=False,
            provenance=SchemaProvenance.STATIC_MIGRATION,
        )
        for name in column_names
    )
    table = TableIR(
        id=table_id("public", "orders"),
        schema_name="public",
        name="orders",
        columns=columns,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, tables=(table,))


def _question(question_id: str) -> MaterialQuestion:
    return next(q for q in CORE_QUESTIONS if q.id == question_id)


def test_a_fresh_context_has_every_applicable_question_remaining() -> None:
    state = build_state(_schema("id", "tenant_id"), ContextIR())
    assert state.remaining == state.applicable
    assert len(state.remaining) == 7


def test_a_schema_with_no_tenant_column_has_six_remaining() -> None:
    state = build_state(_schema("id"), ContextIR())
    assert len(state.remaining) == 6
    assert CORE_TENANT_MODEL not in {q.id for q in state.remaining}


def test_missing_decision_returns_the_first_remaining_question() -> None:
    state = build_state(_schema("id"), ContextIR())
    assert missing_decision(state) == state.remaining[0]


def test_missing_decision_is_none_once_every_question_is_answered() -> None:
    schema = _schema("id")
    context = ContextIR()
    for question in build_state(schema, context).applicable:
        if question.id == CORE_TABLE_SCALE:
            context = record_table_scale(context, (), state=AnswerState.UNKNOWN)
        else:
            context = record_answer(context, question, state=AnswerState.UNKNOWN)
    assert missing_decision(build_state(schema, context)) is None


def test_record_answer_rejects_the_table_scale_question() -> None:
    with pytest.raises(ValueError, match="record_table_scale"):
        record_answer(ContextIR(), _question(CORE_TABLE_SCALE), state=AnswerState.UNKNOWN)


def test_record_answer_derives_the_context_field() -> None:
    context = record_answer(
        ContextIR(),
        _question("core_critical_operations"),
        state=AnswerState.ANSWERED,
        value="checkout",
    )
    assert context.critical_operations == ("checkout",)
