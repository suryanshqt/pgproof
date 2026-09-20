"""The exit-code contract, `docs/TECHNICAL_DESIGN.md` section 2.

Findings do not change the process exit code in v1; command execution status
does. Click's own `UsageError` already exits 2, which is why "invalid
arguments" needs no code here: `click.Path(exists=True, ...)` on an argument
raises it for free.
"""

from __future__ import annotations

from enum import IntEnum

import click


class ExitCode(IntEnum):
    OK = 0
    INVALID_ARGUMENTS = 2
    ENVIRONMENT_CAPABILITY_UNAVAILABLE = 3
    EXECUTION_FAILED = 4
    ARTIFACT_INCOMPATIBLE = 5
    CANCELLED = 6
    INTERNAL_ERROR = 7


class CliError(click.ClickException):
    """Raise to fail a command with one of the documented non-zero exit codes."""

    def __init__(self, message: str, *, exit_code: ExitCode) -> None:
        super().__init__(message)
        # click.ClickException.exit_code is a ClassVar; this type narrows it per
        # raised instance, which mypy cannot express any other way.
        self.exit_code = int(exit_code)  # type: ignore[misc]
