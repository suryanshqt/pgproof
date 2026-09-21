"""`DockerPostgresLifecycle` with `docker` replaced by a scripted fake.

Real-container behaviour is exercised against an actual Docker daemon in
`tests/integration/test_postgres_catalog.py`, mirroring
`test_adapters_runner_docker.py`'s own split between mocked control-flow
tests and a real-daemon adversarial/round-trip suite.
"""

from __future__ import annotations

import subprocess

import pytest

from pgproof.adapters.postgres import lifecycle as lifecycle_module
from pgproof.adapters.postgres.lifecycle import (
    DockerPostgresLifecycle,
    _parse_published_port,
    generate_password,
)
from pgproof.adapters.runner.docker import DockerCapability
from pgproof.ports.database import DatabaseUnavailableError, DisposableDatabase


def _cp(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeDocker:
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
        lifecycle_module,
        "probe_docker",
        lambda: DockerCapability(cli_found=True, daemon_reachable=True),
    )


def test_generate_password_is_reasonably_long_and_varies() -> None:
    first, second = generate_password(), generate_password()
    assert first != second
    assert len(first) >= 20


@pytest.mark.parametrize(
    ("output", "port"),
    [("127.0.0.1:54321\n", 54321), ("0.0.0.0:5432\n127.0.0.1:5432\n", 5432)],
)
def test_parse_published_port(output: str, port: int) -> None:
    assert _parse_published_port(output) == port


def test_start_raises_when_the_daemon_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lifecycle_module,
        "probe_docker",
        lambda: DockerCapability(cli_found=True, daemon_reachable=False),
    )
    with pytest.raises(DatabaseUnavailableError):
        DockerPostgresLifecycle().start(image="postgres:17", timeout_seconds=5)


def test_start_returns_a_disposable_database_once_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker(
        {
            "run": [_cp(stdout="container123\n")],
            "port": [_cp(stdout="127.0.0.1:54321\n")],
            "exec": [_cp()],  # pg_isready succeeds first try
        }
    )
    monkeypatch.setattr(lifecycle_module, "_docker", fake)
    database = DockerPostgresLifecycle().start(image="postgres:17", timeout_seconds=5)
    assert database.container_id == "container123"
    assert database.credentials.host == "127.0.0.1"
    assert database.credentials.port == 54321
    assert database.credentials.user == "pgproof"
    assert database.credentials.database == "pgproof"
    assert fake.calls[0][0] == "run"


def test_start_raises_when_the_run_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker({"run": [_cp(returncode=1, stderr="no such image")]})
    monkeypatch.setattr(lifecycle_module, "_docker", fake)
    with pytest.raises(DatabaseUnavailableError, match="no such image"):
        DockerPostgresLifecycle().start(image="postgres:17", timeout_seconds=5)


def test_start_cleans_up_and_raises_when_the_port_cannot_be_determined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDocker(
        {
            "run": [_cp(stdout="container123\n")],
            "port": [_cp(returncode=1, stderr="no port bound")],
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(lifecycle_module, "_docker", fake)
    with pytest.raises(DatabaseUnavailableError, match="published port"):
        DockerPostgresLifecycle().start(image="postgres:17", timeout_seconds=5)
    assert fake.calls[-1] == ["rm", "-f", "container123"]


def test_start_cleans_up_and_raises_when_readiness_never_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeDocker(
        {
            "run": [_cp(stdout="container123\n")],
            "port": [_cp(stdout="127.0.0.1:54321\n")],
            "exec": [_cp(returncode=1)] * 5,
            "rm": [_cp()],
        }
    )
    monkeypatch.setattr(lifecycle_module, "_docker", fake)
    monkeypatch.setattr("pgproof.adapters.postgres.lifecycle.time.sleep", lambda _s: None)
    clock = iter([0.0, 0.1, 0.2, 0.3, 5.0])
    monkeypatch.setattr(
        "pgproof.adapters.postgres.lifecycle.time.monotonic", lambda: next(clock, 5.0)
    )
    with pytest.raises(DatabaseUnavailableError, match="did not become ready"):
        DockerPostgresLifecycle().start(image="postgres:17", timeout_seconds=1)
    assert fake.calls[-1] == ["rm", "-f", "container123"]


def test_stop_removes_the_container(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeDocker({"rm": [_cp()]})
    monkeypatch.setattr(lifecycle_module, "_docker", fake)
    from pgproof.ports.database import GeneratedCredentials

    database = DisposableDatabase(
        credentials=GeneratedCredentials(
            host="127.0.0.1", port=1, user="pgproof", password="x", database="pgproof"
        ),
        container_id="container123",
    )
    DockerPostgresLifecycle().stop(database)
    assert fake.calls == [["rm", "-f", "container123"]]
