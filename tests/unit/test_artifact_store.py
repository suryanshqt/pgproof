"""The `.pgproof` layout, atomic writes, artifact round trips, and manifest verification."""

import stat
from pathlib import Path
from typing import Any

import pytest

from pgproof.domain.envelope import ArtifactType, Envelope
from pgproof.domain.manifest import ManifestEntry, RunManifest
from pgproof.domain.registry import envelope_model_for
from pgproof.store.artifacts import content_hash, read_artifact, write_artifact
from pgproof.store.atomic import append_line_durable, write_bytes_atomic
from pgproof.store.manifest import read_run_manifest, verify_manifest, write_run_manifest
from pgproof.store.paths import DIR_MODE, FILE_MODE, ProjectLayout

RUN = "01JQ0X3M4N5P6R7S8T9V0W1X2Y"


def _schema_envelope() -> Envelope[Any]:
    envelope_cls = envelope_model_for(ArtifactType.SCHEMA)
    return envelope_cls(
        tool_version="0.1.0",
        artifact_type=ArtifactType.SCHEMA,
        created_at="2026-01-01T00:00:00Z",
        run_id=RUN,
        data={"provenance": "physical_catalog"},
    )


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
def test_ensure_base_layout_creates_owner_only_directories(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    layout.ensure_base_layout()
    for directory in (
        layout.pgproof_dir,
        layout.analysis_dir,
        layout.diagrams_dir,
        layout.runs_dir,
    ):
        assert directory.is_dir()
        assert stat.S_IMODE(directory.stat().st_mode) == DIR_MODE


def test_analysis_path_is_declared_for_every_placeable_artifact(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    for artifact_type in (
        ArtifactType.SCHEMA,
        ArtifactType.CODE,
        ArtifactType.WORKLOAD,
        ArtifactType.EVIDENCE,
        ArtifactType.RECOMMENDATIONS,
        ArtifactType.SCENARIOS,
    ):
        assert layout.analysis_path(artifact_type).parent == layout.analysis_dir


def test_analysis_path_rejects_an_artifact_with_no_fixed_location(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    with pytest.raises(ValueError, match="no analysis-directory location"):
        layout.analysis_path(ArtifactType.GRAPH)


def test_diagram_path_distinguishes_current_and_target(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    assert layout.diagram_path("current").name == "current.graph.json"
    assert layout.diagram_path("target").name == "target.graph.json"


def test_context_path_is_top_level_not_under_analysis(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    assert layout.context_path == layout.pgproof_dir / "context.json"


def test_run_paths_are_scoped_under_the_run_id(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    run_dir = layout.run_dir(RUN)
    assert layout.run_manifest_path(RUN) == run_dir / "manifest.json"
    assert layout.run_events_path(RUN) == run_dir / "events.ndjson"
    assert layout.run_result_path(RUN) == run_dir / "result.json"


# --------------------------------------------------------------------------- #
# Atomic writes
# --------------------------------------------------------------------------- #
def test_write_bytes_atomic_writes_owner_only_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "file.json"
    write_bytes_atomic(target, b"hello")
    assert target.read_bytes() == b"hello"
    assert stat.S_IMODE(target.stat().st_mode) == FILE_MODE


def test_write_bytes_atomic_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    target = tmp_path / "file.json"
    write_bytes_atomic(target, b"hello")
    assert list(tmp_path.iterdir()) == [target]


def test_a_failed_write_never_disturbs_the_previous_complete_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash injection: a fault after the temp file exists but before rename."""
    target = tmp_path / "file.json"
    write_bytes_atomic(target, b"original")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash before rename")

    monkeypatch.setattr("os.fsync", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        write_bytes_atomic(target, b"corrupted")

    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target], "a crashed write must not leave a stray temp file"


def test_a_failed_first_write_leaves_no_file_at_the_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "file.json"

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr("os.fsync", _boom)
    with pytest.raises(OSError, match="simulated crash"):
        write_bytes_atomic(target, b"never landed")

    assert not target.exists()


def test_append_line_durable_never_truncates(tmp_path: Path) -> None:
    target = tmp_path / "events.ndjson"
    append_line_durable(target, '{"a": 1}')
    append_line_durable(target, '{"a": 2}')
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines == ['{"a": 1}', '{"a": 2}']
    assert stat.S_IMODE(target.stat().st_mode) == FILE_MODE


# --------------------------------------------------------------------------- #
# Artifact read/write
# --------------------------------------------------------------------------- #
def test_write_then_read_artifact_round_trips(tmp_path: Path) -> None:
    envelope = _schema_envelope()
    path = tmp_path / "schema.json"
    digest = write_artifact(path, envelope)
    assert digest.startswith("sha256:")
    read_back = read_artifact(path, ArtifactType.SCHEMA)
    assert read_back == envelope


def test_read_artifact_rejects_a_mismatched_type(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    write_artifact(path, _schema_envelope())
    with pytest.raises(ValueError, match="expected artifact_type 'code'"):
        read_artifact(path, ArtifactType.CODE)


def test_content_hash_is_stable_for_identical_bytes() -> None:
    assert content_hash('{"a":1}') == content_hash('{"a":1}')
    assert content_hash('{"a":1}') != content_hash('{"a":2}')


# --------------------------------------------------------------------------- #
# Manifest verification
# --------------------------------------------------------------------------- #
def test_manifest_round_trips(tmp_path: Path) -> None:
    manifest = RunManifest(
        run_id=RUN,
        tool_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        entries=(
            ManifestEntry(
                artifact_type=ArtifactType.SCHEMA,
                path="analysis/schema.json",
                content_hash="sha256:" + "a" * 64,
                schema_version="1.0",
            ),
        ),
    )
    path = tmp_path / "manifest.json"
    write_run_manifest(path, manifest)
    assert read_run_manifest(path) == manifest


def test_verify_manifest_passes_for_matching_artifacts(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    envelope = _schema_envelope()
    artifact_path = layout.analysis_path(ArtifactType.SCHEMA)
    digest = write_artifact(artifact_path, envelope)
    manifest = RunManifest(
        run_id=RUN,
        tool_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        entries=(
            ManifestEntry(
                artifact_type=ArtifactType.SCHEMA,
                path=str(artifact_path.relative_to(layout.pgproof_dir)),
                content_hash=digest,
                schema_version="1.0",
            ),
        ),
    )
    assert verify_manifest(layout.pgproof_dir, manifest) == ()


def test_verify_manifest_detects_a_corrupted_artifact(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    artifact_path = layout.analysis_path(ArtifactType.SCHEMA)
    digest = write_artifact(artifact_path, _schema_envelope())
    artifact_path.write_text('{"tampered": true}', encoding="utf-8")
    manifest = RunManifest(
        run_id=RUN,
        tool_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        entries=(
            ManifestEntry(
                artifact_type=ArtifactType.SCHEMA,
                path=str(artifact_path.relative_to(layout.pgproof_dir)),
                content_hash=digest,
                schema_version="1.0",
            ),
        ),
    )
    problems = verify_manifest(layout.pgproof_dir, manifest)
    assert len(problems) == 1
    assert "content hash mismatch" in problems[0]


def test_verify_manifest_detects_a_missing_artifact(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path)
    manifest = RunManifest(
        run_id=RUN,
        tool_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        entries=(
            ManifestEntry(
                artifact_type=ArtifactType.SCHEMA,
                path="analysis/schema.json",
                content_hash="sha256:" + "a" * 64,
                schema_version="1.0",
            ),
        ),
    )
    problems = verify_manifest(layout.pgproof_dir, manifest)
    assert len(problems) == 1
    assert "missing on disk" in problems[0]


def test_verify_manifest_detects_an_incompatible_major(tmp_path: Path) -> None:
    """A `ManifestEntry` may record any schema major it wrote under.

    Only reading it back later checks compatibility.
    """
    layout = ProjectLayout(tmp_path)
    manifest = RunManifest(
        run_id=RUN,
        tool_version="0.1.0",
        created_at="2026-01-01T00:00:00Z",
        entries=(
            ManifestEntry(
                artifact_type=ArtifactType.SCHEMA,
                path="analysis/schema.json",
                content_hash="sha256:" + "a" * 64,
                schema_version="99.0",
            ),
        ),
    )
    problems = verify_manifest(layout.pgproof_dir, manifest)
    assert len(problems) == 1
    assert "not supported" in problems[0]
