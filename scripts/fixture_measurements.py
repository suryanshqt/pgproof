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
from collections.abc import Sequence
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
    runs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(measurements.glob("*/run-*.json"))
    ]
    runs.sort(key=lambda run: (run["case_id"], run["run"]))
    return runs


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
        f"demo-clean issues {clean['select_statements']} regardless of row count. "
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


def check(measurements: Path, notes: Path) -> list[str]:
    problems: list[str] = []
    runs = load_runs(measurements)
    if not runs:
        return [f"no raw runs under {measurements}"]
    for run in runs:
        problems.extend(validate_run(run))
    for case in case_ids(runs):
        case_dir = measurements / case.lower()
        for plan in ("plan-a1.json", "plan-b.json"):
            if not (case_dir / plan).is_file():
                problems.append(f"{case}: missing plan evidence {plan}")
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
        server_version = cur.fetchone()[0]
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
            explain = cur.fetchone()[0]
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
                size_bytes, size_pretty = cur.fetchone()

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
