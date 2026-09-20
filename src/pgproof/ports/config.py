"""The `pgproof.toml` read/write port.

One filesystem-based adapter exists (`pgproof.adapters.repository.config_toml`).
`docs/ARCHITECTURE.md` section 12 draws this the same way as repository
inventory: a narrow Protocol decouples `application`/`cli` from the concrete
TOML library so it can be substituted without changing either caller.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pgproof.domain.config import ProjectConfig


class ConfigReaderPort(Protocol):
    def __call__(self, path: Path) -> ProjectConfig: ...


class ConfigWriterPort(Protocol):
    def __call__(self, path: Path, config: ProjectConfig) -> None: ...
