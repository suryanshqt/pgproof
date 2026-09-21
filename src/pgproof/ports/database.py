"""The disposable-PostgreSQL lifecycle and catalog ports. `docs/ARCHITECTURE.md:139`.

Two concerns, two Protocols: `DatabaseLifecycle` starts and stops a server
(long-running, not a `Runner.run()`-shaped "execute to completion" command);
`CatalogReader` queries an already-running one. One adapter implements each
today (`pgproof.adapters.postgres.lifecycle.DockerPostgresLifecycle`,
`pgproof.adapters.postgres.catalog.PsycopgCatalogReader`), matching
`ports/runner.py`'s own precedent of a Protocol per port even with a single
concrete implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pgproof.domain.ir.schema import SchemaIR


@dataclass(frozen=True)
class GeneratedCredentials:
    """Never a user-supplied or production credential. `docs/ARCHITECTURE.md:74`."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@dataclass(frozen=True)
class DisposableDatabase:
    credentials: GeneratedCredentials
    container_id: str
    # Set only when `start(network=...)` joined a shared Docker network: the
    # same database, reachable by container name from another container on
    # that network, rather than by the host-facing `credentials` above.
    internal_credentials: GeneratedCredentials | None = None


class DatabaseUnavailableError(RuntimeError):
    """The database never became ready within its startup budget."""


class DatabaseLifecycle(Protocol):
    def start(
        self, *, image: str, timeout_seconds: float, network: str | None = None
    ) -> DisposableDatabase: ...
    def stop(self, database: DisposableDatabase) -> None: ...


class CatalogReader(Protocol):
    def introspect(self, credentials: GeneratedCredentials) -> SchemaIR: ...
