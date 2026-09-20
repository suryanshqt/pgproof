"""Atomic read/write for one top-level artifact document.

Version and payload validation is `pgproof.domain.registry`; this module owns
only the bytes at rest and the content hash recorded in the run manifest.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.registry import parse_artifact
from pgproof.store.atomic import write_bytes_atomic


def content_hash(canonical_json: str) -> str:
    digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def write_artifact(path: Path, envelope: Envelope[Any]) -> str:
    """Write one envelope atomically. Returns the content hash of the bytes written."""
    canonical = envelope.canonical_json()
    write_bytes_atomic(path, canonical.encode("utf-8"))
    return content_hash(canonical)


def read_artifact(path: Path, expected_type: ArtifactType) -> Envelope[Any]:
    """Read and validate one envelope.

    Raises if its `artifact_type` disagrees with `expected_type`.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    envelope = parse_artifact(document)
    if envelope.artifact_type is not expected_type:
        raise ValueError(
            f"{path}: expected artifact_type {expected_type.value!r}, "
            f"got {envelope.artifact_type.value!r}"
        )
    return envelope
