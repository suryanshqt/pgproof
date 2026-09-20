"""Contract for the installed `pgproof` entry point."""

from click.testing import CliRunner

import pgproof
from pgproof.cli.app import main


def _normalised(output: str) -> str:
    return " ".join(output.split())


def test_version_prints_one_restrained_line() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.output == f"pgproof {pgproof.__version__}\n"


def test_help_states_the_local_first_contract() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    text = _normalised(result.output)
    assert "sends no telemetry" in text
    assert "never connects to a production database" in text
    assert "makes no outbound network request" in text


def test_help_reports_that_not_every_command_exists_yet() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert "Not every command is implemented yet." in _normalised(result.output)


def test_bare_invocation_shows_usage_and_exits_two() -> None:
    result = CliRunner().invoke(main, [])
    assert result.exit_code == 2  # TECHNICAL_DESIGN.md section 2: invalid arguments
    assert "Usage: pgproof" in result.output


def test_unknown_command_is_rejected() -> None:
    result = CliRunner().invoke(main, ["review"])
    assert result.exit_code != 0


def test_the_registered_product_commands_appear_in_help() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert "doctor" in result.output
    assert "inspect" in result.output
    assert "ui" in result.output


def test_ascii_is_a_global_option() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert "--ascii" in result.output


def test_verbose_is_a_global_option() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert "--verbose" in result.output
