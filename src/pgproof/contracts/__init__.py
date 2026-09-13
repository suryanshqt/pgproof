"""Access to the generated JSON Schemas that ship with the package.

The canonical generated location is `contracts/schemas/` at the repository root,
per `docs/ARCHITECTURE.md` section 5. The wheel force-includes that directory at
`pgproof/contracts/schemas`, so an installed pgproof resolves its own schemas
through package resources without needing the source tree.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from pgproof.domain.envelope import ArtifactType
from pgproof.domain.registry import ARTIFACT_FILENAMES


def schemas_root() -> Path:
    """Directory holding the generated schemas, installed or in a source checkout."""
    packaged = Path(str(resources.files("pgproof.contracts"))) / "schemas"
    if packaged.is_dir():
        return packaged
    # Source checkout: schemas are generated to the repository root and only
    # copied into the package at build time.
    return Path(__file__).resolve().parents[3] / "contracts" / "schemas"


def schema_path(artifact_type: ArtifactType) -> Path:
    return schemas_root() / ARTIFACT_FILENAMES[artifact_type]


def load_schema(artifact_type: ArtifactType) -> dict[str, Any]:
    """Read one generated schema. Raises FileNotFoundError if it was not generated."""
    document: dict[str, Any] = json.loads(schema_path(artifact_type).read_text(encoding="utf-8"))
    return document


def available_schemas() -> tuple[ArtifactType, ...]:
    root = schemas_root()
    return tuple(
        artifact_type
        for artifact_type, name in sorted(ARTIFACT_FILENAMES.items())
        if (root / name).is_file()
    )
