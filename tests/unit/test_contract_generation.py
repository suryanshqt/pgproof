"""Generated artefacts must match their sources: JSON Schemas and TypeScript types."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from generate_contracts import build_schema, generate, render, root_type_name  # noqa: E402

from pgproof.domain.envelope import ArtifactType  # noqa: E402
from pgproof.domain.versioning import SUPPORTED_MAJOR  # noqa: E402

SCHEMAS = REPO / "contracts" / "schemas"
TYPES = REPO / "contracts" / "types"
GENERATED_TS = TYPES / "generated"


# --------------------------------------------------------------------------- #
# JSON Schema generation
# --------------------------------------------------------------------------- #
def test_schema_generation_is_deterministic() -> None:
    assert generate() == generate()


def test_committed_schemas_match_the_models() -> None:
    """This is the same condition the CI drift gate enforces."""
    generated = generate()
    for name, text in sorted(generated.items()):
        path = SCHEMAS / name
        assert path.is_file(), f"{name} is missing; run the generator with --write"
        assert path.read_text(encoding="utf-8") == text, f"{name} has drifted"
    on_disk = {path.name for path in SCHEMAS.glob("*.schema.json")}
    assert on_disk == set(generated)


def test_schema_check_mode_passes_and_detects_drift(tmp_path: Path) -> None:
    from generate_contracts import main

    staged = tmp_path / "schemas"
    staged.mkdir()
    for name, text in generate().items():
        (staged / name).write_text(text, encoding="utf-8")
    assert main(["--check", "--out", str(staged)]) == 0

    (staged / "schema.schema.json").write_text("{}\n", encoding="utf-8")
    assert main(["--check", "--out", str(staged)]) == 1


def test_schema_check_detects_a_missing_and_a_stale_file(tmp_path: Path) -> None:
    from generate_contracts import main

    staged = tmp_path / "schemas"
    staged.mkdir()
    names = sorted(generate())
    for name, text in generate().items():
        (staged / name).write_text(text, encoding="utf-8")
    (staged / names[0]).unlink()
    assert main(["--check", "--out", str(staged)]) == 1

    for name, text in generate().items():
        (staged / name).write_text(text, encoding="utf-8")
    (staged / "retired.schema.json").write_text("{}\n", encoding="utf-8")
    assert main(["--check", "--out", str(staged)]) == 1


def test_schema_write_mode_removes_a_retired_schema(tmp_path: Path) -> None:
    from generate_contracts import main

    staged = tmp_path / "schemas"
    staged.mkdir()
    (staged / "retired.schema.json").write_text("{}\n", encoding="utf-8")
    assert main(["--write", "--out", str(staged)]) == 0
    assert not (staged / "retired.schema.json").exists()
    assert main(["--check", "--out", str(staged)]) == 0


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_each_schema_pins_the_supported_major(artifact_type: ArtifactType) -> None:
    schema = build_schema(artifact_type)
    pattern = schema["properties"]["schema_version"]["pattern"]
    assert pattern == rf"^{SUPPORTED_MAJOR}\.(0|[1-9][0-9]*)$"


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_each_schema_title_is_an_identifier(artifact_type: ArtifactType) -> None:
    """The TypeScript generator derives its root type name from the title."""
    title = build_schema(artifact_type)["title"]
    assert title == root_type_name(artifact_type)
    assert title.isidentifier()
    assert title[0].isupper()


def test_rendered_schema_is_sorted_and_newline_terminated() -> None:
    text = render(build_schema(ArtifactType.SCHEMA))
    assert text.endswith("}\n")
    document = json.loads(text)
    assert list(document) == sorted(document)


# --------------------------------------------------------------------------- #
# TypeScript generation and compilation
# --------------------------------------------------------------------------- #
npm_required = pytest.mark.skipif(
    shutil.which("npm") is None or not (TYPES / "node_modules").is_dir(),
    reason="npm or contracts/types/node_modules unavailable; CI installs it with npm ci",
)


def run_npm(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["npm", "run", "--silent", script],
        cwd=TYPES,
        capture_output=True,
        text=True,
        check=False,
    )


def test_typescript_toolchain_pins_exact_versions() -> None:
    manifest = json.loads((TYPES / "package.json").read_text(encoding="utf-8"))
    pinned = manifest["devDependencies"]
    assert set(pinned) == {"typescript", "json-schema-to-typescript"}
    for name, version in pinned.items():
        assert version[0].isdigit(), f"{name} is not pinned exactly: {version}"


def test_typescript_lockfile_is_committed() -> None:
    lock = json.loads((TYPES / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] >= 3
    assert lock["packages"]


def test_a_generated_module_exists_for_every_artifact() -> None:
    present = {path.stem for path in GENERATED_TS.glob("*.ts")} - {"index"}
    assert present == {artifact_type.value for artifact_type in ArtifactType}


def test_the_barrel_exports_every_root_type() -> None:
    index = (GENERATED_TS / "index.ts").read_text(encoding="utf-8")
    for artifact_type in ArtifactType:
        assert f"export type {{ {root_type_name(artifact_type)} }}" in index


def test_the_smoke_test_uses_every_root_type() -> None:
    smoke = (TYPES / "smoke.ts").read_text(encoding="utf-8")
    for artifact_type in ArtifactType:
        assert root_type_name(artifact_type) in smoke


@npm_required
def test_generated_typescript_has_not_drifted() -> None:
    result = run_npm("check")
    assert result.returncode == 0, result.stdout + result.stderr


@npm_required
def test_generated_typescript_compiles() -> None:
    result = run_npm("compile")
    assert result.returncode == 0, result.stdout + result.stderr
