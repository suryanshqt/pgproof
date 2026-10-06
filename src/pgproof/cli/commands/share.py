"""`pgproof share`: build the self-contained static report bundle from
artifacts `pgproof review` already wrote under `.pgproof/`.

`docs/PRODUCT_SPEC.md` section 15: "share inventory before export". This
command never reads source, connects to a database, or sends telemetry — it
only rereads what `review` already persisted and renders it to
`.pgproof/share/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from pgproof.adapters.reports.pr_diff import changed_decisions, render_pr_comment
from pgproof.adapters.reports.share_inventory import build_share_inventory, find_leaked_text
from pgproof.adapters.reports.static_bundle import render_static_bundle
from pgproof.cli.exit_codes import CliError, ExitCode
from pgproof.domain.decisions import DecisionLog
from pgproof.domain.envelope import ArtifactType
from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.recommendations import RecommendationSet
from pgproof.store.artifacts import read_artifact
from pgproof.store.paths import ProjectLayout


def _read_decision_log(path: Path) -> DecisionLog:
    if not path.is_file():
        return DecisionLog()
    envelope = read_artifact(path, ArtifactType.DECISIONS)
    log: DecisionLog = envelope.data
    return log


def _load_bundle_inputs(
    layout: ProjectLayout,
) -> tuple[RecommendationSet, EvidenceGraph, DecisionLog]:
    recommendations_path = layout.analysis_path(ArtifactType.RECOMMENDATIONS)
    if not recommendations_path.is_file():
        raise CliError(
            "no recommendations.json found; run `pgproof review` first",
            exit_code=ExitCode.ARTIFACT_INCOMPATIBLE,
        )
    recommendations: RecommendationSet = read_artifact(
        recommendations_path, ArtifactType.RECOMMENDATIONS
    ).data
    evidence_path = layout.analysis_path(ArtifactType.EVIDENCE)
    evidence = (
        read_artifact(evidence_path, ArtifactType.EVIDENCE).data
        if evidence_path.is_file()
        else EvidenceGraph()
    )
    decisions = _read_decision_log(layout.decisions_path)
    return recommendations, evidence, decisions


@click.command("share")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option(
    "--base-decisions",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="A base branch's decisions.json, to render a changed-decisions-only PR comment.",
)
def share(path: Path, base_decisions: Path | None) -> None:
    """Render the static, shareable report bundle to .pgproof/share/."""
    root = path.resolve()
    layout = ProjectLayout(root)
    recommendations, evidence, decisions = _load_bundle_inputs(layout)

    bundle_text = render_static_bundle(recommendations, evidence, decisions)
    leaked = find_leaked_text(bundle_text, forbidden=(str(root),))
    if leaked:
        raise CliError(
            f"refusing to export: the bundle contains {leaked!r}, "
            "which looks like an absolute repository path",
            exit_code=ExitCode.INTERNAL_ERROR,
        )

    share_dir = layout.pgproof_dir / "share"
    share_dir.mkdir(parents=True, exist_ok=True)
    share_dir.chmod(0o700)
    report_path = share_dir / "report.md"
    report_path.write_text(bundle_text, encoding="utf-8")

    inventory = build_share_inventory(
        {
            "report.md": bundle_text.encode("utf-8"),
            "recommendations": recommendations.model_dump_json().encode("utf-8"),
            "decisions": decisions.model_dump_json().encode("utf-8"),
        }
    )
    inventory_path = share_dir / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            [
                {
                    "name": entry.name,
                    "byte_size": entry.byte_size,
                    "content_hash": entry.content_hash,
                }
                for entry in inventory
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    click.echo(f"Static report: {report_path}")
    click.echo(f"Share inventory: {inventory_path}")

    if base_decisions is not None:
        base_envelope = read_artifact(base_decisions, ArtifactType.DECISIONS)
        changed = changed_decisions(base=base_envelope.data, head=decisions)
        comment_path = share_dir / "pr_comment.md"
        comment_path.write_text(render_pr_comment(changed), encoding="utf-8")
        click.echo(f"PR comment: {comment_path}")
