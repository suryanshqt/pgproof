"""The isolated runner port. `docs/ARCHITECTURE.md:140`.

One adapter exists (`pgproof.adapters.runner.docker.DockerRunner`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Protocol

from pgproof.domain.execution import RunnerConfig, RunOutcome


@dataclass(frozen=True)
class RunSpec:
    """One execution request. `environment` is the fully-resolved mapping the
    runner passes through verbatim; the port never reads the host's own
    environment, so leakage is impossible by construction, not by filtering.
    """

    source: Path
    config: RunnerConfig
    command: Sequence[str]
    environment: Mapping[str, str] = field(default_factory=dict)
    cancel_event: Event | None = None


class Runner(Protocol):
    def run(self, spec: RunSpec) -> RunOutcome: ...
