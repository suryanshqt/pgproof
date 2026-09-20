"""Writing, reading, and verifying a run manifest.

Verification is the "hash manifest and compatibility validation" roadmap item:
given a manifest, confirm every entry's schema major is still supported and its
recorded bytes still match what is on disk, independent of re-running analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

from pgproof.domain.manifest import RunManifest
from pgproof.domain.versioning import IncompatibleSchemaVersionError, require_supported
from pgproof.store.artifacts import content_hash
from pgproof.store.atomic import write_bytes_atomic


def write_run_manifest(path: Path, manifest: RunManifest) -> None:
    write_bytes_atomic(path, manifest.canonical_json().encode("utf-8"))


def read_run_manifest(path: Path) -> RunManifest:
    document = json.loads(path.read_text(encoding="utf-8"))
    return RunManifest.model_validate(document)


def verify_manifest(manifest_dir: Path, manifest: RunManifest) -> tuple[str, ...]:
    """Return one problem string per entry that fails compatibility or hash verification.

    An empty result means every entry's schema major is supported by this reader
    and its file's bytes still hash to what the manifest recorded.
    """
    problems: list[str] = []
    for entry in manifest.entries:
        try:
            require_supported(entry.schema_version)
        except IncompatibleSchemaVersionError as error:
            problems.append(f"{entry.path}: {error}")
            continue
        artifact_path = manifest_dir / entry.path
        if not artifact_path.is_file():
            problems.append(f"{entry.path}: recorded in manifest but missing on disk")
            continue
        actual = content_hash(artifact_path.read_text(encoding="utf-8"))
        if actual != entry.content_hash:
            problems.append(
                f"{entry.path}: content hash mismatch; manifest says {entry.content_hash}, "
                f"file is {actual}"
            )
    return tuple(problems)
