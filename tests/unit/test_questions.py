"""Core questions: the seven-question interview, dynamic skipping, answer derivation."""

import pytest

from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.context import (
    AnswerState,
    ContextIR,
    TableScale,
    TenantModel,
    context_cache_key,
)
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR
from pgproof.domain.questions import (
    CORE_CRITICAL_OPERATIONS,
    CORE_QUESTIONS,
    CORE_READ_AFTER_WRITE,
    CORE_READ_WRITE_MIX,
    CORE_RETENTION,
    CORE_RPO_RTO,
    CORE_TENANT_MODEL,
    MaterialQuestion,
    applicable_core_questions,
    apply_core_answer,
    apply_table_scale_answer,
)


def _column(table: str, name: str) -> ColumnIR:
    return ColumnIR(
        id=column_id(table_id("public", table), name),
        name=name,
        data_type="int",
        nullable=False,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )


def _schema(*columns: ColumnIR) -> SchemaIR:
    table = TableIR(
        id=table_id("public", "orders"),
        schema_name="public",
        name="orders",
        columns=columns,
        provenance=SchemaProvenance.STATIC_MIGRATION,
    )
    return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION, tables=(table,))


# --------------------------------------------------------------------------- #
# The seven core questions, and dynamic skipping
# --------------------------------------------------------------------------- #
def test_there_are_exactly_seven_core_questions() -> None:
    assert len(CORE_QUESTIONS) == 7


def test_no_tenant_shaped_column_skips_the_tenant_model_question() -> None:
    schema = _schema(_column("orders", "id"), _column("orders", "user_id"))
    applicable = applicable_core_questions(schema)
    assert len(applicable) == 6
    assert CORE_TENANT_MODEL not in {q.id for q in applicable}


def test_a_tenant_shaped_column_keeps_all_seven_questions() -> None:
    schema = _schema(_column("orders", "id"), _column("orders", "tenant_id"))
    applicable = applicable_core_questions(schema)
    assert len(applicable) == 7


def test_an_empty_schema_skips_the_tenant_model_question() -> None:
    schema = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    assert len(applicable_core_questions(schema)) == 6


# --------------------------------------------------------------------------- #
# Answer derivation
# --------------------------------------------------------------------------- #
def test_critical_operations_splits_on_comma() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout, refund"
    )
    assert context.critical_operations == ("checkout", "refund")
    assert len(context.answers) == 1
    assert context.answers[0].state is AnswerState.ANSWERED


def test_an_unknown_answer_is_recorded_but_never_derives_a_value() -> None:
    context = apply_core_answer(ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.UNKNOWN)
    assert context.critical_operations == ()
    assert context.answers[0].state is AnswerState.UNKNOWN


def test_answering_a_question_twice_replaces_the_earlier_answer() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout"
    )
    context = apply_core_answer(
        context, CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="refund"
    )
    assert context.critical_operations == ("refund",)
    assert len(context.answers) == 1


def test_read_write_mix_splits_ratio_and_peak() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_WRITE_MIX, state=AnswerState.ANSWERED, value="80:20, 100"
    )
    assert context.read_write_ratio == "80:20"
    assert context.peak_requests_per_second == 100


def test_read_write_mix_with_a_non_numeric_peak_leaves_peak_unset() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_WRITE_MIX, state=AnswerState.ANSWERED, value="80:20, a lot"
    )
    assert context.read_write_ratio == "80:20"
    assert context.peak_requests_per_second is None


def test_read_write_mix_with_no_comma_keeps_the_whole_text_and_no_peak() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_WRITE_MIX, state=AnswerState.ANSWERED, value="mostly reads"
    )
    assert context.read_write_ratio == "mostly reads"
    assert context.peak_requests_per_second is None


def test_tenant_model_resolves_a_valid_choice() -> None:
    context = apply_core_answer(
        ContextIR(),
        CORE_TENANT_MODEL,
        state=AnswerState.ANSWERED,
        value="shared_schema_tenant_id",
    )
    assert context.tenant_model is TenantModel.SHARED_SCHEMA_TENANT_ID


def test_tenant_model_with_an_invalid_choice_is_not_applied() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_TENANT_MODEL, state=AnswerState.ANSWERED, value="not-a-real-choice"
    )
    assert context.tenant_model is TenantModel.UNKNOWN


def test_read_after_write_builds_one_requirement_per_flow() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_AFTER_WRITE, state=AnswerState.ANSWERED, value="checkout, invoice"
    )
    assert [r.operation_label for r in context.consistency_requirements] == ["checkout", "invoice"]
    assert all(r.requires_read_after_write for r in context.consistency_requirements)


def test_rpo_rto_splits_both_targets() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_RPO_RTO, state=AnswerState.ANSWERED, value="5m, 30m"
    )
    assert context.rpo == "5m"
    assert context.rto == "30m"


def test_rpo_rto_with_no_comma_sets_only_rpo() -> None:
    context = apply_core_answer(ContextIR(), CORE_RPO_RTO, state=AnswerState.ANSWERED, value="5m")
    assert context.rpo == "5m"
    assert context.rto is None


def test_a_non_core_question_id_records_the_answer_and_derives_nothing() -> None:
    context = apply_core_answer(
        ContextIR(), "some_rule_emitted_question", state=AnswerState.ANSWERED, value="anything"
    )
    assert context.critical_operations == ()
    assert context.answers[0].question == "some_rule_emitted_question"


def test_retention_splits_on_comma() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_RETENTION, state=AnswerState.ANSWERED, value="GDPR, 7-year audit log"
    )
    assert context.retention_constraints == ("GDPR", "7-year audit log")


def test_table_scale_is_set_directly_bypassing_string_parsing() -> None:
    scale = TableScale(
        table=table_id("public", "orders"), current_rows="100", rows_in_twelve_months="1000"
    )
    context = apply_table_scale_answer(ContextIR(), (scale,), state=AnswerState.ANSWERED)
    assert context.table_scales == (scale,)
    assert context.answers[0].state is AnswerState.ANSWERED


def test_table_scale_unknown_records_the_state_without_setting_scales() -> None:
    context = apply_table_scale_answer(ContextIR(), (), state=AnswerState.UNKNOWN)
    assert context.table_scales == ()
    assert context.answers[0].state is AnswerState.UNKNOWN


# --------------------------------------------------------------------------- #
# Context cache key: changing an answer changes the key, nothing else does
# --------------------------------------------------------------------------- #
def test_context_cache_key_changes_when_an_answer_changes() -> None:
    before = context_cache_key(ContextIR())
    after = context_cache_key(
        apply_core_answer(
            ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout"
        )
    )
    assert before != after


def test_context_cache_key_is_stable_for_identical_content() -> None:
    a = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout"
    )
    b = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout"
    )
    assert context_cache_key(a) == context_cache_key(b)


def test_unrelated_questions_do_not_affect_each_others_derived_fields() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout"
    )
    context = apply_core_answer(context, CORE_RETENTION, state=AnswerState.ANSWERED, value="GDPR")
    assert context.critical_operations == ("checkout",)
    assert context.retention_constraints == ("GDPR",)
    assert len(context.answers) == 2


@pytest.mark.parametrize("question", CORE_QUESTIONS, ids=lambda q: q.id)
def test_every_core_question_names_why_it_matters(question: MaterialQuestion) -> None:
    assert question.why_it_matters
    assert question.unknown_is_acceptable is True
