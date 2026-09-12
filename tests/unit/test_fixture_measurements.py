"""Contract for the committed raw measurement evidence and the fixture CI job.

Every statistic published in MEASUREMENT.md must be recomputable from files in
the repository. These tests fail when it is not.
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from fixture_measurements import (  # noqa: E402
    ARMS,
    SAMPLES,
    WARMUPS,
    build_summary,
    check,
    compare_nplus1,
    extract_generated_block,
    iqr_fraction,
    load_nplus1,
    load_runs,
    median_us,
    render_tables,
    run_statistics,
    validate_run,
)

MEASUREMENTS = REPO / "fixtures" / "demo-broken" / "measurements"
NOTES = REPO / "fixtures" / "demo-broken" / "MEASUREMENT.md"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
CASES = ("IDX-001", "IDX-002")


@pytest.fixture(scope="module")
def runs() -> list[dict[str, Any]]:
    return load_runs(MEASUREMENTS)


# --------------------------------------------------------------------------- #
# Raw evidence exists and is complete
# --------------------------------------------------------------------------- #
def test_raw_runs_are_committed(runs: list[dict[str, Any]]) -> None:
    assert runs
    assert {run["case_id"] for run in runs} == set(CASES)


def test_every_run_retains_seven_samples_and_three_warmups(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        for arm in ARMS:
            assert len(run["arms"][arm]["samples"]) == SAMPLES, f"{run['case_id']} {arm}"
            assert len(run["arms"][arm]["warmups"]) == WARMUPS, f"{run['case_id']} {arm}"


def test_every_run_passes_structural_validation(runs: list[dict[str, Any]]) -> None:
    problems = [problem for run in runs for problem in validate_run(run)]
    assert problems == []


def test_every_run_records_its_provenance(runs: list[dict[str, Any]]) -> None:
    for run in runs:
        assert run["units"] == "microseconds"
        assert run["server"]["image_digest"].startswith("sha256:")
        assert run["dataset"]["total_cents_checksum"] > 0
        assert run["recorded_at"].endswith("Z")
        assert run["host"]["architecture"]
        assert set(run["client"]) >= {"python", "sqlalchemy", "alembic", "psycopg", "pytest"}
        assert run["session_settings"]
        assert set(run["formulas"]) >= {"median", "iqr_fraction", "drift_fraction", "ratio"}


def test_raw_evidence_carries_no_secret_or_machine_identifier() -> None:
    paths = sorted(MEASUREMENTS.rglob("*.json"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path
        assert "/home/" not in text, path
        document = json.loads(text)
        # cases.json is a list; only run and evidence documents carry a host block.
        if isinstance(document, dict):
            assert "node" not in document.get("host", {}), path
            assert "hostname" not in text, path


@pytest.mark.parametrize("case", CASES)
def test_plan_evidence_exists_with_timing_disabled(case: str) -> None:
    for arm in ("plan-a1.json", "plan-b.json"):
        path = MEASUREMENTS / case.lower() / arm
        assert path.is_file(), f"{case} missing {arm}"
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert plan["timing_enabled"] is False
        assert "TIMING OFF" in plan["explain_options"]
        assert plan["normalized_shape"]
        assert plan["explain"]


def test_treatment_plans_use_the_proposed_index() -> None:
    for case, index in (
        ("IDX-001", "ix_orders_user_id"),
        ("IDX-002", "ix_orders_tenant_status_created"),
    ):
        control = json.loads((MEASUREMENTS / case.lower() / "plan-a1.json").read_text())
        treatment = json.loads((MEASUREMENTS / case.lower() / "plan-b.json").read_text())
        assert "Seq Scan" in control["normalized_shape"], case
        assert index in treatment["normalized_shape"], case
        assert index not in control["normalized_shape"], case


# --------------------------------------------------------------------------- #
# Statistics agree with the raw samples
# --------------------------------------------------------------------------- #
def test_statistics_match_the_committed_summary_and_notes() -> None:
    assert check(MEASUREMENTS, NOTES) == []


def test_summary_is_exactly_what_the_raw_runs_derive() -> None:
    committed = json.loads((MEASUREMENTS / "summary.json").read_text(encoding="utf-8"))
    assert committed == build_summary(MEASUREMENTS)


def test_generated_block_is_current() -> None:
    assert extract_generated_block(NOTES) == render_tables(MEASUREMENTS)


def test_formulas_are_the_ones_documented() -> None:
    samples = [10, 20, 30, 40, 50, 60, 70]
    assert median_us(samples) == 40.0
    # (s[5] - s[1]) / median == (60 - 20) / 40
    assert iqr_fraction(samples) == 1.0
    with pytest.raises(ValueError, match="expects 7 samples"):
        iqr_fraction([1, 2, 3])


def test_run_statistics_are_recomputable_by_hand(runs: list[dict[str, Any]]) -> None:
    run = runs[0]
    derived = run_statistics(run)
    a1 = sorted(run["arms"]["control_a1"]["samples"])
    b = sorted(run["arms"]["treatment_b"]["samples"])
    a2 = sorted(run["arms"]["drift_control_a2"]["samples"])
    assert derived["arms"]["control_a1"]["median_us"] == a1[3]
    assert derived["absolute_saving_us"] == a1[3] - b[3]
    assert derived["ratio"] == a1[3] / b[3]
    assert derived["drift_fraction"] == abs(a2[3] - a1[3]) / a1[3]


# --------------------------------------------------------------------------- #
# Detection: each guard must fail on a violation
# --------------------------------------------------------------------------- #
def _mutated(runs: list[dict[str, Any]], **changes: object) -> dict[str, Any]:
    run = copy.deepcopy(runs[0])
    run.update(changes)
    return run


def test_missing_sample_is_rejected(runs: list[dict[str, Any]]) -> None:
    run = copy.deepcopy(runs[0])
    run["arms"]["control_a1"]["samples"] = run["arms"]["control_a1"]["samples"][:-1]
    assert any("samples count is 6" in problem for problem in validate_run(run))


def test_missing_warmup_is_rejected(runs: list[dict[str, Any]]) -> None:
    run = copy.deepcopy(runs[0])
    run["arms"]["treatment_b"]["warmups"] = []
    assert any("warmups count is 0" in problem for problem in validate_run(run))


def test_declared_protocol_must_match_the_constants(runs: list[dict[str, Any]]) -> None:
    run = _mutated(runs, protocol={"warmups": 1, "samples": 5})
    problems = validate_run(run)
    assert any("declared warmups" in problem for problem in problems)
    assert any("declared samples" in problem for problem in problems)


def test_non_microsecond_units_are_rejected(runs: list[dict[str, Any]]) -> None:
    assert any("units must be microseconds" in p for p in validate_run(_mutated(runs, units="ms")))


def test_missing_arm_is_rejected(runs: list[dict[str, Any]]) -> None:
    run = copy.deepcopy(runs[0])
    del run["arms"]["drift_control_a2"]
    assert any("missing arm drift_control_a2" in problem for problem in validate_run(run))


def test_disagreeing_summary_is_detected(tmp_path: Path) -> None:
    staged = tmp_path / "measurements"
    staged.mkdir()
    for path in MEASUREMENTS.rglob("*"):
        target = staged / path.relative_to(MEASUREMENTS)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            target.write_bytes(path.read_bytes())
    summary = json.loads((staged / "summary.json").read_text())
    summary["cases"]["IDX-001"]["ratio_range"] = [1.0, 1.0]
    (staged / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    assert any("summary.json disagrees" in problem for problem in check(staged, NOTES))


def test_missing_plan_evidence_is_detected(tmp_path: Path) -> None:
    staged = tmp_path / "measurements"
    for path in MEASUREMENTS.rglob("*"):
        target = staged / path.relative_to(MEASUREMENTS)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.name != "plan-b.json":
            target.write_bytes(path.read_bytes())
    assert any("missing plan evidence plan-b.json" in problem for problem in check(staged, NOTES))


def test_stale_generated_block_is_detected(tmp_path: Path) -> None:
    stale = tmp_path / "MEASUREMENT.md"
    stale.write_text(
        NOTES.read_text(encoding="utf-8").replace("| 1 | 9", "| 1 | 1"), encoding="utf-8"
    )
    assert any("generated block disagrees" in problem for problem in check(MEASUREMENTS, stale))


# --------------------------------------------------------------------------- #
# N+1 evidence
# --------------------------------------------------------------------------- #
def test_nplus1_evidence_is_one_plus_n_and_equivalent() -> None:
    evidence = load_nplus1(MEASUREMENTS)
    broken = evidence["fixtures"]["demo-broken"]
    clean = evidence["fixtures"]["demo-clean"]
    assert broken["select_statements"] == 1 + broken["orders_returned"]
    assert clean["select_statements"] == 2
    assert broken["order_ids"] == clean["order_ids"]
    assert broken["totals_checksum"] == clean["totals_checksum"]
    assert evidence["broken_is_one_plus_n"] is True
    assert evidence["order_ids_identical"] is True
    assert evidence["checksums_identical"] is True
    assert compare_nplus1(broken, clean, 2) == []


def test_nplus1_evidence_records_every_returned_order_id() -> None:
    evidence = load_nplus1(MEASUREMENTS)
    for name in ("demo-broken", "demo-clean"):
        entry = evidence["fixtures"][name]
        assert len(entry["order_ids"]) == entry["orders_returned"]


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"select_statements": 5}, "not 1+N"),
        ({"orders_returned": 0, "select_statements": 1, "order_ids": []}, "no orders"),
        ({"totals_checksum": 1}, "checksums differ"),
        ({"order_ids": [1, 2, 3]}, "order ids differ"),
    ],
)
def test_nplus1_comparison_rejects_violations(mutation: dict[str, Any], expected: str) -> None:
    evidence = load_nplus1(MEASUREMENTS)
    broken = dict(evidence["fixtures"]["demo-broken"])
    clean = dict(evidence["fixtures"]["demo-clean"])
    broken.update(mutation)
    assert any(expected in problem for problem in compare_nplus1(broken, clean, 2))


def test_nplus1_comparison_rejects_a_clean_fixture_that_regressed() -> None:
    evidence = load_nplus1(MEASUREMENTS)
    broken = evidence["fixtures"]["demo-broken"]
    clean = dict(evidence["fixtures"]["demo-clean"])
    clean["select_statements"] = 21
    assert any("not a fixed count" in problem for problem in compare_nplus1(broken, clean, 2))


# --------------------------------------------------------------------------- #
# Notes must not reintroduce unsupported wording
# --------------------------------------------------------------------------- #
def test_notes_state_the_measured_ratio_rather_than_a_vague_magnitude() -> None:
    text = NOTES.read_text(encoding="utf-8")
    assert "orders of magnitude" not in text
    assert "order of magnitude" not in text
    summary = build_summary(MEASUREMENTS)
    for case in CASES:
        low, high = summary["cases"][case]["ratio_range"]
        assert f"{low:.1f}x" in text, f"{case} low ratio absent from the notes"
        assert f"{high:.1f}x" in text, f"{case} high ratio absent from the notes"


def test_notes_make_no_production_performance_prediction() -> None:
    text = NOTES.read_text(encoding="utf-8").lower()
    for phrase in ("in production", "production latency", "will improve", "expected speedup"):
        assert phrase not in text, phrase


# --------------------------------------------------------------------------- #
# Fixture CI job
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return document


def test_fixture_integration_job_exists(workflow: dict[str, Any]) -> None:
    assert "fixtures" in workflow["jobs"], "the fixture integration job disappeared"
    assert workflow["jobs"]["fixtures"]["runs-on"] == "ubuntu-latest"


def test_fixture_job_pins_postgres_by_digest(workflow: dict[str, Any]) -> None:
    image = workflow["jobs"]["fixtures"]["services"]["postgres"]["image"]
    corpus = yaml.safe_load((REPO / "fixtures" / "benchmark-corpus.yaml").read_text())
    assert image == corpus["runtime"]["postgres_image"]
    assert "@sha256:" in image


def test_fixture_job_covers_both_fixtures_and_every_assertion(workflow: dict[str, Any]) -> None:
    steps = workflow["jobs"]["fixtures"]["steps"]
    script = "\n".join(step.get("run", "") for step in steps)
    for required in (
        "demo_broken",
        "demo_clean",
        "uv sync --all-groups --frozen",
        "alembic upgrade head",
        "uv run --frozen pytest",
        "fk_orders_tenant_id",
        "ix_orders_user_id",
        "ix_orders_tenant_status_created",
        "compare-nplus1",
    ):
        assert required in script, f"fixture job no longer covers {required}"


def test_fixture_job_keeps_the_benchmark_dataset_out_of_ci(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["fixtures"]
    assert job["env"]["FIXTURE_DATASET"] == "dataset-small.sql"
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "dataset.sql" not in script.replace("dataset-small.sql", "")
    assert "fixture_measurements.py collect" not in script


def test_fixture_job_always_cleans_up(workflow: dict[str, Any]) -> None:
    cleanup = workflow["jobs"]["fixtures"]["steps"][-1]
    assert cleanup["name"] == "Clean up"
    assert cleanup["if"] == "always()"
    assert "DROP DATABASE IF EXISTS demo_broken" in cleanup["run"]
    assert "DROP DATABASE IF EXISTS demo_clean" in cleanup["run"]
    assert ".venv" in cleanup["run"]
