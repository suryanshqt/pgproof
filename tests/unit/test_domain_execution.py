"""`RunnerConfig` validation and the execution-contract builder."""

import pytest

from pgproof.domain.execution import RunnerConfig, RunOutcome, build_execution_contract


def test_a_config_needs_an_image_or_a_build_path() -> None:
    with pytest.raises(ValueError, match="image or a build"):
        RunnerConfig()


def test_an_image_alone_is_sufficient() -> None:
    assert RunnerConfig(image="alpine:3.19").image == "alpine:3.19"


def test_a_build_path_alone_is_sufficient() -> None:
    assert RunnerConfig(build="Dockerfile").build == "Dockerfile"


def test_cpu_must_be_positive() -> None:
    with pytest.raises(ValueError, match="cpu"):
        RunnerConfig(image="alpine:3.19", cpu=0)


def test_pids_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="pids"):
        RunnerConfig(image="alpine:3.19", pids=0)


def test_timeout_seconds_has_a_ceiling() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        RunnerConfig(image="alpine:3.19", timeout_seconds=999_999)


def test_timeout_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        RunnerConfig(image="alpine:3.19", timeout_seconds=0)


def test_build_execution_contract_carries_the_resolved_image_and_command() -> None:
    config = RunnerConfig(
        build="Dockerfile", network=True, environment_allowlist=("APP_ENV",), cpu=2, pids=64
    )
    contract = build_execution_contract(
        config, ["pytest", "-x"], resolved_image="pgproof-runner:abc"
    )
    assert contract.command == ("pytest", "-x")
    assert contract.image == "pgproof-runner:abc"
    assert contract.network_enabled is True
    assert contract.cpu == 2
    assert contract.pids == 64
    assert contract.environment_allowlist == ("APP_ENV",)
    assert contract.database_url_env == "DATABASE_URL"


def test_run_outcome_succeeded_requires_a_clean_zero_exit() -> None:
    clean = RunOutcome(
        exit_code=0, timed_out=False, cancelled=False, stdout="", stderr="", duration_seconds=1.0
    )
    assert clean.succeeded is True

    failed = RunOutcome(
        exit_code=1, timed_out=False, cancelled=False, stdout="", stderr="", duration_seconds=1.0
    )
    assert failed.succeeded is False

    timed_out = RunOutcome(
        exit_code=0, timed_out=True, cancelled=False, stdout="", stderr="", duration_seconds=1.0
    )
    assert timed_out.succeeded is False

    cancelled = RunOutcome(
        exit_code=0, timed_out=False, cancelled=True, stdout="", stderr="", duration_seconds=1.0
    )
    assert cancelled.succeeded is False
