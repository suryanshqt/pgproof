"""The portable proof bundle directory. `docs/TECHNICAL_DESIGN.md` section 26:

```text
proofs/<id>/
  proof.yaml
  schema.sql
  query.sql
  parameters.json
  dataset.yaml
  config.yaml
  evidence/
    control-a1.json
    treatment-b.json
    control-a2.json
    plans/
  README.md
```

`proof.yaml` is the manifest: tool/generator/schema version, and a SHA-256 of
every other file in the bundle. Reading back re-hashes each file and compares
against those declared hashes — the one way a bundle detects it was edited
after being written, matching section 26's "reproduction verifies... artifact
hashes." A mismatch is reported, never raised: a tampered bundle is real,
observable input, not an exceptional program state.

Writing a bundle performs no database I/O and no subprocess call: `schema_sql`
and every evidence document are given by the caller (`adapters.proof.reproduce`
and, eventually, a `pgproof verify` command), not derived here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pgproof.domain.versioning import CONTRACT_SCHEMA_VERSION

_MANIFEST_NAME = "proof.yaml"


@dataclass(frozen=True)
class BundleManifest:
    proof_id: str
    tool_version: str
    schema_version: str
    generator_version: int
    file_hashes: dict[str, str]


@dataclass(frozen=True)
class BundleContents:
    manifest: BundleManifest
    schema_sql: str
    query_sql: str
    parameters: object
    dataset: object
    config: object
    evidence: dict[str, object]
    plans: dict[str, object]


def _hash_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def write_proof_bundle(
    directory: Path,
    *,
    proof_id: str,
    tool_version: str,
    generator_version: int,
    schema_sql: str,
    query_sql: str,
    parameters: object,
    dataset: object,
    config: object,
    evidence: Mapping[str, object],
    plans: Mapping[str, object],
    readme: str,
) -> None:
    """Writes every file in the bundle, then `proof.yaml` last — a reader can
    treat the manifest's presence as "the write finished", since every hash it
    declares must already exist on disk by the time it is written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    evidence_dir = directory / "evidence"
    plans_dir = evidence_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    parameters_json = json.dumps(parameters, sort_keys=True, indent=2) + "\n"
    dataset_yaml = yaml.safe_dump(dataset, sort_keys=True)
    config_yaml = yaml.safe_dump(config, sort_keys=True)

    text_contents = {
        "schema.sql": schema_sql,
        "query.sql": query_sql,
        "parameters.json": parameters_json,
        "dataset.yaml": dataset_yaml,
        "config.yaml": config_yaml,
    }
    for name, content in text_contents.items():
        (directory / name).write_text(content, encoding="utf-8")

    file_hashes = {name: _hash_text(content) for name, content in text_contents.items()}

    for name, document in evidence.items():
        content = json.dumps(document, sort_keys=True, indent=2) + "\n"
        (evidence_dir / f"{name}.json").write_text(content, encoding="utf-8")
        file_hashes[f"evidence/{name}.json"] = _hash_text(content)

    for name, document in plans.items():
        content = json.dumps(document, sort_keys=True, indent=2) + "\n"
        (plans_dir / f"{name}.json").write_text(content, encoding="utf-8")
        file_hashes[f"evidence/plans/{name}.json"] = _hash_text(content)

    (directory / "README.md").write_text(readme, encoding="utf-8")
    file_hashes["README.md"] = _hash_text(readme)

    manifest = {
        "proof_id": proof_id,
        "tool_version": tool_version,
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "generator_version": generator_version,
        "file_hashes": file_hashes,
    }
    (directory / _MANIFEST_NAME).write_text(
        yaml.safe_dump(manifest, sort_keys=True), encoding="utf-8"
    )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def read_proof_bundle(directory: Path) -> tuple[BundleContents | None, tuple[str, ...]]:
    """`None` plus every problem found when the bundle cannot be trusted at
    all (missing manifest, missing file, or a hash mismatch) — never a
    partially-trusted result a caller might read fields off of by accident.
    """
    manifest_path = directory / _MANIFEST_NAME
    raw_manifest = _read_text(manifest_path)
    if raw_manifest is None:
        return None, (f"{_MANIFEST_NAME} is missing",)
    try:
        parsed: dict[str, Any] = yaml.safe_load(raw_manifest)
    except yaml.YAMLError as error:
        return None, (f"{_MANIFEST_NAME} is not valid YAML: {error}",)

    required_manifest_fields = (
        "proof_id",
        "tool_version",
        "schema_version",
        "generator_version",
        "file_hashes",
    )
    missing_fields = [field for field in required_manifest_fields if field not in parsed]
    if missing_fields:
        return None, tuple(
            f"{_MANIFEST_NAME} is missing field {field!r}" for field in missing_fields
        )

    file_hashes: dict[str, str] = parsed["file_hashes"]
    problems: list[str] = []
    for relative_path, declared_hash in file_hashes.items():
        content = _read_text(directory / relative_path)
        if content is None:
            problems.append(f"{relative_path} is missing")
            continue
        if _hash_text(content) != declared_hash:
            problems.append(f"{relative_path} does not match its declared hash (tampered)")
    if problems:
        return None, tuple(problems)

    manifest = BundleManifest(
        proof_id=parsed["proof_id"],
        tool_version=parsed["tool_version"],
        schema_version=parsed["schema_version"],
        generator_version=parsed["generator_version"],
        file_hashes=file_hashes,
    )
    evidence: dict[str, object] = {}
    plans: dict[str, object] = {}
    for relative_path in file_hashes:
        if relative_path.startswith("evidence/plans/"):
            name = relative_path.removeprefix("evidence/plans/").removesuffix(".json")
            plans[name] = json.loads((directory / relative_path).read_text(encoding="utf-8"))
        elif relative_path.startswith("evidence/"):
            name = relative_path.removeprefix("evidence/").removesuffix(".json")
            evidence[name] = json.loads((directory / relative_path).read_text(encoding="utf-8"))

    contents = BundleContents(
        manifest=manifest,
        schema_sql=(directory / "schema.sql").read_text(encoding="utf-8"),
        query_sql=(directory / "query.sql").read_text(encoding="utf-8"),
        parameters=json.loads((directory / "parameters.json").read_text(encoding="utf-8")),
        dataset=yaml.safe_load((directory / "dataset.yaml").read_text(encoding="utf-8")),
        config=yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8")),
        evidence=evidence,
        plans=plans,
    )
    return contents, ()
