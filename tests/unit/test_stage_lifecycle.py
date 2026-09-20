"""Stage transition validity, the cache-key function, and the event/manifest models."""

import pytest

from pgproof.domain.cache import stage_cache_key
from pgproof.domain.envelope import ArtifactType
from pgproof.domain.events import StageEvent, StageEventKind
from pgproof.domain.manifest import ManifestEntry, RunManifest
from pgproof.domain.stages import StageName, StageStatus, validate_stage_transition

RUN = "01JQ0X3M4N5P6R7S8T9V0W1X2Y"
DIGEST = "sha256:" + "a" * 64


# --------------------------------------------------------------------------- #
# Stage transitions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StageStatus.PENDING, StageStatus.RUNNING),
        (StageStatus.PENDING, StageStatus.CANCELLED),
        (StageStatus.RUNNING, StageStatus.COMPLETE),
        (StageStatus.RUNNING, StageStatus.PARTIAL),
        (StageStatus.RUNNING, StageStatus.FAILED),
        (StageStatus.RUNNING, StageStatus.CANCELLED),
    ],
)
def test_legal_transitions_are_accepted(current: StageStatus, target: StageStatus) -> None:
    validate_stage_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (StageStatus.PENDING, StageStatus.COMPLETE),
        (StageStatus.PENDING, StageStatus.PARTIAL),
        (StageStatus.PENDING, StageStatus.FAILED),
        (StageStatus.COMPLETE, StageStatus.RUNNING),
        (StageStatus.FAILED, StageStatus.RUNNING),
        (StageStatus.CANCELLED, StageStatus.RUNNING),
        (StageStatus.RUNNING, StageStatus.PENDING),
    ],
)
def test_illegal_transitions_are_rejected(current: StageStatus, target: StageStatus) -> None:
    with pytest.raises(ValueError, match="invalid stage transition"):
        validate_stage_transition(current, target)


def test_every_terminal_status_has_no_outgoing_transition() -> None:
    for status in (
        StageStatus.COMPLETE,
        StageStatus.PARTIAL,
        StageStatus.FAILED,
        StageStatus.CANCELLED,
    ):
        for target in StageStatus:
            with pytest.raises(ValueError, match="invalid stage transition"):
                validate_stage_transition(status, target)


# --------------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------------- #
def test_cache_key_is_deterministic() -> None:
    kwargs = {
        "stage_config": {"dialect": "postgres"},
        "upstream_hashes": {"schema": DIGEST},
        "file_hashes": {"alembic/versions/0001.py": DIGEST},
        "tool_versions": {"adapter": "1.2.3"},
    }
    assert stage_cache_key(**kwargs) == stage_cache_key(**kwargs)


def test_cache_key_is_a_sha256_digest() -> None:
    key = stage_cache_key(stage_config={"a": "b"})
    assert key.startswith("sha256:")
    assert len(key) == len("sha256:") + 64


def test_cache_key_ignores_input_dict_ordering() -> None:
    one = stage_cache_key(upstream_hashes={"a": DIGEST, "b": DIGEST})
    two = stage_cache_key(upstream_hashes={"b": DIGEST, "a": DIGEST})
    assert one == two


@pytest.mark.parametrize(
    "changed",
    [
        {"stage_config": {"dialect": "mysql"}},
        {"upstream_hashes": {"schema": "sha256:" + "b" * 64}},
        {"file_hashes": {"other.py": DIGEST}},
        {"tool_versions": {"adapter": "9.9.9"}},
        {"environment_identity": {"postgres": "17"}},
    ],
)
def test_cache_key_changes_when_any_input_changes(changed: dict[str, dict[str, str]]) -> None:
    baseline_kwargs: dict[str, dict[str, str]] = {"stage_config": {"dialect": "postgres"}}
    baseline = stage_cache_key(**baseline_kwargs)
    assert stage_cache_key(**{**baseline_kwargs, **changed}) != baseline


# --------------------------------------------------------------------------- #
# Event and manifest models
# --------------------------------------------------------------------------- #
def test_stage_event_round_trips() -> None:
    event = StageEvent(
        run_id=RUN,
        stage=StageName.REPOSITORY_INVENTORY,
        kind=StageEventKind.STAGE_STARTED,
        at="2026-01-01T00:00:00Z",
    )
    assert StageEvent.model_validate_json(event.canonical_json()) == event


def test_run_manifest_rejects_a_future_major() -> None:
    with pytest.raises(ValueError, match="not supported"):
        RunManifest(
            run_id=RUN,
            tool_version="0.1.0",
            created_at="2026-01-01T00:00:00Z",
            schema_version="99.0",
        )


def test_run_manifest_rejects_duplicate_paths() -> None:
    entry = ManifestEntry(
        artifact_type=ArtifactType.SCHEMA,
        path="analysis/schema.json",
        content_hash=DIGEST,
        schema_version="1.0",
    )
    with pytest.raises(ValueError, match="unique paths"):
        RunManifest(
            run_id=RUN,
            tool_version="0.1.0",
            created_at="2026-01-01T00:00:00Z",
            entries=(entry, entry),
        )
