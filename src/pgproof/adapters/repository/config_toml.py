"""`pgproof.toml` reading and writing.

`docs/TECHNICAL_DESIGN.md` section 3's own example TOML shows only the derived
`[context]` values (`tenant_model`, `rpo`, `rto`, ...), not the raw per-question
`answers` a round trip needs to distinguish "not asked" from "asked, unknown"
on reload. `[[context.answers]]` and `[[context.table_scales]]` are this
module's necessary elaboration of that example, not a contradiction of it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomli_w

from pgproof.domain.config import ProjectConfig
from pgproof.domain.ir.context import (
    AnswerState,
    ConsistencyRequirement,
    ContextAnswer,
    ContextIR,
    TableScale,
    TenantModel,
)

_RESERVED_KEYS = ("config_version", "context")


def _context_to_toml(context: ContextIR) -> dict[str, Any]:
    table: dict[str, Any] = {}
    if context.critical_operations:
        table["critical_operations"] = list(context.critical_operations)
    if context.read_write_ratio is not None:
        table["read_write_ratio"] = context.read_write_ratio
    if context.peak_requests_per_second is not None:
        table["peak_requests_per_second"] = context.peak_requests_per_second
    if context.tenant_model is not TenantModel.UNKNOWN:
        table["tenant_model"] = context.tenant_model.value
    read_after_write = [
        r.operation_label for r in context.consistency_requirements if r.requires_read_after_write
    ]
    if read_after_write:
        table["read_after_write"] = read_after_write
    if context.rpo is not None:
        table["rpo"] = context.rpo
    if context.rto is not None:
        table["rto"] = context.rto
    if context.retention_constraints:
        table["retention_constraints"] = list(context.retention_constraints)
    if context.table_scales:
        table["table_scales"] = [
            {
                key: value
                for key, value in (
                    ("table", scale.table),
                    ("current_rows", scale.current_rows),
                    ("rows_in_twelve_months", scale.rows_in_twelve_months),
                )
                if value is not None
            }
            for scale in context.table_scales
        ]
    if context.answers:
        table["answers"] = [
            {
                key: value
                for key, value in (
                    ("question", answer.question),
                    ("state", answer.state.value),
                    ("value", answer.value),
                    ("note", answer.note),
                )
                if value is not None
            }
            for answer in context.answers
        ]
    return table


def _toml_to_context(table: dict[str, Any]) -> ContextIR:
    tenant_model = TenantModel.UNKNOWN
    raw_tenant_model = table.get("tenant_model")
    if raw_tenant_model is not None:
        try:
            tenant_model = TenantModel(raw_tenant_model)
        except ValueError:
            tenant_model = TenantModel.UNKNOWN
    consistency_requirements = tuple(
        ConsistencyRequirement(operation_label=label, requires_read_after_write=True)
        for label in table.get("read_after_write", [])
    )
    table_scales = tuple(
        TableScale(
            table=row["table"],
            current_rows=row.get("current_rows"),
            rows_in_twelve_months=row.get("rows_in_twelve_months"),
        )
        for row in table.get("table_scales", [])
    )
    answers = tuple(
        ContextAnswer(
            question=row["question"],
            state=AnswerState(row["state"]),
            value=row.get("value"),
            note=row.get("note"),
        )
        for row in table.get("answers", [])
    )
    return ContextIR(
        answers=answers,
        critical_operations=tuple(table.get("critical_operations", ())),
        table_scales=table_scales,
        read_write_ratio=table.get("read_write_ratio"),
        peak_requests_per_second=table.get("peak_requests_per_second"),
        tenant_model=tenant_model,
        consistency_requirements=consistency_requirements,
        rpo=table.get("rpo"),
        rto=table.get("rto"),
        retention_constraints=tuple(table.get("retention_constraints", ())),
    )


def read_config(path: Path) -> ProjectConfig:
    """A missing file reads as the all-defaults `ProjectConfig`: `configure` on a
    fresh repository has nothing to fail on, only questions to ask.
    """
    if not path.is_file():
        return ProjectConfig()
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    version = document.get("config_version", ProjectConfig.model_fields["config_version"].default)
    ProjectConfig.require_supported(version)
    extra_sections = {
        key: value
        for key, value in document.items()
        if key not in _RESERVED_KEYS and isinstance(value, dict)
    }
    return ProjectConfig(
        config_version=version,
        context=_toml_to_context(document.get("context", {})),
        extra_sections=extra_sections,
    )


def write_config(path: Path, config: ProjectConfig) -> None:
    """Every section this module does not interpret is written back unchanged."""
    document: dict[str, Any] = {"config_version": config.config_version, **config.extra_sections}
    context_table = _context_to_toml(config.context)
    if context_table:
        document["context"] = context_table
    path.write_text(tomli_w.dumps(document), encoding="utf-8")
