"""The disposable-PostgreSQL container lifecycle. `docs/ARCHITECTURE.md:76-78`.

A Postgres container is a long-running server, not a command run to
completion, so this does not go through `adapters.runner.docker.DockerRunner`
(`Runner.run()` blocks until the container exits). It reuses that module's
container-ownership label (`LABEL_OWNER`/`OWNER_VALUE`) so `pgproof doctor`'s
and `pgproof clean --containers`' orphan detection already covers a crashed
disposable-Postgres container without any changes there.

Bound to `127.0.0.1` only and never given production credentials or data,
per `docs/PRODUCT_SPEC.md:268` ("no production connection in v1").
"""

from __future__ import annotations

import secrets
import subprocess
import time
import uuid
from collections.abc import Sequence

from pgproof.adapters.runner.docker import LABEL_OWNER, OWNER_VALUE, probe_docker
from pgproof.ports.database import (
    DatabaseUnavailableError,
    DisposableDatabase,
    GeneratedCredentials,
)

_HOST = "127.0.0.1"
_USER = "pgproof"
_DATABASE = "pgproof"
_PASSWORD_BYTES = 18
_POLL_INTERVAL_SECONDS = 0.5


def _docker(
    args: Sequence[str], *, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def generate_password() -> str:
    return secrets.token_urlsafe(_PASSWORD_BYTES)


def _parse_published_port(port_output: str) -> int:
    # `docker port <id> 5432/tcp` prints e.g. "127.0.0.1:54321"; a container
    # can publish more than one address, so use the first line.
    first_line = port_output.strip().splitlines()[0]
    return int(first_line.rsplit(":", 1)[-1])


class DockerPostgresLifecycle:
    def start(self, *, image: str, timeout_seconds: float) -> DisposableDatabase:
        if not probe_docker().daemon_reachable:
            raise DatabaseUnavailableError("Docker daemon is not reachable")

        password = generate_password()
        run_id = uuid.uuid4().hex[:12]
        created = _docker(
            [
                "run",
                "-d",
                "--name",
                f"pgproof-postgres-{run_id}",
                "--label",
                f"{LABEL_OWNER}={OWNER_VALUE}",
                "-e",
                f"POSTGRES_USER={_USER}",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                f"POSTGRES_DB={_DATABASE}",
                "-p",
                f"{_HOST}::5432",
                image,
            ]
        )
        if created.returncode != 0:
            raise DatabaseUnavailableError(f"could not start PostgreSQL: {created.stderr}")
        container_id = created.stdout.strip()

        port_result = _docker(["port", container_id, "5432/tcp"])
        if port_result.returncode != 0 or not port_result.stdout.strip():
            _docker(["rm", "-f", container_id])
            raise DatabaseUnavailableError(
                f"could not determine the published port: {port_result.stderr}"
            )
        port = _parse_published_port(port_result.stdout)

        credentials = GeneratedCredentials(
            host=_HOST, port=port, user=_USER, password=password, database=_DATABASE
        )
        if not self._wait_until_ready(container_id, timeout_seconds=timeout_seconds):
            _docker(["rm", "-f", container_id])
            raise DatabaseUnavailableError(
                f"PostgreSQL did not become ready within {timeout_seconds}s"
            )
        return DisposableDatabase(credentials=credentials, container_id=container_id)

    def stop(self, database: DisposableDatabase) -> None:
        _docker(["rm", "-f", database.container_id])

    def _wait_until_ready(self, container_id: str, *, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            probe = _docker(["exec", container_id, "pg_isready", "-U", _USER, "-d", _DATABASE])
            if probe.returncode == 0:
                return True
            time.sleep(_POLL_INTERVAL_SECONDS)
        return False
