"""`adapters.proof.reproduce`'s pure helpers, and `reproduce_bundle`'s own
short-circuit paths (tampered bundle, incompatible schema version, redacted
parameters with no recoverable value) — each returns before touching `conn`
or `credentials` at all, so they are real, non-mocked behaviour even with
`None` standing in for both: the type signature expects them, but these
paths never dereference them. The data-touching path (a real `_apply_dataset`
and `run_experiment` call) is exercised for real in
`tests/integration/test_adapters_proof_reproduce.py`, which needs Docker.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from pgproof.adapters.benchmark.explain import parse_explain
from pgproof.adapters.benchmark.run import ExperimentResult
from pgproof.adapters.proof.bundle import BundleContents, BundleManifest, write_proof_bundle
from pgproof.adapters.proof.reproduce import (
    _bind_parameters,
    _candidate_from_config,
    _evaluate,
    _median_us,
    _original_direction,
    _recorded_plan_fingerprint,
    reproduce_bundle,
)

_NO_EXPLAIN_RESULT = ExperimentResult(
    control_a1=None,
    treatment_b=None,
    drift_control_a2=None,
    explain_a1=None,
    explain_b=None,
    absolute_saving_us=100.0,
    ratio=2.0,
    drift_fraction=0.01,
    high_variance=False,
    drift_detected=False,
    inconclusive=False,
    cancelled=False,
    timed_out=False,
)


def _contents(*, evidence: Mapping[str, object], plans: Mapping[str, object]) -> BundleContents:
    return BundleContents(
        manifest=BundleManifest(
            proof_id="IDX-001@sha256:" + "a" * 64,
            tool_version="0.1.0",
            schema_version="1.3",
            generator_version=1,
            file_hashes={},
        ),
        schema_sql="CREATE TABLE orders (id serial PRIMARY KEY);",
        query_sql="SELECT id FROM orders",
        parameters={},
        dataset={},
        config={},
        evidence=dict(evidence),
        plans=dict(plans),
    )


_FASTER_EVIDENCE = {"control-a1": {"median_us": 5000.0}, "treatment-b": {"median_us": 500.0}}


def test_evaluate_reproduces_when_direction_and_stability_both_hold() -> None:
    result = _evaluate(_contents(evidence=_FASTER_EVIDENCE, plans={}), _NO_EXPLAIN_RESULT)
    assert result.direction_matches is True
    assert result.stable is True
    assert result.plan_shape_compatible is None
    assert result.reproduced is True


def test_evaluate_does_not_reproduce_when_the_new_run_is_inconclusive() -> None:
    inconclusive = replace(_NO_EXPLAIN_RESULT, inconclusive=True)
    result = _evaluate(_contents(evidence=_FASTER_EVIDENCE, plans={}), inconclusive)
    assert result.stable is False
    assert result.reproduced is False


def test_evaluate_does_not_reproduce_when_direction_disagrees() -> None:
    reversed_evidence = {"control-a1": {"median_us": 500.0}, "treatment-b": {"median_us": 5000.0}}
    result = _evaluate(_contents(evidence=reversed_evidence, plans={}), _NO_EXPLAIN_RESULT)
    assert result.direction_matches is False
    assert result.reproduced is False


def test_evaluate_has_no_direction_opinion_when_the_bundle_recorded_no_evidence() -> None:
    result = _evaluate(_contents(evidence={}, plans={}), _NO_EXPLAIN_RESULT)
    assert result.direction_matches is None
    assert result.reproduced is False


_EXPLAIN_B = [
    {
        "Plan": {
            "Node Type": "Index Scan",
            "Index Name": "ix_orders_user_id",
            "Relation Name": "orders",
        },
        "Planning Time": 0.1,
        "Execution Time": 0.2,
    }
]


def test_evaluate_matches_a_recorded_plan_fingerprint_byte_for_byte() -> None:
    fingerprint = parse_explain(_EXPLAIN_B).plan_fingerprint
    with_explain = replace(_NO_EXPLAIN_RESULT, explain_b=_EXPLAIN_B)
    result = _evaluate(
        _contents(
            evidence=_FASTER_EVIDENCE, plans={"treatment-b": {"plan_fingerprint": fingerprint}}
        ),
        with_explain,
    )
    assert result.plan_shape_compatible is True
    assert result.reproduced is True


def test_evaluate_rejects_a_different_plan_fingerprint() -> None:
    with_explain = replace(_NO_EXPLAIN_RESULT, explain_b=_EXPLAIN_B)
    result = _evaluate(
        _contents(
            evidence=_FASTER_EVIDENCE,
            plans={"treatment-b": {"plan_fingerprint": "sha256:" + "f" * 64}},
        ),
        with_explain,
    )
    assert result.plan_shape_compatible is False
    assert result.reproduced is False


def test_candidate_from_config_reads_apply_and_revert_sql() -> None:
    candidate, settings = _candidate_from_config(
        {
            "candidate": {"apply_sql": "CREATE INDEX ...", "revert_sql": "DROP INDEX ..."},
            "postgres_settings": {"enable_seqscan": "off"},
        }
    )
    assert candidate.apply_sql == "CREATE INDEX ..."
    assert candidate.revert_sql == "DROP INDEX ..."
    assert settings == {"enable_seqscan": "off"}


def test_candidate_from_config_defaults_to_a_noop_when_absent() -> None:
    candidate, settings = _candidate_from_config({})
    assert candidate.apply_sql == "SELECT 1"
    assert candidate.revert_sql == "SELECT 1"
    assert settings == {}


def test_median_us_reads_a_present_arm() -> None:
    assert _median_us({"control-a1": {"median_us": 500.0}}, "control-a1") == 500.0


def test_median_us_is_none_for_a_missing_arm() -> None:
    assert _median_us({}, "control-a1") is None


def test_median_us_is_none_when_the_arm_is_not_a_mapping() -> None:
    assert _median_us({"control-a1": "not a mapping"}, "control-a1") is None


def test_original_direction_is_true_when_the_treatment_was_faster() -> None:
    evidence = {"control-a1": {"median_us": 5000.0}, "treatment-b": {"median_us": 500.0}}
    assert _original_direction(evidence) is True


def test_original_direction_is_false_when_the_treatment_was_not_faster() -> None:
    evidence = {"control-a1": {"median_us": 500.0}, "treatment-b": {"median_us": 5000.0}}
    assert _original_direction(evidence) is False


def test_original_direction_is_none_when_either_arm_is_absent() -> None:
    assert _original_direction({"control-a1": {"median_us": 500.0}}) is None
    assert _original_direction({}) is None


def test_original_direction_is_none_for_a_zero_treatment_median() -> None:
    evidence = {"control-a1": {"median_us": 500.0}, "treatment-b": {"median_us": 0.0}}
    assert _original_direction(evidence) is None


def test_recorded_plan_fingerprint_reads_the_treatment_b_plan() -> None:
    plans = {"treatment-b": {"plan_fingerprint": "sha256:" + "a" * 64}}
    assert _recorded_plan_fingerprint(plans) == "sha256:" + "a" * 64


def test_recorded_plan_fingerprint_is_none_when_absent() -> None:
    assert _recorded_plan_fingerprint({}) is None


def test_recorded_plan_fingerprint_is_none_when_the_field_is_missing() -> None:
    assert _recorded_plan_fingerprint({"treatment-b": {"normalized_shape": "Seq Scan"}}) is None


def test_bind_parameters_resolves_an_unredacted_descriptor() -> None:
    resolved = _bind_parameters({"user_id": {"is_redacted": False, "redacted_value": 1}})
    assert resolved == {"user_id": 1}


def test_bind_parameters_is_none_when_any_descriptor_is_redacted() -> None:
    assert _bind_parameters({"user_id": {"is_redacted": True}}) is None


def test_bind_parameters_is_none_when_redacted_value_is_missing() -> None:
    assert _bind_parameters({"user_id": {"is_redacted": False}}) is None


def test_bind_parameters_is_none_for_a_non_mapping_descriptor() -> None:
    assert _bind_parameters({"user_id": 1}) is None


def test_bind_parameters_of_an_empty_mapping_is_an_empty_mapping() -> None:
    assert _bind_parameters({}) == {}


_FAKE_CONN = cast(Any, None)
_FAKE_CREDENTIALS = cast(Any, None)


def _write(directory: Path, **overrides: object) -> None:
    defaults: dict[str, object] = {
        "proof_id": "IDX-001@sha256:" + "a" * 64,
        "tool_version": "0.1.0",
        "generator_version": 1,
        "schema_sql": "CREATE TABLE orders (id serial PRIMARY KEY);",
        "query_sql": "SELECT id FROM orders",
        "parameters": {},
        "dataset": {"global_seed": 1, "scale": {}, "epoch": "2026-01-01T00:00:00+00:00"},
        "config": {"candidate": {"apply_sql": "SELECT 1", "revert_sql": "SELECT 1"}},
        "evidence": {},
        "plans": {},
        "readme": "# Proof\n",
    }
    defaults.update(overrides)
    write_proof_bundle(directory, **defaults)  # type: ignore[arg-type]


def test_reproduce_bundle_reports_a_tampered_bundle_without_touching_the_database(
    tmp_path: Path,
) -> None:
    _write(tmp_path)
    (tmp_path / "query.sql").write_text("SELECT * FROM orders", encoding="utf-8")
    result = reproduce_bundle(_FAKE_CONN, _FAKE_CREDENTIALS, tmp_path)
    assert result.tampered is True
    assert result.tamper_problems != ()
    assert result.reproduced is False


def test_reproduce_bundle_reports_an_incompatible_schema_version_without_touching_the_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pgproof.adapters.proof.reproduce as reproduce_module

    _write(tmp_path)
    monkeypatch.setattr(reproduce_module, "is_compatible", lambda _version: False)
    result = reproduce_bundle(_FAKE_CONN, _FAKE_CREDENTIALS, tmp_path)
    assert result.tampered is False
    assert result.schema_version_compatible is False
    assert result.reproduced is False


def test_reproduce_bundle_reports_unrecoverable_parameters_without_touching_the_database(
    tmp_path: Path,
) -> None:
    _write(tmp_path, parameters={"user_id": {"is_redacted": True}})
    result = reproduce_bundle(_FAKE_CONN, _FAKE_CREDENTIALS, tmp_path)
    assert result.tampered is False
    assert result.schema_version_compatible is True
    assert result.parameters_available is False
    assert result.reproduced is False
