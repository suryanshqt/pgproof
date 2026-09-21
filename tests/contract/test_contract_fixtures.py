"""Frozen fixture contract.

The fixtures under `contracts/fixtures/` are committed data, not generated
output. A model change that breaks one is supposed to fail here, which is the
whole point of freezing them.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from pgproof.contracts import available_schemas, load_schema, schema_path
from pgproof.domain import (
    ARTIFACT_FILENAMES,
    ArtifactType,
    EvidenceGraph,
    IncompatibleSchemaVersionError,
    envelope_model_for,
    is_compatible,
    parse_artifact,
)
from pgproof.domain.integrity import dangling_evidence_refs
from pgproof.domain.recommendations import RecommendationSet

REPO = Path(__file__).resolve().parents[2]
VALID = REPO / "contracts" / "fixtures" / "valid"
INVALID = REPO / "contracts" / "fixtures" / "invalid"

# Which layer each invalid fixture is rejected by. Graph reference integrity and
# cross-artifact traceability are not expressible in JSON Schema, so those two
# are model-level and integrity-level respectively; the note records that rather
# than pretending the schema catches everything.
INVALID_CASES: dict[str, tuple[str, str]] = {
    "unsupported-major-version": ("version", "not supported"),
    "malformed-digest": ("model", "digest"),
    "absolute-path": ("model", "repository-relative"),
    "non-posix-path": ("model", "POSIX separators"),
    "non-utc-timestamp": ("model", "RFC 3339"),
    "invalid-enum": ("model", "assumed"),
    "missing-required-field": ("model", "tool_version"),
    "dangling-graph-edge": ("model", "unknown nodes"),
    "recommendation-missing-evidence": ("integrity", "ev-does-not-exist"),
    "measurement-without-verified-state": ("model", "only accompany verified_in_fixture"),
    "unqualified-table-id": ("model", "must decode to 2 logical names"),
    "overqualified-column-id": ("model", "must decode to 3 logical names"),
    "dangling-identity-escape": ("model", "dangling escape"),
    "unknown-enum-on-higher-minor": ("model", "presumed"),
}
# Everything except the three joins JSON Schema cannot express. Kept in step with
# NOT_SCHEMA_ENFORCEABLE in contracts/types/validate-fixtures.mjs, asserted below.
NOT_SCHEMA_ENFORCEABLE = {
    "dangling-graph-edge",
    "recommendation-missing-evidence",
    "measurement-without-verified-state",
}
SCHEMA_ENFORCED = set(INVALID_CASES) - NOT_SCHEMA_ENFORCEABLE


def read(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def valid_fixture(artifact_type: ArtifactType) -> dict[str, Any]:
    return read(VALID / f"{artifact_type.value}.json")


# --------------------------------------------------------------------------- #
# Coverage and generated schemas
# --------------------------------------------------------------------------- #
def test_every_artifact_type_has_a_valid_fixture() -> None:
    present = {path.stem for path in VALID.glob("*.json")}
    assert present == {artifact_type.value for artifact_type in ArtifactType}


def test_every_artifact_type_has_a_generated_schema() -> None:
    assert set(available_schemas()) == set(ArtifactType)
    for artifact_type in ArtifactType:
        assert schema_path(artifact_type).name == ARTIFACT_FILENAMES[artifact_type]


def test_generated_schemas_declare_the_2020_12_dialect() -> None:
    for artifact_type in ArtifactType:
        schema = load_schema(artifact_type)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].endswith(ARTIFACT_FILENAMES[artifact_type])
        Draft202012Validator.check_schema(schema)


def test_generated_schemas_carry_no_timestamp_or_machine_data() -> None:
    for artifact_type in ArtifactType:
        text = schema_path(artifact_type).read_text(encoding="utf-8")
        for forbidden in ("/Users/", "/home/", "Darwin", "generated_at"):
            assert forbidden not in text, f"{artifact_type.value}: {forbidden}"


# --------------------------------------------------------------------------- #
# Valid fixtures
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_valid_fixture_validates_against_its_model(artifact_type: ArtifactType) -> None:
    parsed = parse_artifact(valid_fixture(artifact_type))
    assert parsed.artifact_type is artifact_type
    # Every fixture predating a minor that touched its own artifact type stays
    # frozen at the version it was written at, per ADR 0001 rule 6: `schema`
    # moved to 1.2 with BE-17's `extension_versions`/`server_version`/`settings`;
    # `migration_plan` didn't exist before the 1.1 that added it.
    assert parsed.schema_version in {"1.0", "1.1", "1.2"}


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_valid_fixture_validates_against_its_json_schema(
    artifact_type: ArtifactType,
) -> None:
    """Independent validation: jsonschema, not Pydantic."""
    validator = Draft202012Validator(load_schema(artifact_type))
    errors = sorted(validator.iter_errors(valid_fixture(artifact_type)), key=str)
    assert errors == [], [error.message for error in errors]


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_model_to_canonical_json_to_model_round_trips(artifact_type: ArtifactType) -> None:
    document = valid_fixture(artifact_type)
    first = parse_artifact(document)
    canonical = first.canonical_json()
    second = parse_artifact(json.loads(canonical))
    assert second.canonical_json() == canonical
    assert second == first


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_committed_fixture_is_already_canonical(artifact_type: ArtifactType) -> None:
    """The frozen file is the canonical serialisation, so byte diffs are meaningful."""
    document = valid_fixture(artifact_type)
    expected = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert (VALID / f"{artifact_type.value}.json").read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_additive_fields_keep_a_fixture_compatible(artifact_type: ArtifactType) -> None:
    document = valid_fixture(artifact_type)
    document["schema_version"] = "1.7"
    document["added_in_a_later_minor"] = {"nested": [1, 2, 3]}
    if isinstance(document["data"], dict):
        document["data"]["also_added_later"] = "tolerated"
    parsed = parse_artifact(document)
    assert parsed.schema_version == "1.7"
    assert parsed.data == parse_artifact(valid_fixture(artifact_type)).data


def test_fixtures_contain_only_synthetic_data() -> None:
    for path in sorted(VALID.glob("*.json")) + sorted(INVALID.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("/Users/", "/home/", "suryansh", "docstribe", "@gmail"):
            assert forbidden not in text.lower(), f"{path.name}: {forbidden}"


# --------------------------------------------------------------------------- #
# Invalid fixtures
# --------------------------------------------------------------------------- #
def test_invalid_fixture_inventory_is_complete() -> None:
    present = {path.stem for path in INVALID.glob("*.json")}
    assert present == set(INVALID_CASES)


@pytest.mark.parametrize("name", sorted(INVALID_CASES), ids=lambda n: n)
def test_invalid_fixture_fails_for_the_expected_reason(name: str) -> None:
    layer, expected = INVALID_CASES[name]
    document = read(INVALID / f"{name}.json")

    if layer == "version":
        with pytest.raises(IncompatibleSchemaVersionError, match=expected):
            parse_artifact(document)
        return

    if layer == "integrity":
        recommendations = RecommendationSet.model_validate(document["data"])
        evidence = EvidenceGraph.model_validate(valid_fixture(ArtifactType.EVIDENCE)["data"])
        assert expected in dangling_evidence_refs(recommendations, evidence)
        return

    with pytest.raises((ValidationError, ValueError), match=expected):
        parse_artifact(document)


@pytest.mark.parametrize("name", sorted(SCHEMA_ENFORCED), ids=lambda n: n)
def test_schema_enforced_invalid_fixtures_also_fail_independent_validation(name: str) -> None:
    document = read(INVALID / f"{name}.json")
    artifact_type = ArtifactType(document["artifact_type"])
    validator = Draft202012Validator(load_schema(artifact_type))
    errors = list(validator.iter_errors(document))
    assert errors, f"{name} should fail JSON Schema validation"


def test_reference_integrity_is_not_claimed_to_be_schema_enforced() -> None:
    """Recorded deliberately: JSON Schema cannot express these three joins."""
    assert set(INVALID_CASES) - SCHEMA_ENFORCED == NOT_SCHEMA_ENFORCEABLE


def test_python_and_typescript_agree_on_what_json_schema_enforces() -> None:
    """Both validators must carry the same not-enforceable list."""
    script = (REPO / "contracts" / "types" / "validate-fixtures.mjs").read_text(encoding="utf-8")
    block = script.split("NOT_SCHEMA_ENFORCEABLE = new Set([")[1].split("]);")[0]
    declared = {line.strip().strip('",') for line in block.splitlines() if '"' in line}
    assert declared == NOT_SCHEMA_ENFORCEABLE


@pytest.mark.parametrize("name", sorted(SCHEMA_ENFORCED), ids=lambda n: n)
def test_schema_enforced_cases_are_rejected_by_python_too(name: str) -> None:
    """A rule the schema enforces must also be enforced by the model."""
    document = read(INVALID / f"{name}.json")
    with pytest.raises((ValidationError, ValueError)):
        parse_artifact(document)


def test_unknown_enum_value_is_rejected_even_on_a_higher_minor() -> None:
    """ADR 0001 rule 5: an enum change is major, so an unknown value never passes."""
    document = read(INVALID / "unknown-enum-on-higher-minor.json")
    assert document["schema_version"] == "1.7"
    assert is_compatible(document["schema_version"]), "the minor must be compatible"
    with pytest.raises(ValidationError, match="presumed"):
        parse_artifact(document)
    validator = Draft202012Validator(load_schema(ArtifactType.EVIDENCE))
    assert list(validator.iter_errors(document)), "independent validation must reject it"


def test_a_fixture_with_an_identifier_rule_fails_in_both_layers() -> None:
    """The reported defect: Pydantic rejected an unqualified table id, the schema did not."""
    document = read(INVALID / "unqualified-table-id.json")
    assert document["data"]["tables"][1]["id"] == "not-qualified"
    with pytest.raises(ValidationError, match="must decode to 2 logical names"):
        parse_artifact(document)
    validator = Draft202012Validator(load_schema(ArtifactType.SCHEMA))
    errors = list(validator.iter_errors(document))
    assert errors, "the generated schema must reject it too"


def test_valid_fixtures_trace_every_recommendation_to_real_evidence() -> None:
    recommendations = RecommendationSet.model_validate(
        valid_fixture(ArtifactType.RECOMMENDATIONS)["data"]
    )
    evidence = EvidenceGraph.model_validate(valid_fixture(ArtifactType.EVIDENCE)["data"])
    assert dangling_evidence_refs(recommendations, evidence) == ()


def test_every_valid_fixture_parses_through_its_concrete_envelope_model() -> None:
    for artifact_type in ArtifactType:
        model = envelope_model_for(artifact_type)
        assert model.model_validate(valid_fixture(artifact_type)).artifact_type is artifact_type
