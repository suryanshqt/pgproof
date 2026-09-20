"""The runner's configuration and the pre-execution approval contract.

`docs/ARCHITECTURE.md:72-74` ("Project runner"): the runner "receives a
repository copy, generated database credentials, allowlisted environment, no
host write mount, no external network, and explicit resource/time limits."
`ExecutionContract` is the pure value shown for the "execution and isolation
contract" approval step, `docs/ARCHITECTURE.md:317-318`. It is distinct from
`pgproof.domain.manifest.RunManifest` (the artifact-integrity record a
finished run writes): this is a pre-execution approval value, never persisted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# `docs/TECHNICAL_DESIGN.md:130` requires "safe minimums/maximums" without
# naming numbers; four hours is pgproof's own chosen ceiling.
_MAX_TIMEOUT_SECONDS = 14_400


@dataclass(frozen=True)
class RunnerConfig:
    """The `[runner]` table, `docs/TECHNICAL_DESIGN.md:82-91`."""

    image: str | None = None
    build: str | None = None
    database_url_env: str = "DATABASE_URL"
    environment_allowlist: tuple[str, ...] = ()
    network: bool = False
    cpu: float = 1.0
    memory: str = "512m"
    pids: int = 128
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.image and not self.build:
            raise ValueError("runner config requires an image or a build (Dockerfile) path")
        if self.cpu <= 0:
            raise ValueError("runner cpu limit must be positive")
        if self.pids < 1:
            raise ValueError("runner pids limit must be at least 1")
        if not 1 <= self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ValueError(f"runner timeout_seconds must be between 1 and {_MAX_TIMEOUT_SECONDS}")


@dataclass(frozen=True)
class ExecutionContract:
    """The factual execution contract, `docs/INTERFACE_DESIGN.md:147-163`."""

    command: tuple[str, ...]
    image: str
    network_enabled: bool
    cpu: float
    memory: str
    pids: int
    timeout_seconds: int
    environment_allowlist: tuple[str, ...]
    database_url_env: str


def build_execution_contract(
    config: RunnerConfig, command: Sequence[str], *, resolved_image: str
) -> ExecutionContract:
    return ExecutionContract(
        command=tuple(command),
        image=resolved_image,
        network_enabled=config.network,
        cpu=config.cpu,
        memory=config.memory,
        pids=config.pids,
        timeout_seconds=config.timeout_seconds,
        environment_allowlist=config.environment_allowlist,
        database_url_env=config.database_url_env,
    )


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled
