"""Fixture measurement tooling: collect raw evidence, derive summaries, verify agreement.

This is fixture tooling, not pgproof product functionality. It defines no domain
model and writes no pgproof artifact. Only `collect` and `nplus1` touch a
database, and they import their drivers lazily so the pure functions below stay
importable with the standard library alone.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WARMUPS = 3
SAMPLES = 7

FORMULAS = {
    "median": "sorted(samples)[len(samples) // 2], which is index 3 of 7",
    "iqr_fraction": "(sorted(samples)[5] - sorted(samples)[1]) / median",
    "drift_fraction": "abs(median_a2 - median_a1) / median_a1",
    "absolute_saving": "median_a1 - median_b",
    "ratio": "median_a1 / median_b",
    "units": "every raw sample is an integer count of microseconds",
}

ARMS = ("control_a1", "treatment_b", "drift_control_a2")

# Exact inventory. Accepting "any non-empty set" would let a noisy run be deleted
# and the remaining ones re-summarised without the omission being visible.
EXPECTED_RUNS: dict[str, tuple[int, ...]] = {"IDX-001": (1, 2, 3), "IDX-002": (1, 2, 3)}

PINNED_CLIENTS = ("sqlalchemy", "alembic", "psycopg", "pytest")

GENERATED_BEGIN = "<!-- generated-from-raw-evidence:begin -->"
GENERATED_END = "<!-- generated-from-raw-evidence:end -->"


# --------------------------------------------------------------------------- #
# Pure statistics over raw samples
# --------------------------------------------------------------------------- #
def median_us(samples: Sequence[int]) -> float:
    ordered = sorted(samples)
    return float(ordered[len(ordered) // 2])


def iqr_fraction(samples: Sequence[int]) -> float:
    ordered = sorted(samples)
    if len(ordered) != SAMPLES:
        raise ValueError(f"iqr_fraction expects {SAMPLES} samples, got {len(ordered)}")
    return (ordered[5] - ordered[1]) / median_us(ordered)


def arm_statistics(samples: Sequence[int]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "median_us": median_us(ordered),
        "min_us": float(ordered[0]),
        "max_us": float(ordered[-1]),
        "q1_us": float(ordered[1]),
        "q3_us": float(ordered[5]),
        "iqr_fraction": iqr_fraction(ordered),
        "mean_us": statistics.fmean(ordered),
    }


def run_statistics(run: dict[str, Any]) -> dict[str, Any]:
    """Derive every reported quantity from one raw run. Deterministic."""
    arms = {name: arm_statistics(run["arms"][name]["samples"]) for name in ARMS}
    a1 = arms["control_a1"]["median_us"]
    b = arms["treatment_b"]["median_us"]
    a2 = arms["drift_control_a2"]["median_us"]
    return {
        "case_id": run["case_id"],
        "run": run["run"],
        "arms": arms,
        "absolute_saving_us": a1 - b,
        "ratio": a1 / b,
        "drift_fraction": abs(a2 - a1) / a1,
    }


def validate_run(run: dict[str, Any]) -> list[str]:
    """Structural problems that make a run unusable as evidence."""
    problems: list[str] = []
    protocol = run.get("protocol", {})
    if protocol.get("warmups") != WARMUPS:
        problems.append(f"{run.get('case_id')} run {run.get('run')}: declared warmups != {WARMUPS}")
    if protocol.get("samples") != SAMPLES:
        problems.append(f"{run.get('case_id')} run {run.get('run')}: declared samples != {SAMPLES}")
    for name in ARMS:
        arm = run.get("arms", {}).get(name)
        if arm is None:
            problems.append(f"{run.get('case_id')} run {run.get('run')}: missing arm {name}")
            continue
        for key, expected in (("warmups", WARMUPS), ("samples", SAMPLES)):
            values = arm.get(key)
            if not isinstance(values, list) or len(values) != expected:
                got = "missing" if values is None else len(values)
                problems.append(
                    f"{run.get('case_id')} run {run.get('run')} {name}: "
                    f"{key} count is {got}, expected {expected}"
                )
                continue
            if not all(isinstance(value, int) and value > 0 for value in values):
                problems.append(
                    f"{run.get('case_id')} run {run.get('run')} {name}: "
                    f"{key} must be positive integer microseconds"
                )
    if run.get("units") != "microseconds":
        problems.append(f"{run.get('case_id')} run {run.get('run')}: units must be microseconds")
    return problems


# --------------------------------------------------------------------------- #
# Loading committed evidence
# --------------------------------------------------------------------------- #
def load_runs(measurements: Path) -> list[dict[str, Any]]:
    runs, _ = load_runs_safely(measurements)
    return runs


def load_runs_safely(measurements: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load run documents without raising on malformed or unreadable evidence."""
    runs: list[dict[str, Any]] = []
    problems: list[str] = []
    for path in sorted(measurements.glob("*/run-*.json")):
        name = str(path.relative_to(measurements))
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{name}: unreadable or malformed JSON ({error})")
            continue
        if not isinstance(document, dict):
            problems.append(f"{name}: expected a JSON object")
            continue
        for required in ("case_id", "run", "arms"):
            if required not in document:
                problems.append(f"{name}: missing required field {required!r}")
                break
        else:
            runs.append(document)
    runs.sort(key=lambda run: (str(run.get("case_id")), int(run.get("run", 0))))
    return runs, problems


def expected_run_path(measurements: Path, case: str, run: int) -> Path:
    return measurements / case.lower() / f"run-{run}.json"


def validate_run_files(measurements: Path) -> list[str]:
    """Every expected run file exists, and its contents match its own path."""
    problems: list[str] = []
    expected_paths: set[Path] = set()
    for case, numbers in EXPECTED_RUNS.items():
        for number in numbers:
            path = expected_run_path(measurements, case, number)
            expected_paths.add(path)
            if not path.is_file():
                problems.append(f"{case} run {number}: {path.name} is missing")
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                problems.append(f"{case} run {number}: unreadable ({error})")
                continue
            if document.get("case_id") != case or document.get("run") != number:
                problems.append(
                    f"{path.name} declares {document.get('case_id')} run "
                    f"{document.get('run')}, which does not match its path"
                )
    for path in sorted(measurements.glob("*/run-*.json")):
        if path not in expected_paths:
            problems.append(f"{path.relative_to(measurements)}: unexpected run file")
    return problems


def validate_run_inventory(runs: Sequence[dict[str, Any]]) -> list[str]:
    """Exactly the expected identifiers, each exactly once."""
    observed: dict[tuple[str, int], int] = {}
    for run in runs:
        key = (str(run.get("case_id")), int(run.get("run", 0)))
        observed[key] = observed.get(key, 0) + 1
    problems: list[str] = []
    for case, numbers in EXPECTED_RUNS.items():
        for number in numbers:
            count = observed.get((case, number), 0)
            if count == 0:
                problems.append(f"{case}: run {number} is missing from the inventory")
            elif count > 1:
                problems.append(f"{case}: run {number} appears {count} times")
    for case, number in sorted(observed):
        if case not in EXPECTED_RUNS:
            problems.append(f"unexpected case {case} in the inventory")
        elif number not in EXPECTED_RUNS[case]:
            problems.append(f"{case}: unexpected run {number} in the inventory")
    return problems


@dataclass(frozen=True)
class Provenance:
    """Declared sources every run is validated against."""

    postgres_digest: str
    server_version: str
    client_versions: dict[str, str]
    python_version: str
    dataset: dict[str, int]
    session_settings: list[str]
    cases: dict[str, dict[str, Any]]


def load_provenance(measurements: Path) -> tuple[Provenance | None, list[str]]:
    """Read the declared sources. yaml is imported lazily: the fixture environment
    that runs `collect` and `nplus1` does not install it."""
    import yaml

    fixture = measurements.parent
    corpus_path = fixture.parent / "benchmark-corpus.yaml"
    lock_path = fixture / "uv.lock"
    python_path = fixture / ".python-version"
    environment_path = measurements / "environment.json"
    cases_path = measurements / "cases.json"

    problems: list[str] = []
    for path in (corpus_path, lock_path, python_path, environment_path, cases_path):
        if not path.is_file():
            problems.append(f"provenance source missing: {path.name}")
    if problems:
        return None, problems

    try:
        corpus = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        environment = json.loads(environment_path.read_text(encoding="utf-8"))
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as error:
        return None, [f"provenance source unreadable: {error}"]

    locked = {package["name"]: package["version"] for package in lock["package"]}
    missing = [name for name in PINNED_CLIENTS if name not in locked]
    if missing:
        return None, [f"lockfile does not pin {', '.join(missing)}"]

    return (
        Provenance(
            postgres_digest=corpus["runtime"]["postgres_digest"],
            server_version=str(corpus["runtime"]["postgres_server_version"]),
            client_versions={name: locked[name] for name in PINNED_CLIENTS},
            python_version=python_path.read_text(encoding="utf-8").strip(),
            dataset=environment["dataset"],
            session_settings=list(environment["session_settings"]),
            cases={case["id"]: case for case in cases},
        ),
        [],
    )


def validate_provenance(run: dict[str, Any], provenance: Provenance) -> list[str]:
    """One run agrees with every declared source."""
    label = f"{run.get('case_id')} run {run.get('run')}"
    problems: list[str] = []

    server = run.get("server", {})
    if server.get("image_digest") != provenance.postgres_digest:
        problems.append(
            f"{label}: image digest {server.get('image_digest')} is not the declared "
            f"{provenance.postgres_digest}"
        )
    if server.get("version") != provenance.server_version:
        problems.append(
            f"{label}: server version {server.get('version')!r} is not the declared "
            f"{provenance.server_version!r}"
        )

    client = run.get("client", {})
    for name, version in provenance.client_versions.items():
        if client.get(name) != version:
            problems.append(f"{label}: {name} {client.get(name)} is not the locked {version}")
    python_version = str(client.get("python", ""))
    if not python_version.startswith(provenance.python_version):
        problems.append(
            f"{label}: python {python_version or 'missing'} does not match "
            f".python-version {provenance.python_version}"
        )

    if run.get("dataset") != provenance.dataset:
        problems.append(f"{label}: dataset {run.get('dataset')} is not the declared dataset")

    if list(run.get("session_settings", [])) != provenance.session_settings:
        problems.append(f"{label}: session settings differ from the declared settings")

    case = provenance.cases.get(str(run.get("case_id")))
    if case is None:
        problems.append(f"{label}: no matching entry in cases.json")
    else:
        query = run.get("query", {})
        index = run.get("index", {})
        if query.get("sql") != case["sql"]:
            problems.append(f"{label}: measured SQL differs from cases.json")
        if list(query.get("params", [])) != list(case["params"]):
            problems.append(f"{label}: measured parameters differ from cases.json")
        if index.get("name") != case["index_name"]:
            problems.append(
                f"{label}: index {index.get('name')} is not the declared {case['index_name']}"
            )
        if index.get("ddl") != case["ddl"]:
            problems.append(f"{label}: index DDL differs from cases.json")
    return problems


def validate_session_consistency(runs: Sequence[dict[str, Any]]) -> list[str]:
    """Every run in one committed session shares an environment."""
    problems: list[str] = []
    for field in ("host", "client", "server", "session_settings", "recorded_at"):
        observed = {json.dumps(run.get(field), sort_keys=True) for run in runs}
        if len(observed) > 1:
            problems.append(
                f"runs disagree on {field}: {len(observed)} distinct values across the session"
            )
    return problems


def validate_nplus1_evidence(measurements: Path) -> list[str]:
    """Presence, shape, the 1+N invariant, and result equivalence."""
    path = measurements / "nplus1-001" / "evidence.json"
    if not path.is_file():
        return ["nplus1-001/evidence.json is missing"]
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"nplus1-001/evidence.json is unreadable or malformed ({error})"]
    if not isinstance(evidence, dict):
        return ["nplus1-001/evidence.json: expected a JSON object"]

    fixtures = evidence.get("fixtures")
    if not isinstance(fixtures, dict):
        return ["nplus1-001/evidence.json: missing or malformed 'fixtures'"]

    problems: list[str] = []
    required = ("orders_returned", "select_statements", "totals_checksum", "order_ids")
    for name in ("demo-broken", "demo-clean"):
        entry = fixtures.get(name)
        if not isinstance(entry, dict):
            problems.append(f"nplus1 evidence: missing or malformed entry for {name}")
            continue
        for field in required:
            if field not in entry:
                problems.append(f"nplus1 evidence: {name} is missing {field!r}")
        ids = entry.get("order_ids")
        if isinstance(ids, list) and entry.get("orders_returned") != len(ids):
            problems.append(
                f"nplus1 evidence: {name} records {len(ids)} order ids for "
                f"{entry.get('orders_returned')} orders"
            )
    if problems:
        return problems

    problems += [
        f"nplus1 evidence: {problem}"
        for problem in compare_nplus1(fixtures["demo-broken"], fixtures["demo-clean"], 2)
    ]
    for flag in ("broken_is_one_plus_n", "order_ids_identical", "checksums_identical"):
        if evidence.get(flag) is not True:
            problems.append(f"nplus1 evidence: {flag} is not true")
    return problems


def load_nplus1(measurements: Path) -> dict[str, Any]:
    path = measurements / "nplus1-001" / "evidence.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def case_ids(runs: Sequence[dict[str, Any]]) -> list[str]:
    return sorted({run["case_id"] for run in runs})


def ratio_range(runs: Sequence[dict[str, Any]]) -> tuple[float, float]:
    ratios = [run_statistics(run)["ratio"] for run in runs]
    return min(ratios), max(ratios)


def saving_range_ms(runs: Sequence[dict[str, Any]]) -> tuple[float, float]:
    savings = [run_statistics(run)["absolute_saving_us"] / 1000 for run in runs]
    return min(savings), max(savings)


# --------------------------------------------------------------------------- #
# Deterministic summary
# --------------------------------------------------------------------------- #
def build_summary(measurements: Path) -> dict[str, Any]:
    runs = load_runs(measurements)
    if not runs:
        raise SystemExit(f"no raw runs under {measurements}")
    per_case: dict[str, Any] = {}
    for case in case_ids(runs):
        case_runs = [run for run in runs if run["case_id"] == case]
        low_ratio, high_ratio = ratio_range(case_runs)
        low_saving, high_saving = saving_range_ms(case_runs)
        per_case[case] = {
            "runs": [run_statistics(run) for run in case_runs],
            "ratio_range": [low_ratio, high_ratio],
            "absolute_saving_ms_range": [low_saving, high_saving],
            "max_control_iqr_fraction": max(
                run_statistics(run)["arms"]["control_a1"]["iqr_fraction"] for run in case_runs
            ),
            "max_drift_fraction": max(run_statistics(run)["drift_fraction"] for run in case_runs),
        }
    return {
        "summary_version": 1,
        "derived_from": "run-*.json under this directory",
        "formulas": FORMULAS,
        "protocol": {"warmups": WARMUPS, "samples": SAMPLES},
        "cases": per_case,
    }


def _fmt_ms(microseconds: float) -> str:
    return f"{microseconds / 1000:.2f}"


def render_tables(measurements: Path) -> str:
    runs = load_runs(measurements)
    lines = [
        GENERATED_BEGIN,
        "",
        "<!-- Regenerate with: uv run python scripts/fixture_measurements.py summarize"
        " --measurements fixtures/demo-broken/measurements --write -->",
        "",
    ]
    for case in case_ids(runs):
        case_runs = [run for run in runs if run["case_id"] == case]
        first = case_runs[0]
        lines += [
            f"#### {case} — {first['index']['name']}",
            "",
            "| Run | A1 median | A1 IQR | B median | A2 median | Drift | Saving | Ratio |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for run in case_runs:
            s = run_statistics(run)
            lines.append(
                f"| {s['run']} "
                f"| {_fmt_ms(s['arms']['control_a1']['median_us'])} ms "
                f"| {s['arms']['control_a1']['iqr_fraction'] * 100:.1f}% "
                f"| {_fmt_ms(s['arms']['treatment_b']['median_us'])} ms "
                f"| {_fmt_ms(s['arms']['drift_control_a2']['median_us'])} ms "
                f"| {s['drift_fraction'] * 100:.2f}% "
                f"| {_fmt_ms(s['absolute_saving_us'])} ms "
                f"| {s['ratio']:.1f}x |"
            )
        low_ratio, high_ratio = ratio_range(case_runs)
        low_saving, high_saving = saving_range_ms(case_runs)
        lines += [
            "",
            f"Saving ranges from {low_saving:.2f} ms to {high_saving:.2f} ms; the control-to-"
            f"treatment ratio ranges from {low_ratio:.1f}x to {high_ratio:.1f}x across "
            f"{len(case_runs)} runs. Index size {first['index']['size_pretty']}.",
            "",
        ]
    nplus1 = load_nplus1(measurements)
    lines += [
        "#### NPLUS1-001 — statement counts and result equivalence",
        "",
        "| Fixture | Orders returned | SELECT statements | Totals checksum |",
        "|---|---|---|---|",
    ]
    for name in ("demo-broken", "demo-clean"):
        entry = nplus1["fixtures"][name]
        lines.append(
            f"| {name} | {entry['orders_returned']} | {entry['select_statements']} "
            f"| {entry['totals_checksum']} |"
        )
    broken = nplus1["fixtures"]["demo-broken"]
    clean = nplus1["fixtures"]["demo-clean"]
    lines += [
        "",
        f"`{broken['select_statements']} = 1 + {broken['orders_returned']}` in demo-broken; "
        f"demo-clean issues {clean['select_statements']} statements for this operation "
        f"returning {clean['orders_returned']} orders. "
        f"Order ids identical: {nplus1['order_ids_identical']}. "
        f"Checksums identical: {nplus1['checksums_identical']}.",
        "",
        GENERATED_END,
    ]
    return "\n".join(lines)


def write_generated_block(notes: Path, block: str) -> None:
    text = notes.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(GENERATED_BEGIN) + r".*?" + re.escape(GENERATED_END), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"{notes} has no generated-from-raw-evidence markers")
    notes.write_text(pattern.sub(lambda _: block, text), encoding="utf-8")


def extract_generated_block(notes: Path) -> str:
    text = notes.read_text(encoding="utf-8")
    match = re.search(
        re.escape(GENERATED_BEGIN) + r".*?" + re.escape(GENERATED_END), text, re.DOTALL
    )
    if match is None:
        raise SystemExit(f"{notes} has no generated-from-raw-evidence markers")
    return match.group(0)


def check(measurements: Path, notes: Path, provenance: Provenance | None = None) -> list[str]:
    """Validate structure, inventory and provenance before computing any statistic.

    Statistics are only compared once the evidence is known to be well formed, so
    malformed input yields a named problem rather than an IndexError or KeyError.
    """
    problems: list[str] = []
    runs, load_problems = load_runs_safely(measurements)
    problems += load_problems
    problems += validate_run_files(measurements)
    problems += validate_run_inventory(runs)
    for run in runs:
        problems += validate_run(run)

    if provenance is None:
        provenance, provenance_problems = load_provenance(measurements)
        problems += provenance_problems
    if provenance is not None:
        for run in runs:
            problems += validate_provenance(run, provenance)
    problems += validate_session_consistency(runs)

    for case in EXPECTED_RUNS:
        case_dir = measurements / case.lower()
        for plan in ("plan-a1.json", "plan-b.json"):
            if not (case_dir / plan).is_file():
                problems.append(f"{case}: missing plan evidence {plan}")
    problems += validate_nplus1_evidence(measurements)

    if problems:
        return problems

    committed = measurements / "summary.json"
    if not committed.is_file():
        problems.append("missing summary.json")
    elif json.loads(committed.read_text(encoding="utf-8")) != build_summary(measurements):
        problems.append("summary.json disagrees with the raw runs")
    if extract_generated_block(notes) != render_tables(measurements):
        problems.append(f"{notes.name} generated block disagrees with the raw runs")
    return problems


# --------------------------------------------------------------------------- #
# Database-touching commands
# --------------------------------------------------------------------------- #
def _environment(dsn: str) -> dict[str, Any]:
    import psycopg

    versions: dict[str, str] = {"python": platform.python_version()}
    for module_name, key in (
        ("sqlalchemy", "sqlalchemy"),
        ("alembic", "alembic"),
        ("psycopg", "psycopg"),
        ("pytest", "pytest"),
    ):
        module = __import__(module_name)
        versions[key] = str(module.__version__)
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SHOW server_version")
        row = cur.fetchone()
        assert row is not None
        server_version = row[0]
    return {
        "client": versions,
        # platform.node() is deliberately not recorded; it is a machine identifier.
        "host": {"os": platform.system(), "architecture": platform.machine()},
        "server_version": server_version,
    }


def _dataset_facts(cur: Any) -> dict[str, int]:  # noqa: ANN401
    cur.execute(
        "SELECT (SELECT count(*) FROM orders), (SELECT count(*) FROM order_items),"
        " (SELECT sum(total_cents) FROM orders)"
    )
    orders, items, checksum = cur.fetchone()
    return {"orders": orders, "order_items": items, "total_cents_checksum": int(checksum)}


def _plan_shape(node: dict[str, Any]) -> str:
    entry = node["Node Type"]
    if node.get("Index Name"):
        entry += f" using {node['Index Name']}"
    elif node.get("Relation Name"):
        entry += f" on {node['Relation Name']}"
    parts = [entry]
    for child in node.get("Plans", []):
        parts.append(_plan_shape(child))
    return " -> ".join(parts)


def collect(args: argparse.Namespace) -> int:
    import time

    import psycopg

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    measurements = Path(args.measurements)
    environment = _environment(args.dsn)

    with psycopg.connect(args.dsn, autocommit=True) as conn, conn.cursor() as cur:
        for setting in args.setting:
            cur.execute(setting)
        dataset = _dataset_facts(cur)

        def timed(sql: str, params: list[Any]) -> tuple[list[int], list[int], int]:
            warmups: list[int] = []
            samples: list[int] = []
            rows = 0
            for index in range(WARMUPS + SAMPLES):
                start = time.perf_counter()
                cur.execute(sql, params)
                fetched = cur.fetchall()
                elapsed = round((time.perf_counter() - start) * 1_000_000)
                (warmups if index < WARMUPS else samples).append(elapsed)
                rows = len(fetched)
            return warmups, samples, rows

        def plan(sql: str, params: list[Any]) -> dict[str, Any]:
            cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON) {sql}", params)
            row = cur.fetchone()
            assert row is not None
            explain = row[0]
            return {
                "explain_options": "ANALYZE, BUFFERS, WAL, TIMING OFF, FORMAT JSON",
                "timing_enabled": False,
                "normalized_shape": _plan_shape(explain[0]["Plan"]),
                "explain": explain,
            }

        for case in cases:
            case_dir = measurements / case["id"].lower()
            case_dir.mkdir(parents=True, exist_ok=True)
            for run_number in range(1, args.runs + 1):
                cur.execute(f"DROP INDEX IF EXISTS {case['index_name']}")
                cur.execute("ANALYZE orders")

                a1_warm, a1_samples, rows = timed(case["sql"], case["params"])
                if run_number == 1:
                    (case_dir / "plan-a1.json").write_text(
                        json.dumps(plan(case["sql"], case["params"]), indent=2) + "\n",
                        encoding="utf-8",
                    )

                build_start = time.perf_counter()
                cur.execute(case["ddl"])
                build_us = round((time.perf_counter() - build_start) * 1_000_000)
                cur.execute("ANALYZE orders")
                cur.execute(
                    "SELECT pg_relation_size(%s), pg_size_pretty(pg_relation_size(%s))",
                    (case["index_name"], case["index_name"]),
                )
                row = cur.fetchone()
                assert row is not None
                size_bytes, size_pretty = row

                b_warm, b_samples, _ = timed(case["sql"], case["params"])
                if run_number == 1:
                    (case_dir / "plan-b.json").write_text(
                        json.dumps(plan(case["sql"], case["params"]), indent=2) + "\n",
                        encoding="utf-8",
                    )

                cur.execute(f"DROP INDEX {case['index_name']}")
                cur.execute("ANALYZE orders")
                a2_warm, a2_samples, _ = timed(case["sql"], case["params"])

                document = {
                    "case_id": case["id"],
                    "run": run_number,
                    "recorded_at": args.recorded_at,
                    "units": "microseconds",
                    "protocol": {
                        "warmups": WARMUPS,
                        "samples": SAMPLES,
                        "order": "control A1, physical treatment B, drift control A2",
                        "fetch_policy": "execute then fetchall, both inside the timed region",
                    },
                    "formulas": FORMULAS,
                    "query": {"sql": case["sql"], "params": case["params"], "rows": rows},
                    "arms": {
                        "control_a1": {"warmups": a1_warm, "samples": a1_samples, "rows": rows},
                        "treatment_b": {"warmups": b_warm, "samples": b_samples, "rows": rows},
                        "drift_control_a2": {
                            "warmups": a2_warm,
                            "samples": a2_samples,
                            "rows": rows,
                        },
                    },
                    "index": {
                        "name": case["index_name"],
                        "ddl": case["ddl"],
                        "build_us": build_us,
                        "size_bytes": size_bytes,
                        "size_pretty": size_pretty,
                    },
                    "dataset": dataset,
                    "server": {
                        "version": environment["server_version"],
                        "image_digest": args.image_digest,
                    },
                    "client": environment["client"],
                    "host": environment["host"],
                    "session_settings": list(args.setting),
                }
                (case_dir / f"run-{run_number}.json").write_text(
                    json.dumps(document, indent=2) + "\n", encoding="utf-8"
                )
                print(f"wrote {case_dir / f'run-{run_number}.json'}")
    return 0


def nplus1(args: argparse.Namespace) -> int:
    """Count statements for the N+1 operation in one fixture, using its own app code."""
    sys.path.insert(0, str(Path(args.fixture).resolve()))
    from app.db import build_engine
    from app.repositories import order_totals_by_item
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    engine = build_engine()
    statements: list[str] = []

    def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
        statements.append(statement.lstrip().split("\n")[0])

    # event.listen rather than @event.listens_for: the decorator form is untyped
    # here because SQLAlchemy is not resolvable outside a fixture environment.
    event.listen(engine, "before_cursor_execute", record)

    with Session(engine) as session:
        totals = order_totals_by_item(session, args.tenant_id, args.status)

    selects = [s for s in statements if s.upper().startswith("SELECT")]
    result = {
        "orders_returned": len(totals),
        "select_statements": len(selects),
        "totals_checksum": sum(total for _, total in totals),
        "order_ids": [order_id for order_id, _ in totals],
    }
    print(json.dumps(result, indent=2))
    return 0


def compare_nplus1(broken: dict[str, Any], clean: dict[str, Any], clean_expected: int) -> list[str]:
    """Rules the N+1 case must satisfy: 1+N in broken, fixed in clean, same results."""
    problems: list[str] = []
    returned = broken.get("orders_returned", 0)
    if returned <= 0:
        problems.append("broken returned no orders, so the counts prove nothing")
    if clean.get("orders_returned") != returned:
        problems.append(
            f"fixtures returned different row counts: "
            f"{returned} broken, {clean.get('orders_returned')} clean"
        )
    if broken.get("select_statements") != 1 + returned:
        problems.append(
            f"broken is not 1+N: {broken.get('select_statements')} statements for {returned} orders"
        )
    if clean.get("select_statements") != clean_expected:
        problems.append(
            f"clean is not a fixed count of {clean_expected}: "
            f"{clean.get('select_statements')} statements"
        )
    if broken.get("order_ids") != clean.get("order_ids"):
        problems.append("order ids differ between fixtures, so results are not equivalent")
    if broken.get("totals_checksum") != clean.get("totals_checksum"):
        problems.append("totals checksums differ between fixtures")
    return problems


def compare_nplus1_command(args: argparse.Namespace) -> int:
    broken = json.loads(Path(args.broken).read_text(encoding="utf-8"))
    clean = json.loads(Path(args.clean).read_text(encoding="utf-8"))
    problems = compare_nplus1(broken, clean, args.clean_expected)
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    print(
        f"ok broken {broken['select_statements']} = 1 + {broken['orders_returned']}, "
        f"clean {clean['select_statements']} fixed, "
        f"checksum {broken['totals_checksum']} equivalent"
    )
    return 0


def summarize(args: argparse.Namespace) -> int:
    measurements = Path(args.measurements)
    summary = build_summary(measurements)
    block = render_tables(measurements)
    if args.write:
        (measurements / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        write_generated_block(Path(args.notes), block)
        print(f"wrote {measurements / 'summary.json'} and the generated block in {args.notes}")
    else:
        print(block)
    return 0


def check_command(args: argparse.Namespace) -> int:
    problems = check(Path(args.measurements), Path(args.notes))
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    print("raw evidence, summary.json and the generated block agree")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    collect_parser = sub.add_parser("collect", help="run measurements and write raw evidence")
    collect_parser.add_argument("--dsn", required=True)
    collect_parser.add_argument("--cases", required=True)
    collect_parser.add_argument("--measurements", required=True)
    collect_parser.add_argument("--image-digest", required=True)
    collect_parser.add_argument("--recorded-at", required=True)
    collect_parser.add_argument("--runs", type=int, default=3)
    collect_parser.add_argument("--setting", action="append", default=[])
    collect_parser.set_defaults(func=collect)

    nplus1_parser = sub.add_parser("nplus1", help="count statements for the N+1 operation")
    nplus1_parser.add_argument("--fixture", required=True)
    nplus1_parser.add_argument("--tenant-id", type=int, required=True)
    nplus1_parser.add_argument("--status", required=True)
    nplus1_parser.set_defaults(func=nplus1)

    compare_parser = sub.add_parser(
        "compare-nplus1", help="assert 1+N in broken and a fixed equivalent count in clean"
    )
    compare_parser.add_argument("--broken", required=True)
    compare_parser.add_argument("--clean", required=True)
    compare_parser.add_argument("--clean-expected", type=int, default=2)
    compare_parser.set_defaults(func=compare_nplus1_command)

    summarize_parser = sub.add_parser("summarize", help="derive summaries from raw evidence")
    summarize_parser.add_argument("--measurements", required=True)
    summarize_parser.add_argument("--notes", default="fixtures/demo-broken/MEASUREMENT.md")
    summarize_parser.add_argument("--write", action="store_true")
    summarize_parser.set_defaults(func=summarize)

    check_parser = sub.add_parser("check", help="verify notes and summary match raw evidence")
    check_parser.add_argument("--measurements", required=True)
    check_parser.add_argument("--notes", default="fixtures/demo-broken/MEASUREMENT.md")
    check_parser.set_defaults(func=check_command)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
