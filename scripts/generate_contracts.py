"""Generate the JSON Schema for every top-level artifact.

Output is byte-stable: sorted object keys, two-space indent, one trailing
newline, and no timestamp, path or machine identifier anywhere in the document.
That is what lets `--check` act as a drift gate in CI.

A Pydantic upgrade that changes schema output shows up here as drift, which is
intended: the generated contract is reviewed, not silently regenerated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pgproof.domain.envelope import ArtifactType  # noqa: E402
from pgproof.domain.registry import (  # noqa: E402
    ARTIFACT_FILENAMES,
    envelope_model_for,
)
from pgproof.domain.versioning import (  # noqa: E402
    CONTRACT_SCHEMA_VERSION,
    SUPPORTED_MAJOR,
)

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_BASE = "https://pgproof.dev/contracts"


def root_type_name(artifact_type: ArtifactType) -> str:
    """Stable PascalCase name shared by the JSON Schema title and the TS root type."""
    parts = artifact_type.value.split("_")
    return "".join(part.capitalize() for part in parts) + "Artifact"


def build_schema(artifact_type: ArtifactType) -> dict[str, Any]:
    model = envelope_model_for(artifact_type)
    schema: dict[str, Any] = model.model_json_schema(
        by_alias=False,
        ref_template="#/$defs/{model}",
        mode="validation",
    )
    schema["$schema"] = SCHEMA_DIALECT
    schema["$id"] = f"{ID_BASE}/{CONTRACT_SCHEMA_VERSION}/{ARTIFACT_FILENAMES[artifact_type]}"
    # The title is identifier-shaped because the TypeScript generator derives the
    # root type name from it. The human sentence lives in `description`.
    schema["title"] = root_type_name(artifact_type)
    # Express the supported major in the emitted contract so an independent
    # validator rejects a future-major document exactly as the reader does.
    schema["properties"]["schema_version"]["pattern"] = rf"^{SUPPORTED_MAJOR}\.(0|[1-9][0-9]*)$"
    schema["description"] = (
        f"Transport envelope for the pgproof {artifact_type.value} artifact, "
        f"contract schema version {CONTRACT_SCHEMA_VERSION}."
    )
    return schema


def render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generate() -> dict[str, str]:
    return {
        ARTIFACT_FILENAMES[artifact_type]: render(build_schema(artifact_type))
        for artifact_type in ArtifactType
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(REPO / "contracts" / "schemas"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true", help="write the schemas")
    group.add_argument("--check", action="store_true", help="fail on any drift")
    args = parser.parse_args(argv)

    out = Path(args.out)
    generated = generate()

    if args.write:
        out.mkdir(parents=True, exist_ok=True)
        for name in sorted({path.name for path in out.glob("*.schema.json")}):
            if name not in generated:
                (out / name).unlink()
                print(f"removed stale {name}")
        for name, text in sorted(generated.items()):
            (out / name).write_text(text, encoding="utf-8")
        print(f"wrote {len(generated)} schemas to {out}")
        return 0

    problems: list[str] = []
    existing = {path.name for path in out.glob("*.schema.json")}
    for name in sorted(existing - generated.keys()):
        problems.append(f"{name}: present on disk but no longer generated")
    for name, text in sorted(generated.items()):
        path = out / name
        if not path.is_file():
            problems.append(f"{name}: missing; run with --write")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"{name}: differs from the generated schema")
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        print("schema drift detected; run: uv run python scripts/generate_contracts.py --write")
        return 1
    print(f"{len(generated)} schemas match the models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
