"""Model behaviour: envelope discrimination, graph integrity, traceability, versions."""

import pytest
from pydantic import ValidationError

from pgproof.domain import (
    ARTIFACT_FILENAMES,
    ARTIFACT_MODELS,
    CONTRACT_SCHEMA_VERSION,
    ENVELOPE_MODELS,
    SUPPORTED_MAJOR,
    ArtifactType,
    EvidenceGraph,
    EvidenceKind,
    EvidenceRef,
    IncompatibleSchemaVersionError,
    data_model_for,
    envelope_model_for,
    is_compatible,
    parse_artifact,
    require_supported,
)
from pgproof.domain.experiments import (
    ArmMeasurement,
    ExperimentArm,
    ProofSummary,
    ProofVerdict,
    TreatmentKind,
)
from pgproof.domain.graph import EdgeKind, GraphEdge, GraphIR, GraphNode, NodeKind
from pgproof.domain.integrity import (
    dangling_evidence_refs,
    dangling_question_refs,
    dangling_scenario_refs,
    untraceable_recommendations,
)
from pgproof.domain.ir.schema import SchemaIR
from pgproof.domain.questions import AnswerSchema, MaterialQuestion
from pgproof.domain.recommendations import (
    ChangeKind,
    FixtureMeasurement,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationSet,
    VerificationState,
)
from pgproof.domain.scenarios import (
    DeltaKind,
    Scenario,
    ScenarioDelta,
    ScenarioDiff,
    ScenarioKind,
    ScenarioSet,
)
from pgproof.domain.stages import StageName, StageStatus, StageSummary

RUN = "01JQ0X3M4N5P6R7S8T9V0W1X2Y"
DIGEST = "sha256:" + "a" * 64


def envelope(artifact_type: ArtifactType, data: object, **overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "tool_version": "0.1.0",
        "artifact_type": artifact_type.value,
        "created_at": "2026-01-01T00:00:00Z",
        "run_id": RUN,
        "inputs": {"repository": DIGEST},
        "data": data,
    }
    document.update(overrides)
    return document


# --------------------------------------------------------------------------- #
# Registry and envelope discrimination
# --------------------------------------------------------------------------- #
def test_registry_covers_every_artifact_type_exactly_once() -> None:
    assert set(ARTIFACT_MODELS) == set(ArtifactType)
    assert set(ENVELOPE_MODELS) == set(ArtifactType)
    assert set(ARTIFACT_FILENAMES) == set(ArtifactType)
    assert len(set(ARTIFACT_FILENAMES.values())) == len(ArtifactType)


def test_envelope_table_agrees_with_the_data_model_table() -> None:
    """The two tables are written out separately; this is what stops them drifting."""
    for artifact_type in ArtifactType:
        annotation = ENVELOPE_MODELS[artifact_type].model_fields["data"].annotation
        assert annotation is ARTIFACT_MODELS[artifact_type], artifact_type.value


def test_parse_artifact_dispatches_on_artifact_type() -> None:
    parsed = parse_artifact(envelope(ArtifactType.SCHEMA, {"provenance": "physical_catalog"}))
    assert parsed.artifact_type is ArtifactType.SCHEMA
    assert isinstance(parsed.data, SchemaIR)


def test_parse_artifact_rejects_an_unknown_artifact_type() -> None:
    document = envelope(ArtifactType.SCHEMA, {"provenance": "physical_catalog"})
    document["artifact_type"] = "not_an_artifact"
    with pytest.raises(ValueError, match="unknown artifact_type"):
        parse_artifact(document)


def test_parse_artifact_rejects_a_non_string_artifact_type() -> None:
    document = envelope(ArtifactType.SCHEMA, {"provenance": "physical_catalog"})
    document["artifact_type"] = 7
    with pytest.raises(ValueError, match="must be a string"):
        parse_artifact(document)


def test_payload_of_the_wrong_shape_is_rejected() -> None:
    with pytest.raises(ValidationError):
        envelope_model_for(ArtifactType.GRAPH).model_validate(
            envelope(ArtifactType.GRAPH, {"provenance": "physical_catalog"})
        )


def test_envelope_requires_every_declared_field() -> None:
    for missing in ("tool_version", "artifact_type", "created_at", "run_id", "data"):
        document = envelope(ArtifactType.EVIDENCE, {"refs": []})
        del document[missing]
        with pytest.raises(ValidationError, match=missing):
            envelope_model_for(ArtifactType.EVIDENCE).model_validate(document)


def test_run_id_must_be_a_ulid() -> None:
    for bad in ["short", RUN.lower(), RUN + "Z", "01JQ0X3M4N5P6R7S8T9V0W1X2I"]:
        document = envelope(ArtifactType.EVIDENCE, {"refs": []}, run_id=bad)
        with pytest.raises(ValidationError):
            envelope_model_for(ArtifactType.EVIDENCE).model_validate(document)


def test_data_model_for_matches_the_registry() -> None:
    assert data_model_for(ArtifactType.EVIDENCE) is EvidenceGraph


# --------------------------------------------------------------------------- #
# Version compatibility
# --------------------------------------------------------------------------- #
def test_contract_schema_version_starts_at_one_zero() -> None:
    assert CONTRACT_SCHEMA_VERSION == "1.0"
    assert SUPPORTED_MAJOR == 1


@pytest.mark.parametrize("value", ["1.0", "1.1", "1.9", "1.10", "1.99"])
def test_same_major_minors_are_accepted(value: str) -> None:
    assert require_supported(value).major == 1
    assert is_compatible(value)


@pytest.mark.parametrize("value", ["2.0", "0.9", "3.1"])
def test_unsupported_majors_are_rejected(value: str) -> None:
    with pytest.raises(IncompatibleSchemaVersionError, match="not supported"):
        require_supported(value)
    assert not is_compatible(value)


@pytest.mark.parametrize("value", ["1", "1.0.0", "v1.0", "01.0", "", "abc"])
def test_malformed_versions_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="not a schema version"):
        require_supported(value)
    assert not is_compatible(value)


def test_envelope_rejects_a_future_major() -> None:
    document = envelope(ArtifactType.EVIDENCE, {"refs": []}, schema_version="2.0")
    with pytest.raises(ValidationError, match="not supported"):
        envelope_model_for(ArtifactType.EVIDENCE).model_validate(document)


def test_parse_artifact_reports_the_version_before_the_payload() -> None:
    """A future-major document fails on version, not on a confusing field error."""
    document = envelope(ArtifactType.EVIDENCE, {"nonsense": True}, schema_version="9.0")
    with pytest.raises(IncompatibleSchemaVersionError):
        parse_artifact(document)


def test_tool_version_is_independent_of_schema_version() -> None:
    for tool in ("0.1.0", "1.2.3", "2.0.0-rc1"):
        parsed = envelope_model_for(ArtifactType.EVIDENCE).model_validate(
            envelope(ArtifactType.EVIDENCE, {"refs": []}, tool_version=tool)
        )
        assert parsed.tool_version == tool
        assert parsed.schema_version == CONTRACT_SCHEMA_VERSION


def test_additive_minor_fields_are_tolerated_end_to_end() -> None:
    document = envelope(ArtifactType.EVIDENCE, {"refs": [], "added_in_1_1": []})
    document["added_in_1_1"] = {"anything": True}
    document["schema_version"] = "1.1"
    parsed = parse_artifact(document)
    assert parsed.schema_version == "1.1"
    assert isinstance(parsed.data, EvidenceGraph)


# --------------------------------------------------------------------------- #
# Graph reference integrity
# --------------------------------------------------------------------------- #
def _nodes() -> tuple[GraphNode, ...]:
    return (
        GraphNode(id="table:public.orders", kind=NodeKind.TABLE, label="orders"),
        GraphNode(id="table:public.tenants", kind=NodeKind.TABLE, label="tenants"),
    )


def test_graph_accepts_edges_between_known_nodes() -> None:
    graph = GraphIR(
        view="current",
        nodes=_nodes(),
        edges=(
            GraphEdge(
                id="e1",
                kind=EdgeKind.ORM_ONLY_RELATIONSHIP,
                source="table:public.orders",
                target="table:public.tenants",
            ),
        ),
    )
    assert len(graph.edges) == 1


def test_graph_rejects_a_dangling_edge() -> None:
    with pytest.raises(ValidationError, match="unknown nodes"):
        GraphIR(
            view="current",
            nodes=_nodes(),
            edges=(
                GraphEdge(
                    id="e1",
                    kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
                    source="table:public.orders",
                    target="table:public.missing",
                ),
            ),
        )


def test_graph_rejects_duplicate_node_and_edge_ids() -> None:
    duplicate = _nodes()[0]
    with pytest.raises(ValidationError, match="node ids must be unique"):
        GraphIR(view="current", nodes=(duplicate, duplicate))
    edge = GraphEdge(
        id="e1",
        kind=EdgeKind.CONTAINS,
        source="table:public.orders",
        target="table:public.tenants",
    )
    with pytest.raises(ValidationError, match="edge ids must be unique"):
        GraphIR(view="current", nodes=_nodes(), edges=(edge, edge))


def test_physical_and_orm_only_edges_are_different_kinds() -> None:
    """`docs/ARCHITECTURE.md` section 17: they cannot serialise as the same kind."""
    kinds = {EdgeKind.PHYSICAL_FOREIGN_KEY.value, EdgeKind.ORM_ONLY_RELATIONSHIP.value}
    assert len(kinds) == 2
    physical = GraphEdge(
        id="e1",
        kind=EdgeKind.PHYSICAL_FOREIGN_KEY,
        source="table:public.orders",
        target="table:public.tenants",
    )
    orm_only = physical.model_copy(update={"kind": EdgeKind.ORM_ONLY_RELATIONSHIP})
    assert physical.canonical_json() != orm_only.canonical_json()


# --------------------------------------------------------------------------- #
# Recommendation contract
# --------------------------------------------------------------------------- #
def _base_recommendation(**overrides: object) -> Recommendation:
    fields: dict[str, object] = {
        "id": "TENANT-001",
        "rule": "schema_integrity.orm_relationship_without_physical_fk",
        "rule_version": 1,
        "title": "Enforce tenant ownership for orders",
        "priority": RecommendationPriority.REQUIRED_FOR_CORRECTNESS,
        "category": RecommendationCategory.TENANCY,
        "statement": "The ORM links orders to tenants, but PostgreSQL does not.",
        "affected_objects": ("public.orders.tenant_id",),
        "proposed_change": ProposedChange(kind=ChangeKind.ADD_CONSTRAINT, summary="Add the FK."),
    }
    fields.update(overrides)
    return Recommendation(**fields)  # type: ignore[arg-type]


def test_evidence_kinds_are_exactly_the_four_labels() -> None:
    assert [kind.value for kind in EvidenceKind] == [
        "observed",
        "user_confirmed",
        "inferred",
        "verified_in_fixture",
    ]


def test_recommendation_priorities_are_exactly_the_five_groups() -> None:
    assert [priority.value for priority in RecommendationPriority] == [
        "required_for_correctness",
        "required_by_confirmed_requirements",
        "verified_improvement",
        "worth_evaluating",
        "optional_hardening",
    ]


def test_recommendation_needs_an_affected_object() -> None:
    with pytest.raises(ValidationError, match="at least one affected object"):
        _base_recommendation(affected_objects=())


def test_recommendation_needs_a_change_or_a_question() -> None:
    with pytest.raises(ValidationError, match="proposed change or a blocking question"):
        _base_recommendation(proposed_change=None)
    assert (
        _base_recommendation(
            proposed_change=None, blocking_question="read_after_write_invoices"
        ).blocking_question
        == "read_after_write_invoices"
    )


def test_a_measurement_cannot_be_attached_without_a_verified_state() -> None:
    measurement = FixtureMeasurement(
        fixture_scale="orders 400000",
        control_median_us=9760,
        treatment_median_us=240,
        absolute_saving_us=9520,
    )
    with pytest.raises(ValidationError, match="only accompany verified_in_fixture"):
        _base_recommendation(measurement=measurement)


def test_verified_state_requires_a_measurement_to_cite() -> None:
    with pytest.raises(ValidationError, match="requires a fixture measurement"):
        _base_recommendation(verification_state=VerificationState.VERIFIED_IN_FIXTURE)


def test_verified_improvement_priority_requires_a_verified_state() -> None:
    with pytest.raises(ValidationError, match="requires verification_state"):
        _base_recommendation(priority=RecommendationPriority.VERIFIED_IMPROVEMENT)


def test_a_fixture_measurement_always_carries_its_scale() -> None:
    """There is no field in which a production prediction could be written."""
    fields = set(FixtureMeasurement.model_fields)
    assert "fixture_scale" in fields
    assert FixtureMeasurement.model_fields["fixture_scale"].is_required()
    assert not any("production" in name or "expected" in name for name in fields)


# --------------------------------------------------------------------------- #
# Traceability
# --------------------------------------------------------------------------- #
def _evidence() -> EvidenceGraph:
    return EvidenceGraph(
        refs=(
            EvidenceRef(id="ev-1", kind=EvidenceKind.OBSERVED, summary="Seen in code."),
            EvidenceRef(id="ev-2", kind=EvidenceKind.USER_CONFIRMED, summary="Confirmed."),
        )
    )


def test_recommendations_tracing_to_existing_evidence_pass() -> None:
    recommendations = RecommendationSet(
        recommendations=(_base_recommendation(evidence_refs=("ev-1", "ev-2")),)
    )
    assert dangling_evidence_refs(recommendations, _evidence()) == ()
    assert untraceable_recommendations(recommendations, _evidence()) == ()


def test_a_recommendation_citing_missing_evidence_is_reported() -> None:
    recommendations = RecommendationSet(
        recommendations=(_base_recommendation(evidence_refs=("ev-1", "ev-nope")),)
    )
    assert dangling_evidence_refs(recommendations, _evidence()) == ("ev-nope",)


def test_a_recommendation_with_no_resolvable_evidence_is_untraceable() -> None:
    recommendations = RecommendationSet(recommendations=(_base_recommendation(),))
    assert untraceable_recommendations(recommendations, _evidence()) == ("TENANT-001",)


def test_dangling_question_links_are_reported_in_both_directions() -> None:
    recommendations = RecommendationSet(
        recommendations=(_base_recommendation(blocking_question="absent_question"),),
        questions=(
            MaterialQuestion(
                id="present_question",
                prompt="Does it matter?",
                answer_schema=AnswerSchema.BOOLEAN,
                why_it_matters="It decides routing.",
                affected_recommendations=("IDX-999",),
            ),
        ),
    )
    assert dangling_question_refs(recommendations) == ("IDX-999", "absent_question")


def test_dangling_scenario_references_are_reported() -> None:
    recommendations = RecommendationSet(recommendations=(_base_recommendation(),))
    scenarios = ScenarioSet(
        scenarios=(
            Scenario(
                kind=ScenarioKind.LAUNCH_MINIMAL,
                title="Launch-minimal",
                summary="Simplest satisfying design.",
                recommendations=("TENANT-001", "IDX-404"),
            ),
        ),
        diffs=(
            ScenarioDiff(
                base=ScenarioKind.LAUNCH_MINIMAL,
                target=ScenarioKind.GROWTH_READY,
                deltas=(
                    ScenarioDelta(
                        kind=DeltaKind.ADDED,
                        recommendation="IDX-505",
                        explanation="Added at the twelve-month scale.",
                    ),
                ),
            ),
        ),
    )
    assert dangling_scenario_refs(scenarios, recommendations) == ("IDX-404", "IDX-505")


# --------------------------------------------------------------------------- #
# Stage and proof contracts
# --------------------------------------------------------------------------- #
def test_a_failed_stage_must_state_why() -> None:
    with pytest.raises(ValidationError, match="state its failure reason"):
        StageSummary(stage=StageName.QUERY_CAPTURE, status=StageStatus.FAILED)


def test_a_partial_stage_must_state_its_boundary() -> None:
    with pytest.raises(ValidationError, match="state its boundary"):
        StageSummary(stage=StageName.QUERY_CAPTURE, status=StageStatus.PARTIAL)


def _arm(arm: ExperimentArm) -> ArmMeasurement:
    return ArmMeasurement(
        arm=arm,
        samples=7,
        warmups_discarded=3,
        median_us=100,
        q1_us=95,
        q3_us=105,
        iqr_fraction="0.1000",
    )


def test_a_verified_proof_requires_all_three_arms() -> None:
    with pytest.raises(ValidationError, match="missing"):
        ProofSummary(
            id=f"IDX-002@{DIGEST}",
            recommendation="IDX-002",
            treatment=TreatmentKind.COMPOSITE_BTREE,
            verdict=ProofVerdict.VERIFIED_IN_FIXTURE,
            fixture_scale="orders 400000",
            dataset_seed="synthetic-1",
            postgres_version="17",
            input_manifest_hash=DIGEST,
            absolute_saving_us=9520,
            arms=(_arm(ExperimentArm.CONTROL_A1), _arm(ExperimentArm.TREATMENT_B)),
        )


def test_proof_identity_must_match_its_recommendation() -> None:
    with pytest.raises(ValidationError, match="input-manifest hash"):
        ProofSummary(
            id=f"IDX-002@{DIGEST}",
            recommendation="IDX-003",
            treatment=TreatmentKind.COMPOSITE_BTREE,
            verdict=ProofVerdict.UNSUPPORTED,
            fixture_scale="orders 400000",
            dataset_seed="synthetic-1",
            postgres_version="17",
            input_manifest_hash=DIGEST,
        )


def test_no_proof_field_reports_a_percentile() -> None:
    """`docs/TECHNICAL_DESIGN.md` section 20: seven samples cannot support a p95."""
    for model in (ProofSummary, ArmMeasurement):
        for name in model.model_fields:
            assert "p95" not in name
            assert "percentile" not in name


def test_pydantic_is_bounded_below_version_three() -> None:
    """The models target the Pydantic v2 API and its schema generator."""
    import importlib.metadata as metadata
    import re

    requirements = metadata.requires("pgproof") or []
    pydantic = [item for item in requirements if item.startswith("pydantic")]
    assert len(pydantic) == 1, requirements
    assert ">=2.9" in pydantic[0]
    assert "<3" in pydantic[0]
    installed = metadata.version("pydantic")
    assert re.match(r"^2\.", installed), f"expected Pydantic 2.x, got {installed}"


# --------------------------------------------------------------------------- #
# Enum versioning policy: closed semantic enums vs the artifact-kind registry
# --------------------------------------------------------------------------- #
# ADR 0001 rule 5. These carry product meaning and are matched exhaustively, so
# any member change is a major contract change.
CLOSED_SEMANTIC_ENUMS = (
    "EvidenceKind",
    "RecommendationPriority",
    "RecommendationCategory",
    "VerificationState",
    "ProofVerdict",
    "StageStatus",
    "StageName",
    "EdgeKind",
    "NodeKind",
    "AmplificationClass",
    "WorkloadCoverage",
    "ScenarioKind",
    "TenantModel",
    "AnswerState",
    "AnswerSchema",
    "ChangeKind",
    "SchemaProvenance",
    "ConstraintKind",
    "LoadingStrategy",
)


def test_evidence_kind_stays_closed_at_exactly_four_labels() -> None:
    """Rule 5 and ARCHITECTURE section 16 both gate this enum."""
    assert len(EvidenceKind) == 4
    assert {kind.value for kind in EvidenceKind} == {
        "observed",
        "user_confirmed",
        "inferred",
        "verified_in_fixture",
    }


def test_the_closed_semantic_enums_all_exist_and_reject_unknown_values() -> None:
    import importlib
    import pkgutil
    from enum import Enum

    import pgproof.domain as package

    found: dict[str, type[Enum]] = {}
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        module = importlib.import_module(info.name)
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, type) and issubclass(value, Enum) and value is not Enum:
                found[value.__name__] = value
    missing = [name for name in CLOSED_SEMANTIC_ENUMS if name not in found]
    assert missing == [], f"ADR 0001 rule 5 names enums that do not exist: {missing}"
    for name in CLOSED_SEMANTIC_ENUMS:
        with pytest.raises(ValueError, match="is not a valid"):
            found[name]("a_value_no_release_ever_defined")


def test_artifact_type_is_the_additive_registry_not_a_semantic_enum() -> None:
    """Rule 6: a new artifact kind may land as a minor, so it is listed separately."""
    assert "ArtifactType" not in CLOSED_SEMANTIC_ENUMS
    # The kinds the roadmap still has to add. Their absence is exactly why rule 6
    # exists: a blanket major-only rule would have forced a bump to finish BE-04,
    # BE-14 and BE-33. None of them is implemented here.
    planned_later = {"project", "migration_plan", "decisions"}
    assert planned_later & {item.value for item in ArtifactType} == set()


def test_an_unknown_artifact_kind_is_rejected_by_name() -> None:
    """An older reader refuses a kind it does not know, and says which it knows."""
    document = envelope(ArtifactType.SCHEMA, {"provenance": "physical_catalog"})
    document["artifact_type"] = "project"
    with pytest.raises(ValueError, match="unknown artifact_type 'project'") as raised:
        parse_artifact(document)
    for known in ArtifactType:
        assert known.value in str(raised.value)


def test_every_known_artifact_kind_still_parses_alongside_an_unknown_one() -> None:
    """Rule 6 is only additive if an unknown kind does not disturb known ones."""
    unknown = envelope(ArtifactType.EVIDENCE, {"refs": []})
    unknown["artifact_type"] = "not_yet_invented"
    with pytest.raises(ValueError, match="unknown artifact_type"):
        parse_artifact(unknown)
    for artifact_type, payload in (
        (ArtifactType.EVIDENCE, {"refs": []}),
        (ArtifactType.SCHEMA, {"provenance": "physical_catalog"}),
        (ArtifactType.GRAPH, {"view": "current"}),
    ):
        assert parse_artifact(envelope(artifact_type, payload)).artifact_type is artifact_type


@pytest.mark.parametrize("artifact_type", list(ArtifactType), ids=lambda t: t.value)
def test_each_envelope_is_strictly_discriminated(artifact_type: ArtifactType) -> None:
    """A document of one kind cannot be read through another kind's contract."""
    model = envelope_model_for(artifact_type)
    assert model.model_fields["artifact_type"].is_required()
    for other in ArtifactType:
        if other is artifact_type:
            continue
        document = envelope(other, {"refs": []})
        with pytest.raises(ValidationError):
            model.model_validate(document)
