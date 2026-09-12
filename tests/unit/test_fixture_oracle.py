"""Contract for the ground-truth fixtures and their EXPECTED.yaml oracles.

The fixtures are analysed as data, never imported, so these checks parse them
rather than executing them.
"""

import ast
import filecmp
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

FIXTURES = Path(__file__).parents[2] / "fixtures"
BROKEN = FIXTURES / "demo-broken"
CLEAN = FIXTURES / "demo-clean"

EVIDENCE_LABELS = frozenset({"observed", "user_confirmed", "inferred", "verified_in_fixture"})
PRIORITIES = frozenset(
    {
        "required_for_correctness",
        "required_by_confirmed_requirements",
        "verified_improvement",
        "worth_evaluating",
        "optional_hardening",
    }
)
PLANTED_CASES = ("TENANT-001", "IDX-001", "IDX-002", "NPLUS1-001")

# demo-clean is demo-broken with the four planted cases corrected. Anything else
# differing lets a rule pass for the wrong reason.
MAY_DIFFER = frozenset(
    {
        "EXPECTED.yaml",
        "app/models.py",
        "app/repositories.py",
        "migrations/versions/0002_create_orders.py",
        "pyproject.toml",
    }
)
BROKEN_ONLY = frozenset({"MEASUREMENT.md"})

# Reproducing a fixture by hand creates .venv and tool caches inside it. Walking
# those made the divergence check fail for anyone who followed the documented
# procedure, and their contents differ per machine.
IGNORED_DIRS = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
    }
)

# A measured quantity in an oracle would be a fabricated performance claim.
MEASUREMENT_UNIT = re.compile(r"\d+(?:\.\d+)?\s*(?:ms|µs|us|sec|seconds|%)\b", re.IGNORECASE)
MEASUREMENT_WORD = re.compile(
    r"\b(?:median|latency|percentile|p95|throughput|faster|slower|speedup|iqr)\b",
    re.IGNORECASE,
)


def load(fixture: Path) -> dict[str, Any]:
    document = yaml.safe_load((fixture / "EXPECTED.yaml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def relative_files(fixture: Path) -> set[str]:
    return {
        str(path.relative_to(fixture))
        for path in fixture.rglob("*")
        if path.is_file() and IGNORED_DIRS.isdisjoint(path.parts)
    }


def fixture_sources(fixture: Path) -> Iterator[str]:
    for path in sorted(fixture.rglob("*.py")):
        if IGNORED_DIRS.isdisjoint(path.parts):
            yield path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def broken() -> dict[str, Any]:
    return load(BROKEN)


@pytest.fixture(scope="module")
def clean() -> dict[str, Any]:
    return load(CLEAN)


def test_both_fixtures_exist() -> None:
    assert (BROKEN / "EXPECTED.yaml").is_file()
    assert (CLEAN / "EXPECTED.yaml").is_file()
    assert (BROKEN / "MEASUREMENT.md").is_file()
    assert (FIXTURES / "benchmark-corpus.yaml").is_file()


def test_broken_declares_exactly_the_planted_cases(broken: dict[str, Any]) -> None:
    assert tuple(f["id"] for f in broken["headline_findings"]) == PLANTED_CASES


def test_clean_control_reports_no_headline_finding(clean: dict[str, Any]) -> None:
    assert clean["headline_findings"] == []
    assert clean["role"] == "control"


def test_clean_control_accounts_for_every_planted_case(clean: dict[str, Any]) -> None:
    corrected = {entry["id"] for entry in clean["clean_control_assertions"]}
    assert corrected == set(PLANTED_CASES)


@pytest.mark.parametrize("case_id", PLANTED_CASES)
def test_every_finding_uses_a_declared_evidence_label_and_priority(
    broken: dict[str, Any], case_id: str
) -> None:
    finding = next(f for f in broken["headline_findings"] if f["id"] == case_id)
    assert finding["evidence"] in EVIDENCE_LABELS
    assert finding["priority"] in PRIORITIES


@pytest.mark.parametrize("case_id", PLANTED_CASES)
def test_every_source_reference_resolves_to_real_text(broken: dict[str, Any], case_id: str) -> None:
    finding = next(f for f in broken["headline_findings"] if f["id"] == case_id)
    assert finding["sources"], f"{case_id} cites no source"
    for source in finding["sources"]:
        path = BROKEN / source["path"]
        assert path.is_file(), f"{case_id} cites missing file {source['path']}"
        assert source["anchor"] in path.read_text(encoding="utf-8"), (
            f"{case_id} anchor {source['anchor']!r} is absent from {source['path']}"
        )


@pytest.mark.parametrize("fixture", [BROKEN, CLEAN], ids=["demo-broken", "demo-clean"])
def test_oracle_states_no_measured_quantity(fixture: Path) -> None:
    document = load(fixture)
    # forbidden_claims names the measurements the product may never make, so it
    # is the one section allowed to mention them.
    document.pop("forbidden_claims")
    text = yaml.safe_dump(document)
    assert not MEASUREMENT_UNIT.findall(text)
    assert not MEASUREMENT_WORD.findall(text)


@pytest.mark.parametrize("fixture", [BROKEN, CLEAN], ids=["demo-broken", "demo-clean"])
def test_oracle_forbids_the_claims_the_product_may_never_make(fixture: Path) -> None:
    forbidden = load(fixture)["forbidden_claims"]
    assert any("replica" in claim.lower() for claim in forbidden)
    assert any("production" in claim.lower() for claim in forbidden)


def test_clean_differs_from_broken_only_in_the_planted_cases() -> None:
    broken_files, clean_files = relative_files(BROKEN), relative_files(CLEAN)
    assert broken_files - clean_files == BROKEN_ONLY
    assert clean_files - broken_files == set()

    shared = sorted(broken_files & clean_files)
    _, mismatch, errors = filecmp.cmpfiles(BROKEN, CLEAN, shared, shallow=False)
    assert errors == []
    assert set(mismatch) <= MAY_DIFFER, (
        f"unexpected divergence: {sorted(set(mismatch) - MAY_DIFFER)}"
    )


def test_every_planted_case_is_anchored_in_broken_but_not_in_clean() -> None:
    clean_text = "\n".join(fixture_sources(CLEAN))
    broken_text = "\n".join(fixture_sources(BROKEN))
    for case_id in PLANTED_CASES:
        assert case_id in broken_text, f"{case_id} is not marked in demo-broken source"
        assert case_id not in clean_text, f"{case_id} marker leaked into demo-clean source"


@pytest.mark.parametrize("fixture", [BROKEN, CLEAN], ids=["demo-broken", "demo-clean"])
def test_fixture_python_is_syntactically_valid(fixture: Path) -> None:
    sources = list(fixture_sources(fixture))
    assert sources
    for source in sources:
        ast.parse(source)


def test_benchmark_corpus_pins_every_repository_by_commit() -> None:
    corpus = yaml.safe_load((FIXTURES / "benchmark-corpus.yaml").read_text(encoding="utf-8"))
    assert corpus["runtime"]["postgres_digest"].startswith("sha256:")
    assert corpus["repositories"]
    for repository in corpus["repositories"]:
        assert re.fullmatch(r"[0-9a-f]{40}", repository["commit"]), repository["id"]
        assert repository["url"].startswith("https://github.com/")
        assert repository["role"]


# The audit that produced these guards found the reverse of each: a digest
# recorded but never used, and ranges standing in for the measured versions.
PINNED_CLIENTS = ("sqlalchemy", "alembic", "psycopg", "pytest")


def test_measurement_notes_pin_postgres_by_digest() -> None:
    text = (BROKEN / "MEASUREMENT.md").read_text(encoding="utf-8")
    corpus = yaml.safe_load((FIXTURES / "benchmark-corpus.yaml").read_text(encoding="utf-8"))
    digest = corpus["runtime"]["postgres_digest"]
    assert f"postgres@{digest}" in text
    assert not re.search(r"\bpostgres:\d", text), "floating image tag in the procedure"
    assert not re.search(r"\bpostgres:\d", yaml.safe_dump(corpus["runtime"]))


@pytest.mark.parametrize("fixture", [BROKEN, CLEAN], ids=["demo-broken", "demo-clean"])
def test_fixture_declares_exact_pins_and_ships_a_lockfile(fixture: Path) -> None:
    manifest = tomllib.loads((fixture / "pyproject.toml").read_text(encoding="utf-8"))
    declared = manifest["project"]["dependencies"] + manifest["dependency-groups"]["dev"]
    assert declared
    for requirement in declared:
        assert "==" in requirement, f"{requirement} is not an exact pin"
    assert (fixture / "uv.lock").is_file()
    assert (fixture / ".python-version").is_file()


def test_both_fixtures_share_one_locked_client_stack() -> None:
    assert (BROKEN / "uv.lock").read_bytes() == (CLEAN / "uv.lock").read_bytes()
    assert (BROKEN / ".python-version").read_text() == (CLEAN / ".python-version").read_text()


def test_measured_environment_matches_the_fixture_lockfile() -> None:
    lock = tomllib.loads((BROKEN / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"]: p["version"] for p in lock["package"]}
    environment = (BROKEN / "MEASUREMENT.md").read_text(encoding="utf-8")
    for name in PINNED_CLIENTS:
        version = locked[name]
        assert re.search(rf"{name} {re.escape(version)}\b", environment, re.IGNORECASE), (
            f"MEASUREMENT.md does not attribute its numbers to {name} {version}"
        )
    python_version = (BROKEN / ".python-version").read_text().strip()
    assert f"| Python | {python_version}" in environment
