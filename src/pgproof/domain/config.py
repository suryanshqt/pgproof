"""`pgproof.toml`: the project-owned, commit-safe configuration document.

`docs/TECHNICAL_DESIGN.md` section 3: "`pgproof.toml` is project-owned and safe
to commit... unsupported config major version fails." This module owns only
`config_version` and `[context]`; every other top-level table (`[project]`,
`[runner]`, `[dataset]`, `[verification]`) belongs to roadmap items that do not
exist yet, and is carried in `extra_sections` unexamined so a round trip never
loses or corrupts a section this module cannot yet interpret.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from pgproof.domain.ir.context import ContextIR
from pgproof.domain.primitives import Contract

SUPPORTED_CONFIG_VERSION = 1


class UnsupportedConfigVersionError(ValueError):
    """Raised when a config document's major version is not one this build reads."""


class ProjectConfig(Contract):
    """One `pgproof.toml` document."""

    config_version: int = SUPPORTED_CONFIG_VERSION
    context: ContextIR = ContextIR()
    extra_sections: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @staticmethod
    def require_supported(version: int) -> None:
        if version != SUPPORTED_CONFIG_VERSION:
            raise UnsupportedConfigVersionError(
                f"pgproof.toml config_version {version} is not supported; "
                f"this build reads version {SUPPORTED_CONFIG_VERSION}"
            )
