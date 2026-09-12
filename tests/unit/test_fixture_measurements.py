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
    EXPECTED_RUNS,
    SAMPLES,
    WARMUPS,
    Provenance,
    build_summary,
    check,
    compare_nplus1,
    extract_generated_block,
    iqr_fraction,
    load_nplus1,
    load_provenance,
    load_runs,
    load_runs_safely,
    median_us,
    render_tables,
    run_statistics,
    validate_nplus1_evidence,
    validate_provenance,
    validate_run,
    validate_run_files,
    validate_run_inventory,
    validate_session_consistency,
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
def test_raw_runs_are_exactly_the_expected_inventory(runs: list[dict[str, Any]]) -> None:
    assert EXPECTED_RUNS == {"IDX-001": (1, 2, 3), "IDX-002": (1, 2, 3)}
    assert [(run["case_id"], run["run"]) for run in runs] == [
        ("IDX-001", 1),
        ("IDX-001", 2),
        ("IDX-001", 3),
        ("IDX-002", 1),
        ("IDX-002", 2),
        ("IDX-002", 3),
    ]
    assert validate_run_inventory(runs) == []
    assert validate_run_files(MEASUREMENTS) == []


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


def stage(tmp_path: Path, skip: str | None = None) -> Path:
    """Copy the committed evidence so a mutation can be applied to it."""
    staged = tmp_path / "measurements"
    staged.mkdir(exist_ok=True)
    for path in MEASUREMENTS.rglob("*"):
        target = staged / path.relative_to(MEASUREMENTS)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.name != skip:
            target.write_bytes(path.read_bytes())
    return staged


def test_staged_copy_is_clean_before_mutation(tmp_path: Path, provenance: Provenance) -> None:
    assert check(stage(tmp_path), NOTES, provenance) == []


def test_disagreeing_summary_is_detected(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path)
    summary = json.loads((staged / "summary.json").read_text())
    summary["cases"]["IDX-001"]["ratio_range"] = [1.0, 1.0]
    (staged / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    assert any("summary.json disagrees" in problem for problem in check(staged, NOTES, provenance))


def test_missing_plan_evidence_is_detected(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path, skip="plan-b.json")
    assert any(
        "missing plan evidence plan-b.json" in problem
        for problem in check(staged, NOTES, provenance)
    )


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


# --------------------------------------------------------------------------- #
# Inventory: no run may be quietly dropped or renamed
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def provenance() -> Provenance:
    loaded, problems = load_provenance(MEASUREMENTS)
    assert problems == []
    assert loaded is not None
    return loaded


@pytest.mark.parametrize(("case", "run"), [(c, r) for c, rs in EXPECTED_RUNS.items() for r in rs])
def test_deleting_one_run_is_rejected(
    tmp_path: Path, provenance: Provenance, case: str, run: int
) -> None:
    staged = stage(tmp_path)
    (staged / case.lower() / f"run-{run}.json").unlink()
    problems = check(staged, NOTES, provenance)
    assert any(f"{case} run {run}" in problem and "missing" in problem for problem in problems)


def test_renaming_one_run_is_rejected(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path)
    source = staged / "idx-001" / "run-3.json"
    source.rename(staged / "idx-001" / "run-9.json")
    problems = check(staged, NOTES, provenance)
    assert any("run 3" in problem and "missing" in problem for problem in problems)
    assert any("unexpected run file" in problem for problem in problems)


def test_renaming_with_a_rewritten_identifier_is_still_rejected(
    tmp_path: Path, provenance: Provenance
) -> None:
    staged = stage(tmp_path)
    source = staged / "idx-001" / "run-3.json"
    document = json.loads(source.read_text())
    document["run"] = 9
    (staged / "idx-001" / "run-9.json").write_text(json.dumps(document, indent=2) + "\n")
    source.unlink()
    problems = check(staged, NOTES, provenance)
    assert any("IDX-001 run 3" in problem and "missing" in problem for problem in problems)
    assert any("unexpected run 9" in problem for problem in problems)


def test_duplicating_a_run_identifier_is_rejected(runs: list[dict[str, Any]]) -> None:
    duplicated = [*runs, copy.deepcopy(runs[0])]
    assert any("appears 2 times" in problem for problem in validate_run_inventory(duplicated))


def test_an_extra_case_is_rejected(runs: list[dict[str, Any]]) -> None:
    extra = copy.deepcopy(runs[0])
    extra["case_id"] = "IDX-999"
    assert any("unexpected case IDX-999" in p for p in validate_run_inventory([*runs, extra]))


def test_a_run_file_contradicting_its_path_is_rejected(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    target = staged / "idx-001" / "run-2.json"
    document = json.loads(target.read_text())
    document["run"] = 3
    target.write_text(json.dumps(document, indent=2) + "\n")
    assert any("does not match its path" in problem for problem in validate_run_files(staged))


# --------------------------------------------------------------------------- #
# Provenance consistency
# --------------------------------------------------------------------------- #
def test_every_committed_run_agrees_with_every_declared_source(
    runs: list[dict[str, Any]], provenance: Provenance
) -> None:
    for run in runs:
        assert validate_provenance(run, provenance) == [], run["case_id"]


def test_declared_sources_are_the_committed_ones(provenance: Provenance) -> None:
    corpus = yaml.safe_load((REPO / "fixtures" / "benchmark-corpus.yaml").read_text())
    assert provenance.postgres_digest == corpus["runtime"]["postgres_digest"]
    assert provenance.server_version == str(corpus["runtime"]["postgres_server_version"])
    assert (
        provenance.python_version
        == (REPO / "fixtures" / "demo-broken" / ".python-version").read_text().strip()
    )
    assert set(provenance.client_versions) == {"sqlalchemy", "alembic", "psycopg", "pytest"}
    assert set(provenance.cases) == set(EXPECTED_RUNS)


@pytest.mark.parametrize(
    ("path", "value", "expected"),
    [
        (("server", "image_digest"), "sha256:0000", "image digest"),
        (("server", "version"), "16.1", "server version"),
        (("client", "sqlalchemy"), "2.0.0", "sqlalchemy 2.0.0 is not the locked"),
        (("client", "alembic"), "1.0.0", "alembic 1.0.0 is not the locked"),
        (("client", "psycopg"), "3.0.0", "psycopg 3.0.0 is not the locked"),
        (("client", "pytest"), "8.0.0", "pytest 8.0.0 is not the locked"),
        (("client", "python"), "3.11.9", "does not match .python-version"),
        (("index", "name"), "ix_wrong", "is not the declared"),
        (("index", "ddl"), "CREATE INDEX ix_wrong ON orders (id)", "index DDL differs"),
    ],
)
def test_provenance_mismatches_are_rejected(
    runs: list[dict[str, Any]],
    provenance: Provenance,
    path: tuple[str, str],
    value: str,
    expected: str,
) -> None:
    run = copy.deepcopy(runs[0])
    run[path[0]][path[1]] = value
    assert any(expected in problem for problem in validate_provenance(run, provenance))


def test_dataset_mismatch_is_rejected(runs: list[dict[str, Any]], provenance: Provenance) -> None:
    run = copy.deepcopy(runs[0])
    run["dataset"]["total_cents_checksum"] = 1
    assert any("is not the declared dataset" in p for p in validate_provenance(run, provenance))
    run = copy.deepcopy(runs[0])
    run["dataset"]["orders"] = 1000
    assert any("is not the declared dataset" in p for p in validate_provenance(run, provenance))


def test_session_setting_mismatch_is_rejected(
    runs: list[dict[str, Any]], provenance: Provenance
) -> None:
    run = copy.deepcopy(runs[0])
    run["session_settings"] = ["SET jit = on"]
    assert any("session settings differ" in p for p in validate_provenance(run, provenance))


def test_query_mismatch_is_rejected(runs: list[dict[str, Any]], provenance: Provenance) -> None:
    run = copy.deepcopy(runs[0])
    run["query"]["sql"] = "SELECT 1"
    assert any("measured SQL differs" in p for p in validate_provenance(run, provenance))
    run = copy.deepcopy(runs[0])
    run["query"]["params"] = [999]
    assert any("measured parameters differ" in p for p in validate_provenance(run, provenance))


def test_unknown_case_has_no_declaration(
    runs: list[dict[str, Any]], provenance: Provenance
) -> None:
    run = copy.deepcopy(runs[0])
    run["case_id"] = "IDX-999"
    assert any("no matching entry in cases.json" in p for p in validate_provenance(run, provenance))


def test_runs_in_one_session_share_an_environment(runs: list[dict[str, Any]]) -> None:
    assert validate_session_consistency(runs) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", {"os": "Linux", "architecture": "x86_64"}),
        ("client", {"python": "3.13.5"}),
        ("server", {"version": "16.1", "image_digest": "sha256:0000"}),
        ("recorded_at", "2020-01-01T00:00:00Z"),
        ("session_settings", ["SET jit = on"]),
    ],
)
def test_mixed_session_environments_are_rejected(
    runs: list[dict[str, Any]], field: str, value: object
) -> None:
    mixed = copy.deepcopy(runs)
    mixed[0][field] = value
    assert any(f"runs disagree on {field}" in p for p in validate_session_consistency(mixed))


def test_missing_provenance_source_is_reported(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    loaded, problems = load_provenance(staged)
    assert loaded is None
    assert any("provenance source missing" in problem for problem in problems)


def test_check_reports_missing_provenance_rather_than_crashing(tmp_path: Path) -> None:
    problems = check(stage(tmp_path), NOTES)
    assert any("provenance source missing" in problem for problem in problems)


# --------------------------------------------------------------------------- #
# Failure safety: malformed evidence must name a problem, never raise
# --------------------------------------------------------------------------- #
def test_empty_sample_arrays_do_not_raise(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path)
    target = staged / "idx-001" / "run-1.json"
    document = json.loads(target.read_text())
    for arm in ARMS:
        document["arms"][arm]["samples"] = []
    target.write_text(json.dumps(document, indent=2) + "\n")
    problems = check(staged, NOTES, provenance)
    assert any("samples count is 0" in problem for problem in problems)
    assert not any("Traceback" in problem for problem in problems)


def test_absent_arms_field_does_not_raise(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path)
    target = staged / "idx-002" / "run-2.json"
    document = json.loads(target.read_text())
    del document["arms"]
    target.write_text(json.dumps(document, indent=2) + "\n")
    problems = check(staged, NOTES, provenance)
    assert any("missing required field 'arms'" in problem for problem in problems)


def test_absent_case_id_does_not_raise(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    target = staged / "idx-001" / "run-1.json"
    document = json.loads(target.read_text())
    del document["case_id"]
    target.write_text(json.dumps(document, indent=2) + "\n")
    loaded, problems = load_runs_safely(staged)
    assert any("missing required field 'case_id'" in problem for problem in problems)
    assert len(loaded) == 5


def test_malformed_json_does_not_raise(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path)
    (staged / "idx-001" / "run-1.json").write_text("{not json")
    problems = check(staged, NOTES, provenance)
    assert any("malformed JSON" in problem or "unreadable" in problem for problem in problems)


def test_a_run_that_is_not_an_object_does_not_raise(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    (staged / "idx-002" / "run-1.json").write_text("[1, 2, 3]")
    _, problems = load_runs_safely(staged)
    assert any("expected a JSON object" in problem for problem in problems)


def test_statistics_are_never_computed_on_malformed_evidence(
    tmp_path: Path, provenance: Provenance
) -> None:
    staged = stage(tmp_path)
    target = staged / "idx-001" / "run-1.json"
    document = json.loads(target.read_text())
    document["arms"]["control_a1"]["samples"] = [1, 2]
    target.write_text(json.dumps(document, indent=2) + "\n")
    problems = check(staged, NOTES, provenance)
    # Structural failure short-circuits, so no summary comparison is attempted.
    assert any("samples count is 2" in problem for problem in problems)
    assert not any("summary.json disagrees" in problem for problem in problems)


# --------------------------------------------------------------------------- #
# N+1 evidence validation
# --------------------------------------------------------------------------- #
def test_committed_nplus1_evidence_validates() -> None:
    assert validate_nplus1_evidence(MEASUREMENTS) == []


def test_missing_nplus1_evidence_is_rejected(tmp_path: Path, provenance: Provenance) -> None:
    staged = stage(tmp_path, skip="evidence.json")
    assert any("evidence.json is missing" in p for p in validate_nplus1_evidence(staged))
    assert any("evidence.json is missing" in p for p in check(staged, NOTES, provenance))


def test_malformed_nplus1_evidence_is_rejected(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    (staged / "nplus1-001" / "evidence.json").write_text("{broken")
    assert any("unreadable or malformed" in p for p in validate_nplus1_evidence(staged))


def test_nplus1_evidence_without_fixtures_is_rejected(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    (staged / "nplus1-001" / "evidence.json").write_text(json.dumps({"case_id": "NPLUS1-001"}))
    assert any("malformed 'fixtures'" in p for p in validate_nplus1_evidence(staged))


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        ({"select_statements": 7}, "not 1+N"),
        ({"totals_checksum": 5}, "checksums differ"),
        ({"order_ids": [1]}, "records 1 order ids"),
    ],
)
def test_invalid_nplus1_results_are_rejected(
    tmp_path: Path, mutate: dict[str, Any], expected: str
) -> None:
    staged = stage(tmp_path)
    path = staged / "nplus1-001" / "evidence.json"
    evidence = json.loads(path.read_text())
    evidence["fixtures"]["demo-broken"].update(mutate)
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    assert any(expected in problem for problem in validate_nplus1_evidence(staged))


def test_nplus1_evidence_missing_a_field_is_rejected(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    path = staged / "nplus1-001" / "evidence.json"
    evidence = json.loads(path.read_text())
    del evidence["fixtures"]["demo-clean"]["totals_checksum"]
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    assert any("is missing 'totals_checksum'" in p for p in validate_nplus1_evidence(staged))


def test_nplus1_evidence_with_a_false_flag_is_rejected(tmp_path: Path) -> None:
    staged = stage(tmp_path)
    path = staged / "nplus1-001" / "evidence.json"
    evidence = json.loads(path.read_text())
    evidence["order_ids_identical"] = False
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    assert any("order_ids_identical is not true" in p for p in validate_nplus1_evidence(staged))


# --------------------------------------------------------------------------- #
# Wording must not outrun the evidence
# --------------------------------------------------------------------------- #
def test_nplus1_wording_is_scoped_to_the_measured_operation() -> None:
    block = extract_generated_block(NOTES)
    evidence = load_nplus1(MEASUREMENTS)
    clean = evidence["fixtures"]["demo-clean"]
    assert (
        f"demo-clean issues {clean['select_statements']} statements for this operation "
        f"returning {clean['orders_returned']} orders." in block
    )
    assert "regardless of row count" not in block
    assert "regardless of" not in block
