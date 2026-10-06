"""Reproducing a proof bundle against a live, disposable database.
`docs/TECHNICAL_DESIGN.md` section 26: "reproduction verifies compatible
input/tool versions; artifact hashes; stable measurements; same direction of
effect; configured improvement threshold; compatible normalized plan shape.
It never requires exact milliseconds."

Evidence documents follow a plain convention this module defines itself:
`control-a1.json`/`treatment-b.json`/`control-a2.json` each carry at least a
`median_us` field (`adapters.benchmark.statistics.ArmStatistics`'s own shape,
JSON-dumped by whatever wrote the bundle); `plans/treatment-b.json` carries a
`plan_fingerprint` field (`adapters.benchmark.explain.PlanDiagnostics`'s own
shape). A bundle missing either is not a hash-tamper problem — it is simply
unable to support that one qualitative check, reported as `None`, never
guessed at as pass or fail.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from pgproof.adapters.benchmark.explain import parse_explain
from pgproof.adapters.benchmark.run import CandidateDDL, run_experiment
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.proof.bundle import BundleContents, read_proof_bundle
from pgproof.adapters.seeder.load import load_dataset
from pgproof.domain.identifiers import TableId
from pgproof.domain.versioning import is_compatible
from pgproof.ports.database import GeneratedCredentials


@dataclass(frozen=True)
class ReproductionResult:
    proof_id: str
    tampered: bool
    tamper_problems: tuple[str, ...]
    schema_version_compatible: bool
    # False when `parameters.json`'s descriptors are redacted (the common,
    # privacy-preserving default from BE-20/24) with no `redacted_value` to
    # rebind — reproduction cannot run the query at all without a real value,
    # which is an honest capability gap, not a tamper or version problem.
    parameters_available: bool
    direction_matches: bool | None
    plan_shape_compatible: bool | None
    stable: bool | None
    reproduced: bool


def _failed(
    proof_id: str, *, tampered: bool, tamper_problems: tuple[str, ...]
) -> ReproductionResult:
    return ReproductionResult(
        proof_id=proof_id,
        tampered=tampered,
        tamper_problems=tamper_problems,
        schema_version_compatible=False,
        parameters_available=False,
        direction_matches=None,
        plan_shape_compatible=None,
        stable=None,
        reproduced=False,
    )


def _median_us(evidence: Mapping[str, object], key: str) -> float | None:
    arm = evidence.get(key)
    if not isinstance(arm, Mapping):
        return None
    value = arm.get("median_us")
    return float(value) if isinstance(value, int | float) else None


def _original_direction(evidence: Mapping[str, object]) -> bool | None:
    control = _median_us(evidence, "control-a1")
    treatment = _median_us(evidence, "treatment-b")
    if control is None or treatment is None or treatment == 0:
        return None
    return control / treatment > 1.0


def _recorded_plan_fingerprint(plans: Mapping[str, object]) -> str | None:
    document = plans.get("treatment-b")
    if not isinstance(document, Mapping):
        return None
    fingerprint = document.get("plan_fingerprint")
    return fingerprint if isinstance(fingerprint, str) else None


def _bind_parameters(parameters: Mapping[str, object]) -> dict[str, object] | None:
    """Real bind values from `parameters.json`'s descriptors, or `None` if
    any one of them is redacted with no `redacted_value` to recover — the
    same shape `adapters.parameters.probe.ParameterProbe` already uses.
    """
    resolved: dict[str, object] = {}
    for name, descriptor in parameters.items():
        if not isinstance(descriptor, Mapping) or descriptor.get("is_redacted", True):
            return None
        if "redacted_value" not in descriptor:
            return None
        resolved[name] = descriptor["redacted_value"]
    return resolved


def _apply_dataset(
    conn: psycopg.Connection[tuple[object, ...]],
    contents: BundleContents,
    credentials: GeneratedCredentials,
) -> None:
    with conn.cursor() as cur:
        cur.execute(contents.schema_sql)
    conn.commit()
    schema = PsycopgCatalogReader().introspect(credentials)
    dataset = contents.dataset
    if not isinstance(dataset, Mapping):
        raise ValueError("dataset.yaml must be a mapping")
    scale: dict[TableId, int] = dict(dataset.get("scale", {}))
    epoch = datetime.fromisoformat(str(dataset["epoch"]))
    load_dataset(conn, schema, global_seed=int(dataset["global_seed"]), scale=scale, epoch=epoch)


def reproduce_bundle(
    conn: psycopg.Connection[tuple[object, ...]],
    credentials: GeneratedCredentials,
    directory: Path,
) -> ReproductionResult:
    """Re-applies the bundle's declared schema and dataset to `conn` (expected
    to be a fresh, empty disposable database — this function never drops or
    truncates anything itself), re-runs the declared query/candidate, and
    compares the new measurement's direction and plan shape against what the
    bundle recorded.
    """
    contents, tamper_problems = read_proof_bundle(directory)
    if contents is None:
        return _failed(directory.name, tampered=True, tamper_problems=tamper_problems)

    schema_ok = is_compatible(contents.manifest.schema_version)
    if not schema_ok:
        return ReproductionResult(
            proof_id=contents.manifest.proof_id,
            tampered=False,
            tamper_problems=(),
            schema_version_compatible=False,
            parameters_available=False,
            direction_matches=None,
            plan_shape_compatible=None,
            stable=None,
            reproduced=False,
        )

    raw_parameters = contents.parameters if isinstance(contents.parameters, Mapping) else {}
    bound_parameters = _bind_parameters(raw_parameters)
    if bound_parameters is None:
        return ReproductionResult(
            proof_id=contents.manifest.proof_id,
            tampered=False,
            tamper_problems=(),
            schema_version_compatible=True,
            parameters_available=False,
            direction_matches=None,
            plan_shape_compatible=None,
            stable=None,
            reproduced=False,
        )

    _apply_dataset(conn, contents, credentials)

    config = contents.config
    if not isinstance(config, Mapping):
        raise ValueError("config.yaml must be a mapping")
    candidate_config: Mapping[str, Any] = config.get("candidate", {})
    candidate = CandidateDDL(
        apply_sql=candidate_config.get("apply_sql", "SELECT 1"),
        revert_sql=candidate_config.get("revert_sql", "SELECT 1"),
    )
    postgres_settings: Mapping[str, str] = config.get("postgres_settings", {})

    new_result = run_experiment(
        conn,
        contents.query_sql,
        bound_parameters,
        candidate=candidate,
        postgres_settings=postgres_settings,
    )

    new_ratio_positive = new_result.ratio is not None and new_result.ratio > 1.0
    original_positive = _original_direction(contents.evidence)
    direction_matches = (
        None if original_positive is None else original_positive == new_ratio_positive
    )

    recorded_fingerprint = _recorded_plan_fingerprint(contents.plans)
    plan_shape_compatible: bool | None = None
    if recorded_fingerprint is not None and new_result.explain_b is not None:
        new_fingerprint = parse_explain(new_result.explain_b).plan_fingerprint
        plan_shape_compatible = new_fingerprint == recorded_fingerprint

    stable = not new_result.inconclusive
    reproduced = direction_matches is True and stable and plan_shape_compatible is not False

    return ReproductionResult(
        proof_id=contents.manifest.proof_id,
        tampered=False,
        tamper_problems=(),
        schema_version_compatible=True,
        parameters_available=True,
        direction_matches=direction_matches,
        plan_shape_compatible=plan_shape_compatible,
        stable=stable,
        reproduced=reproduced,
    )
