"""`pgproof share`: the static report bundle, built from `review`'s own output.

The seeded-canary test is `docs/PR_ROADMAP.md` BE-34's release gate made
concrete: a fake secret planted in the fixture repository must never reach
the exported bundle.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from pgproof.cli.app import main
from pgproof.store.paths import ProjectLayout

FIXTURES = Path(__file__).parents[2] / "fixtures"


def _clean(root: Path) -> None:
    shutil.rmtree(root / ".pgproof", ignore_errors=True)


@pytest.fixture(autouse=True)
def _cleanup_demo_fixtures() -> Iterator[None]:
    yield
    _clean(FIXTURES / "demo-broken")
    _clean(FIXTURES / "demo-clean")


def test_share_without_a_prior_review_fails_clearly() -> None:
    result = CliRunner().invoke(main, ["share", str(FIXTURES / "demo-clean")])
    assert result.exit_code != 0
    assert "pgproof review" in result.output


def test_share_writes_a_static_report_and_inventory() -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])
    result = CliRunner().invoke(main, ["share", str(root)])
    assert result.exit_code == 0

    layout = ProjectLayout(root)
    report_path = layout.pgproof_dir / "share" / "report.md"
    inventory_path = layout.pgproof_dir / "share" / "inventory.json"
    assert report_path.is_file()
    assert inventory_path.is_file()
    assert "TENANT-001" in report_path.read_text(encoding="utf-8")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    names = {entry["name"] for entry in inventory}
    assert {"report.md", "recommendations", "decisions"} <= names


def test_the_exported_bundle_never_contains_the_absolute_repository_path() -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])
    CliRunner().invoke(main, ["share", str(root)])
    report = (root / ".pgproof" / "share" / "report.md").read_text(encoding="utf-8")
    assert str(root.resolve()) not in report


def test_a_seeded_canary_planted_in_a_source_comment_never_reaches_the_bundle(
    tmp_path: Path,
) -> None:
    """The canary lives only in a comment the parser does not surface as
    evidence text; if it ever appeared in the bundle, something had started
    copying raw source into the shared report.
    """
    root = tmp_path / "demo-broken"
    shutil.copytree(FIXTURES / "demo-broken", root)
    canary = "PGPROOF-SEEDED-TEST-CANARY-0000000000000000"
    models_path = root / "app" / "models.py"
    models_path.write_text(f"# {canary}\n" + models_path.read_text(encoding="utf-8"))

    CliRunner().invoke(main, ["review", str(root)])
    CliRunner().invoke(main, ["share", str(root)])
    report = (root / ".pgproof" / "share" / "report.md").read_text(encoding="utf-8")
    assert canary not in report


def test_base_decisions_renders_a_changed_decisions_pr_comment(tmp_path: Path) -> None:
    root = FIXTURES / "demo-broken"
    CliRunner().invoke(main, ["review", str(root)])

    base_decisions_path = tmp_path / "base-decisions.json"
    base_decisions_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "tool_version": "0.1.0",
                "artifact_type": "decisions",
                "created_at": "2026-01-01T00:00:00Z",
                "run_id": "01JQ0X3M4N5P6R7S8T9V0W1X2Y",
                "inputs": {},
                "data": {"decisions": []},
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main, ["share", str(root), "--base-decisions", str(base_decisions_path)]
    )
    assert result.exit_code == 0
    comment_path = root / ".pgproof" / "share" / "pr_comment.md"
    assert comment_path.is_file()
    assert "no decisions changed" in comment_path.read_text(encoding="utf-8")


def test_help_documents_base_decisions() -> None:
    result = CliRunner().invoke(main, ["share", "--help"])
    assert "--base-decisions" in result.output
