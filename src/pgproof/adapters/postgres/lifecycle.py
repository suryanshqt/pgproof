"""The disposable-PostgreSQL container lifecycle. `docs/ARCHITECTURE.md:76-78`.

A Postgres container is a long-running server, not a command run to
completion, so this does not go through `adapters.runner.docker.DockerRunner`
(`Runner.run()` blocks until the container exits). It reuses that module's
container-ownership label (`LABEL_OWNER`/`OWNER_VALUE`) so `pgproof doctor`'s
and `pgproof clean --containers`' orphan detection already covers a crashed
disposable-Postgres container without any changes there.

Bound to `127.0.0.1` only and never given production credentials or data,
per `docs/PRODUCT_SPEC.md:268` ("no production connection in v1"). The host
publish (127.0.0.1) stays in place even when `start(network=...)` also joins
a shared, `--internal` Docker network (BE-18): the host-facing `credentials`
keep serving `PsycopgCatalogReader` from the host process, while the
returned `internal_credentials` (container-name-addressed) is what a runner
container on that same network uses — two routes to the one database.

Readiness is a real TCP `psycopg.connect()` attempt against the published
port, not `docker exec ... pg_isready`. The official Postgres image runs a
*temporary* Unix-socket-only server during `initdb`/init-script execution,
stops it, then starts the real TCP server; `pg_isready` run inside the
container can observe the temporary instance as "accepting connections" and
report ready well before the real server is listening, which surfaced as a
real, intermittent "server closed the connection unexpectedly" failure on a
slower CI runner. Probing the exact host:port:credentials path the caller
will actually use removes the ambiguity about which server instance answered.
"""

from __future__ import annotations

import secrets
import subprocess
import time
import uuid
from collections.abc import Sequence

import psycopg

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
    def start(
        self, *, image: str, timeout_seconds: float, network: str | None = None
    ) -> DisposableDatabase:
        if not probe_docker().daemon_reachable:
            raise DatabaseUnavailableError("Docker daemon is not reachable")

        password = generate_password()
        run_id = uuid.uuid4().hex[:12]
        container_name = f"pgproof-postgres-{run_id}"
        run_args = [
            "run",
            "-d",
            "--name",
            container_name,
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
        created = _docker(run_args)
        if created.returncode != 0:
            raise DatabaseUnavailableError(f"could not start PostgreSQL: {created.stderr}")
        container_id = created.stdout.strip()

        if network is not None:
            # Joined *after* creation, not via `--network` at `docker run`:
            # Docker does not publish ports at all for a container created
            # directly on an `--internal` network, only for one connected to
            # it afterward — verified directly, not assumed.
            connected = _docker(["network", "connect", network, container_id])
            if connected.returncode != 0:
                _docker(["rm", "-f", container_id])
                raise DatabaseUnavailableError(
                    f"could not join network {network!r}: {connected.stderr}"
                )

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
        if not self._wait_until_ready(credentials, timeout_seconds=timeout_seconds):
            _docker(["rm", "-f", container_id])
            raise DatabaseUnavailableError(
                f"PostgreSQL did not become ready within {timeout_seconds}s"
            )
        internal_credentials = (
            GeneratedCredentials(
                host=container_name, port=5432, user=_USER, password=password, database=_DATABASE
            )
            if network is not None
            else None
        )
        return DisposableDatabase(
            credentials=credentials,
            container_id=container_id,
            internal_credentials=internal_credentials,
        )

    def stop(self, database: DisposableDatabase) -> None:
        _docker(["rm", "-f", database.container_id])

    def _wait_until_ready(
        self, credentials: GeneratedCredentials, *, timeout_seconds: float
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(credentials.dsn, connect_timeout=2):
                    return True
            except psycopg.OperationalError:
                time.sleep(_POLL_INTERVAL_SECONDS)
        return False
