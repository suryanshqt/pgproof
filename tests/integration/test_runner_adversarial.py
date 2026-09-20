"""BE-16 accept criteria: adversarial tests against a real Docker daemon.

`docs/PR_ROADMAP.md` BE-16: "Accept with adversarial tests for network, host
mutation, environment leakage, timeout, SIGINT, and orphan cleanup." These
tests prove the guarantee against real container behaviour, not a mock;
`tests/unit/test_adapters_runner_docker.py` covers command construction and
control flow without a daemon. Self-skips wherever Docker is unreachable,
following the `requires_git`/`npm_required` precedent in this suite
(`tests/unit/test_repository_inventory.py`, `tests/unit/test_contract_generation.py`) —
in CI this means the `macos-15` legs of the `quality` matrix skip and the
dedicated `runner-integration` job (`ubuntu-latest`) runs them for real.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from threading import Event, Timer

import pytest

from pgproof.adapters.runner.docker import (
    DockerRunner,
    find_orphaned_containers,
    probe_docker,
    remove_containers,
)
from pgproof.domain.execution import RunnerConfig
from pgproof.ports.runner import RunSpec

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)

_IMAGE = "alpine:3.19"

pytestmark = requires_docker


def _spec(
    source: Path,
    command: list[str],
    *,
    config: RunnerConfig | None = None,
    environment: Mapping[str, str] | None = None,
    cancel_event: Event | None = None,
) -> RunSpec:
    return RunSpec(
        source=source,
        config=config or RunnerConfig(image=_IMAGE, timeout_seconds=30),
        command=command,
        environment=environment or {},
        cancel_event=cancel_event,
    )


def test_network_is_disabled_by_default(tmp_path: Path) -> None:
    outcome = DockerRunner().run(
        _spec(
            tmp_path,
            ["sh", "-c", "wget -T 2 -O /dev/null http://1.1.1.1 2>&1 || echo NETWORK_BLOCKED"],
        )
    )
    assert "NETWORK_BLOCKED" in outcome.stdout


def test_the_container_cannot_mutate_the_host_source(tmp_path: Path) -> None:
    """Writes land on the disposable staged copy; the real source is never mounted."""
    (tmp_path / "existing.txt").write_text("original", encoding="utf-8")
    outcome = DockerRunner().run(_spec(tmp_path, ["sh", "-c", "echo pwned > pwned.txt"]))
    assert outcome.exit_code == 0
    assert not (tmp_path / "pwned.txt").exists()
    assert (tmp_path / "existing.txt").read_text(encoding="utf-8") == "original"


def test_only_the_explicit_environment_reaches_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOST_SECRET", "should-never-leak")
    outcome = DockerRunner().run(_spec(tmp_path, ["env"], environment={"APP_ENV": "test"}))
    assert "HOST_SECRET" not in outcome.stdout
    assert "APP_ENV=test" in outcome.stdout


def test_the_container_runs_as_a_fixed_non_root_user(tmp_path: Path) -> None:
    outcome = DockerRunner().run(_spec(tmp_path, ["id", "-u"]))
    assert outcome.stdout.strip() == "1000"


def test_a_command_past_its_timeout_is_stopped(tmp_path: Path) -> None:
    config = RunnerConfig(image=_IMAGE, timeout_seconds=2)
    started = time.monotonic()
    outcome = DockerRunner().run(_spec(tmp_path, ["sleep", "30"], config=config))
    elapsed = time.monotonic() - started
    assert outcome.timed_out is True
    assert elapsed < 15


def test_cancelling_mid_run_stops_the_container(tmp_path: Path) -> None:
    config = RunnerConfig(image=_IMAGE, timeout_seconds=30)
    cancel_event = Event()
    Timer(0.5, cancel_event.set).start()
    started = time.monotonic()
    outcome = DockerRunner().run(
        _spec(tmp_path, ["sleep", "20"], config=config, cancel_event=cancel_event)
    )
    elapsed = time.monotonic() - started
    assert outcome.cancelled is True
    assert elapsed < 15


def test_a_finished_run_leaves_no_container_behind(tmp_path: Path) -> None:
    before = {orphan.id for orphan in find_orphaned_containers()}
    DockerRunner().run(_spec(tmp_path, ["echo", "hi"]))
    after = {orphan.id for orphan in find_orphaned_containers()}
    assert after == before


def test_orphan_cleanup_finds_and_removes_a_container_pgproof_did_not_clean_up() -> None:
    created = subprocess.run(
        [
            "docker",
            "create",
            "--label",
            "pgproof.owner=pgproof",
            _IMAGE,
            "sleep",
            "60",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    container_id = created.stdout.strip()
    try:
        orphans = {orphan.id for orphan in find_orphaned_containers()}
        assert any(container_id.startswith(orphan_id) for orphan_id in orphans)
        remove_containers([container_id])
        orphans_after = {orphan.id for orphan in find_orphaned_containers()}
        assert not any(container_id.startswith(orphan_id) for orphan_id in orphans_after)
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], capture_output=True, check=False)
