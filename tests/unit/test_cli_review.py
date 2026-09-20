"""`pgproof review`: end-to-end against the real demo-broken/demo-clean fixtures,
artifact writing, and the schema-reconstruction cache."""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

import pgproof.cli.commands.review as review_module
from pgproof.adapters.repository.alembic_static import AlembicStaticResult
from pgproof.cli.app import main
from pgproof.cli.commands.inspect import parse_alembic_directories
from pgproof.domain.envelope import ArtifactType
from pgproof.ports.repository import RepositoryInventory
from pgproof.store.paths import ProjectLayout

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _clean(root: Path) -> None:
    shutil.rmtree(root / ".pgproof", ignore_errors=True)


@pytest.fixture(autouse=True)
def _cleanup_demo_fixtures() -> Iterator[None]:
    yield
    _clean(FIXTURES / "demo-broken")
    _clean(FIXTURES / "demo-clean")


# --------------------------------------------------------------------------- #
# Golden: the real fixtures, end to end through the CLI
# --------------------------------------------------------------------------- #
def test_demo_broken_reports_the_planted_tenant_gap_and_two_index_gaps() -> None:
    result = CliRunner().invoke(main, ["--ascii", "review", str(FIXTURES / "demo-broken")])
    assert result.exit_code == 0
    assert "1 required" in result.output
    assert "2 worth eval." in result.output
    assert "Enforce the orders to tenants relationship physically" in result.output
    assert "Index order_items.product_id" in result.output
    assert "Index orders.user_id" in result.output


def test_demo_clean_has_no_headline_result() -> None:
    result = CliRunner().invoke(main, ["--ascii", "review", str(FIXTURES / "demo-clean")])
    assert result.exit_code == 0
    assert "0 required" in result.output
    assert "No headline result" in result.output


def test_a_headline_finding_never_changes_the_exit_code() -> None:
    result = CliRunner().invoke(main, ["review", str(FIXTURES / "demo-broken")])
    assert result.exit_code == 0


# --------------------------------------------------------------------------- #
# On-disk artifacts
# --------------------------------------------------------------------------- #
def test_review_writes_every_analysis_artifact() -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])
    layout = ProjectLayout(root)
    for artifact_type in (
        ArtifactType.SCHEMA,
        ArtifactType.CODE,
        ArtifactType.EVIDENCE,
        ArtifactType.RECOMMENDATIONS,
        ArtifactType.SCENARIOS,
        ArtifactType.MIGRATION_PLAN,
    ):
        assert layout.analysis_path(artifact_type).is_file()
    assert layout.diagram_path("current").is_file()
    assert (layout.pgproof_dir / "report" / "review.md").is_file()


def test_review_writes_a_run_manifest_and_events() -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])
    layout = ProjectLayout(root)
    runs = list(layout.runs_dir.iterdir())
    assert len(runs) == 1
    assert (runs[0] / "manifest.json").is_file()
    assert (runs[0] / "events.ndjson").is_file()
    assert (runs[0] / "result.json").is_file()


def test_the_markdown_report_lists_every_recommendation() -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])
    markdown = (root / ".pgproof" / "report" / "review.md").read_text(encoding="utf-8")
    assert "TENANT-001" in markdown
    assert "IDX-001" in markdown
    assert "IDX-002" in markdown


def test_the_markdown_report_says_so_when_there_is_nothing_to_report() -> None:
    root = FIXTURES / "demo-clean"
    CliRunner().invoke(main, ["review", str(root)])
    markdown = (root / ".pgproof" / "report" / "review.md").read_text(encoding="utf-8")
    assert "No recommendations." in markdown


# --------------------------------------------------------------------------- #
# --json
# --------------------------------------------------------------------------- #
def test_json_output_carries_recommendations_scenario_and_plan() -> None:
    result = CliRunner().invoke(main, ["review", str(FIXTURES / "demo-broken"), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert {"recommendations", "scenario", "migration_plan"} <= payload.keys()
    assert len(payload["recommendations"]["recommendations"]) == 3


# --------------------------------------------------------------------------- #
# --scenario
# --------------------------------------------------------------------------- #
def test_scenario_flag_selects_the_projection() -> None:
    result = CliRunner().invoke(
        main, ["review", str(FIXTURES / "demo-broken"), "--scenario", "growth", "--json"]
    )
    payload = json.loads(result.output)
    assert payload["scenario"]["kind"] == "growth_ready"


def test_an_invalid_scenario_choice_is_rejected() -> None:
    result = CliRunner().invoke(
        main, ["review", str(FIXTURES / "demo-broken"), "--scenario", "bogus"]
    )
    assert result.exit_code == 2


def test_help_documents_scenario_and_json() -> None:
    result = CliRunner().invoke(main, ["review", "--help"])
    assert "--scenario" in result.output
    assert "--json" in result.output


# --------------------------------------------------------------------------- #
# Schema-reconstruction cache
# --------------------------------------------------------------------------- #
def test_a_second_run_reuses_the_cached_schema_without_reparsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])

    calls: list[int] = []
    real = parse_alembic_directories

    def _spy(inventory: RepositoryInventory, path: Path) -> dict[str, AlembicStaticResult]:
        calls.append(1)
        return real(inventory, path)

    monkeypatch.setattr(review_module, "parse_alembic_directories", _spy)
    result = CliRunner().invoke(main, ["review", str(root)])
    assert result.exit_code == 0
    assert calls == []


def test_touching_a_migration_file_invalidates_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])

    calls: list[int] = []
    real = parse_alembic_directories

    def _spy(inventory: RepositoryInventory, path: Path) -> dict[str, AlembicStaticResult]:
        calls.append(1)
        return real(inventory, path)

    monkeypatch.setattr(review_module, "parse_alembic_directories", _spy)
    migration = next((root / "migrations" / "versions").glob("*.py"))
    original = migration.read_text(encoding="utf-8")
    migration.write_text(original + "\n# a harmless comment\n", encoding="utf-8")
    try:
        result = CliRunner().invoke(main, ["review", str(root)])
        assert result.exit_code == 0
        assert calls == [1]
    finally:
        migration.write_text(original, encoding="utf-8")


def test_a_fresh_repository_with_no_prior_run_parses_normally() -> None:
    result = CliRunner().invoke(main, ["review", str(FIXTURES / "demo-clean")])
    assert result.exit_code == 0
