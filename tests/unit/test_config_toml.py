"""`pgproof.toml` round trip: context answers, unknown states, and unowned sections."""

from pathlib import Path

import pytest

from pgproof.adapters.repository import config_toml
from pgproof.adapters.repository.config_toml import read_config, write_config
from pgproof.domain.config import ProjectConfig, UnsupportedConfigVersionError
from pgproof.domain.ir.context import AnswerState, ContextIR, TableScale, TenantModel
from pgproof.domain.questions import (
    CORE_CRITICAL_OPERATIONS,
    CORE_READ_AFTER_WRITE,
    CORE_READ_WRITE_MIX,
    CORE_RETENTION,
    CORE_RPO_RTO,
    CORE_TENANT_MODEL,
    apply_core_answer,
    apply_table_scale_answer,
)
from pgproof.ports.config import ConfigReaderPort, ConfigWriterPort


def test_the_adapter_functions_satisfy_the_config_port_shape() -> None:
    reader: ConfigReaderPort = read_config
    writer: ConfigWriterPort = write_config
    assert callable(reader)
    assert callable(writer)


def test_a_missing_file_reads_as_the_default_config(tmp_path: Path) -> None:
    config = read_config(tmp_path / "pgproof.toml")
    assert config == ProjectConfig()


def test_writing_then_reading_reproduces_the_same_config(tmp_path: Path) -> None:
    context = apply_core_answer(
        ContextIR(), CORE_CRITICAL_OPERATIONS, state=AnswerState.ANSWERED, value="checkout, refund"
    )
    context = apply_core_answer(
        context, CORE_TENANT_MODEL, state=AnswerState.ANSWERED, value="single_tenant"
    )
    context = apply_table_scale_answer(
        context,
        (TableScale(table="public.orders", current_rows="100", rows_in_twelve_months="1000"),),
        state=AnswerState.ANSWERED,
    )
    config = ProjectConfig(context=context)
    path = tmp_path / "pgproof.toml"
    write_config(path, config)
    assert read_config(path) == config


def test_an_unknown_answer_round_trips_as_unknown_not_as_absence(tmp_path: Path) -> None:
    context = apply_core_answer(ContextIR(), CORE_TENANT_MODEL, state=AnswerState.UNKNOWN)
    path = tmp_path / "pgproof.toml"
    write_config(path, ProjectConfig(context=context))
    reloaded = read_config(path)
    assert reloaded.context.answers[0].state is AnswerState.UNKNOWN
    assert reloaded.context.tenant_model is TenantModel.UNKNOWN


def test_a_section_this_module_does_not_own_round_trips_unchanged(tmp_path: Path) -> None:
    config = ProjectConfig(
        extra_sections={"project": {"orm": "sqlalchemy", "postgres_version": "17"}}
    )
    path = tmp_path / "pgproof.toml"
    write_config(path, config)
    reloaded = read_config(path)
    assert reloaded.extra_sections == {"project": {"orm": "sqlalchemy", "postgres_version": "17"}}


def test_read_after_write_flows_round_trip() -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_AFTER_WRITE, state=AnswerState.ANSWERED, value="checkout, invoice"
    )
    toml_table = config_toml._context_to_toml(context)
    assert toml_table["read_after_write"] == ["checkout", "invoice"]
    restored = config_toml._toml_to_context(toml_table)
    assert [r.operation_label for r in restored.consistency_requirements] == ["checkout", "invoice"]


def test_retention_and_rpo_rto_round_trip(tmp_path: Path) -> None:
    context = apply_core_answer(
        ContextIR(), CORE_RETENTION, state=AnswerState.ANSWERED, value="GDPR"
    )
    context = apply_core_answer(context, CORE_RPO_RTO, state=AnswerState.ANSWERED, value="5m, 30m")
    path = tmp_path / "pgproof.toml"
    write_config(path, ProjectConfig(context=context))
    reloaded = read_config(path)
    assert reloaded.context.retention_constraints == ("GDPR",)
    assert reloaded.context.rpo == "5m"
    assert reloaded.context.rto == "30m"


def test_read_write_ratio_and_peak_round_trip(tmp_path: Path) -> None:
    context = apply_core_answer(
        ContextIR(), CORE_READ_WRITE_MIX, state=AnswerState.ANSWERED, value="80:20, 100"
    )
    path = tmp_path / "pgproof.toml"
    write_config(path, ProjectConfig(context=context))
    reloaded = read_config(path)
    assert reloaded.context.read_write_ratio == "80:20"
    assert reloaded.context.peak_requests_per_second == 100


def test_an_unsupported_config_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "pgproof.toml"
    path.write_text("config_version = 99\n", encoding="utf-8")
    with pytest.raises(UnsupportedConfigVersionError):
        read_config(path)


def test_a_non_table_top_level_key_is_dropped_defensively(tmp_path: Path) -> None:
    path = tmp_path / "pgproof.toml"
    path.write_text('config_version = 1\nstray = "value"\n', encoding="utf-8")
    config = read_config(path)
    assert config.extra_sections == {}


def test_an_empty_context_writes_no_context_table(tmp_path: Path) -> None:
    path = tmp_path / "pgproof.toml"
    write_config(path, ProjectConfig())
    assert "[context]" not in path.read_text()


def test_an_invalid_tenant_model_value_on_disk_reads_as_unknown(tmp_path: Path) -> None:
    path = tmp_path / "pgproof.toml"
    path.write_text(
        'config_version = 1\n\n[context]\ntenant_model = "not-real"\n', encoding="utf-8"
    )
    config = read_config(path)
    assert config.context.tenant_model is TenantModel.UNKNOWN
