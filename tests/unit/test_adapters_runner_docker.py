"""`DockerRunner` logic with `docker` itself replaced by a scripted fake.

Real-container behaviour (network isolation, host-mutation resistance,
environment leakage, timeout, cancellation, orphan cleanup) is exercised
against an actual Docker daemon in `tests/integration/test_runner_adversarial.py`,
which self-skips where Docker is unavailable (including every macOS CI leg).
These tests instead prove the command construction and control flow are
correct, the same way `tests/unit/test_cli_doctor.py` already tests Docker
probing without a real daemon.
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Event

import pytest

from pgproof.adapters.runner import docker as docker_module
from pgproof.adapters.runner.docker import (
    DockerCapability,
    DockerRunner,
    OrphanedContainer,
    RunnerBuildError,
    RunnerUnavailableError,
    _normalize_memory,
    find_orphaned_containers,
    remove_containers,
    resolve_image,
)
from pgproof.domain.execution import RunnerConfig
from pgproof.ports.runner import RunSpec


def _cp(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeDocker:
    """Scripted `docker` CLI: each subcommand pops the next response off its queue."""

    def __init__(self, responses: dict[str, list[subprocess.CompletedProcess[str]]]) -> None:
        self.calls: list[list[str]] = []
        self._responses = {key: list(value) for key, value in responses.items()}

    def __call__(
        self,
        args: list[str],
        *,
        timeout: float | None = None,  # noqa: ARG002
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        queue = self._responses.get(args[0])
        if not queue:
            return _cp()
        return queue.pop(0)


@pytest.fixture(autouse=True)
def _reachable_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_module,
        "probe_docker",
        lambda: DockerCapability(cli_found=True, daemon_reachable=True),
    )


# --------------------------------------------------------------------------- #
# _normalize_memory
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("512m", "512m"), ("2GB", "2g"), ("256M", "256m"), ("1g", "1g"), ("1024", "1024b")],
)
def test_normalize_memory(raw: str, normalized: str) -> None:
    assert _normalize_memory(raw) == normalized


def test_normalize_memory_rejects_nonsense() -> None:
    with pytest.raises(ValueError, match="memory"):
        _normalize_memory("plenty")


# --------------------------------------------------------------------------- #
# resolve_image
# --------------------------------------------------------------------------- #
def test_resolve_image_returns_a_configured_image_without_touching_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker({})
    monkeypatch.setattr(docker_module, "_docker", fake)
    assert resolve_image(RunnerConfig(image="alpine:3.19"), tmp_path) == "alpine:3.19"
    assert fake.calls == []


def test_resolve_image_builds_from_a_dockerfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "Dockerfile").write_text("FROM alpine:3.19\n", encoding="utf-8")
    fake = _FakeDocker({"build": [_cp()]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    tag = resolve_image(RunnerConfig(build="Dockerfile"), tmp_path)
    assert tag.startswith("pgproof-runner:")
    assert fake.calls[0][0] == "build"


def test_resolve_image_raises_on_a_failed_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "Dockerfile").write_text("garbage\n", encoding="utf-8")
    fake = _FakeDocker({"build": [_cp(returncode=1, stderr="no such instruction")]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    with pytest.raises(RunnerBuildError, match="no such instruction"):
        resolve_image(RunnerConfig(build="Dockerfile"), tmp_path)


# --------------------------------------------------------------------------- #
# find_orphaned_containers / remove_containers
# --------------------------------------------------------------------------- #
def test_find_orphaned_containers_parses_tab_separated_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDocker(
        {"ps": [_cp(stdout="abc123\tpgproof-runner-abc123\ndef456\tpgproof-runner-def456\n")]}
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    orphans = find_orphaned_containers()
    assert orphans == (
        OrphanedContainer(id="abc123", name="pgproof-runner-abc123"),
        OrphanedContainer(id="def456", name="pgproof-runner-def456"),
    )


def test_find_orphaned_containers_is_empty_on_a_failed_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDocker({"ps": [_cp(returncode=1)]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    assert find_orphaned_containers() == ()


def test_find_orphaned_containers_is_empty_with_no_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker({"ps": [_cp(stdout="")]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    assert find_orphaned_containers() == ()


def test_find_orphaned_containers_skips_blank_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker({"ps": [_cp(stdout="\nabc123\tpgproof-runner-abc123\n\n")]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    assert find_orphaned_containers() == (
        OrphanedContainer(id="abc123", name="pgproof-runner-abc123"),
    )


def test_remove_containers_force_removes_every_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker({"rm": [_cp(), _cp()]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    remove_containers(["abc123", "def456"])
    assert fake.calls == [["rm", "-f", "abc123"], ["rm", "-f", "def456"]]


# --------------------------------------------------------------------------- #
# DockerRunner.run
# --------------------------------------------------------------------------- #
def _spec(
    tmp_path: Path,
    *,
    config: RunnerConfig | None = None,
    command: Sequence[str] = ("echo", "hi"),
    environment: Mapping[str, str] | None = None,
    cancel_event: Event | None = None,
) -> RunSpec:
    return RunSpec(
        source=tmp_path,
        config=config or RunnerConfig(image="alpine:3.19"),
        command=command,
        environment=environment or {},
        cancel_event=cancel_event,
    )


def test_run_stages_a_world_writable_copy_and_removes_it_afterward(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "readonly.txt").write_text("data", encoding="utf-8")
    (source / "readonly.txt").chmod(0o400)
    staged: list[Path] = []

    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="false\n"), _cp(stdout="0\n")],
            "logs": [_cp()],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    real_stage = docker_module._stage_source

    def _spy_stage(src: Path, run_id: str) -> Path:
        result = real_stage(src, run_id)
        staged.append(result)
        return result

    monkeypatch.setattr(docker_module, "_stage_source", _spy_stage)
    DockerRunner().run(_spec(source))

    assert len(staged) == 1
    assert not staged[0].exists()  # cleaned up after the run
    assert source.is_dir()  # the real source is untouched


def test_run_raises_when_the_daemon_is_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        docker_module,
        "probe_docker",
        lambda: DockerCapability(cli_found=True, daemon_reachable=False),
    )
    with pytest.raises(RunnerUnavailableError):
        DockerRunner().run(_spec(tmp_path))


def test_a_successful_run_captures_logs_and_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="false\n"), _cp(stdout="0\n")],
            "logs": [_cp(stdout="hi\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path, environment={"APP_ENV": "test"}))
    assert outcome.exit_code == 0
    assert outcome.stdout == "hi\n"
    assert outcome.timed_out is False
    assert outcome.cancelled is False
    assert outcome.succeeded is True

    create_call = fake.calls[0]
    assert create_call[0] == "create"
    assert "--network" in create_call
    assert "none" in create_call
    assert "--user" in create_call
    mount = create_call[create_call.index("-v") + 1]
    assert mount.endswith(":/workspace:rw")
    assert mount != f"{tmp_path}:/workspace:rw"  # a staged copy, never the real source
    assert "-e" in create_call
    assert "APP_ENV=test" in create_call
    assert fake.calls[-1] == ["rm", "-f", "container123"]


def test_an_unparseable_exit_code_is_reported_as_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="false\n"), _cp(stdout="<no value>\n")],
            "logs": [_cp(stdout="hi\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path))
    assert outcome.exit_code is None


def test_a_failed_exit_code_inspection_leaves_the_exit_code_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="false\n"), _cp(returncode=1)],
            "logs": [_cp(stdout="hi\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path))
    assert outcome.exit_code is None


def test_a_non_zero_exit_is_reported_without_being_treated_as_a_failure_to_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="false\n"), _cp(stdout="1\n")],
            "logs": [_cp(stdout="", stderr="boom\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path))
    assert outcome.exit_code == 1
    assert outcome.succeeded is False
    assert outcome.stderr == "boom\n"


def test_a_failed_create_short_circuits_without_starting_or_cleaning_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker({"create": [_cp(returncode=1, stderr="no such image")]})
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path))
    assert outcome.exit_code is None
    assert outcome.stderr == "no such image"
    assert [call[0] for call in fake.calls] == ["create"]


def test_a_failed_start_still_removes_the_created_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp(returncode=1, stderr="cannot start")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    outcome = DockerRunner().run(_spec(tmp_path))
    assert outcome.exit_code is None
    assert outcome.stderr == "cannot start"
    assert fake.calls[-1] == ["rm", "-f", "container123"]


def test_an_already_set_cancel_event_stops_the_container_before_inspecting_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "stop": [_cp()],
            "logs": [_cp(stdout="partial\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    cancel_event = Event()
    cancel_event.set()
    outcome = DockerRunner().run(_spec(tmp_path, cancel_event=cancel_event))
    assert outcome.cancelled is True
    assert outcome.timed_out is False
    assert outcome.exit_code is None
    assert ["stop", "-t", "5", "container123"] in fake.calls


def test_the_container_is_stopped_and_marked_timed_out_once_the_deadline_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeDocker(
        {
            "create": [_cp(stdout="container123\n")],
            "start": [_cp()],
            "inspect": [_cp(stdout="true\n")] * 5,  # never reports finished
            "stop": [_cp()],
            "logs": [_cp(stdout="still running\n")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(docker_module, "_docker", fake)
    clock = iter([0.0, 0.1, 1.5, 1.5, 1.5])
    monkeypatch.setattr("pgproof.adapters.runner.docker.time.monotonic", lambda: next(clock, 1.5))
    monkeypatch.setattr("pgproof.adapters.runner.docker.time.sleep", lambda _seconds: None)

    outcome = DockerRunner().run(
        _spec(tmp_path, config=RunnerConfig(image="alpine:3.19", timeout_seconds=1))
    )
    assert outcome.timed_out is True
    assert outcome.cancelled is False
    assert outcome.exit_code is None
    assert ["stop", "-t", "5", "container123"] in fake.calls
