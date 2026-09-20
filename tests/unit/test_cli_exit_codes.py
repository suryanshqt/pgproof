"""The exit-code contract, `docs/TECHNICAL_DESIGN.md` section 2."""

import click
import pytest
from click.testing import CliRunner

from pgproof.cli.exit_codes import CliError, ExitCode


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ExitCode.OK, 0),
        (ExitCode.INVALID_ARGUMENTS, 2),
        (ExitCode.ENVIRONMENT_CAPABILITY_UNAVAILABLE, 3),
        (ExitCode.EXECUTION_FAILED, 4),
        (ExitCode.ARTIFACT_INCOMPATIBLE, 5),
        (ExitCode.CANCELLED, 6),
        (ExitCode.INTERNAL_ERROR, 7),
    ],
)
def test_exit_codes_match_the_documented_table(code: ExitCode, expected: int) -> None:
    assert code == expected


def test_cli_error_exits_with_its_declared_code() -> None:
    @click.command()
    def boom() -> None:
        raise CliError(
            "no runner image configured",
            exit_code=ExitCode.ENVIRONMENT_CAPABILITY_UNAVAILABLE,
        )

    result = CliRunner().invoke(boom, [])
    assert result.exit_code == 3
    assert "no runner image configured" in result.output
