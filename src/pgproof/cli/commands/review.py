"""`pgproof review`: parse-only design review, cached and written under `.pgproof/`.

`docs/TECHNICAL_DESIGN.md` section 2: `pgproof review PATH [--scenario launch|
growth|availability]`. No import, migration, test, container, or database
connection happens here — `docs/PRODUCT_SPEC.md` section 9's parse-only mode
contract, already how `inspect`/`configure` are built.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

from pgproof import __version__
from pgproof.adapters.diagrams.graph_ir import build_graph
from pgproof.adapters.repository.config_toml import read_config
from pgproof.adapters.repository.inventory import discover
from pgproof.application.review import ReviewResult, run_review
from pgproof.cli.commands.inspect import parse_alembic_directories, parse_sqlalchemy_models
from pgproof.cli.rendering.capabilities import TerminalCapabilities, detect_capabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import finding_summary, next_command, stage_line, trailer_line
from pgproof.domain.cache import stage_cache_key
from pgproof.domain.envelope import ArtifactType
from pgproof.domain.evidence import EvidenceGraph
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, SchemaProvenance
from pgproof.domain.primitives import Contract
from pgproof.domain.recommendations import Recommendation, RecommendationPriority
from pgproof.domain.reconciliation import reconcile
from pgproof.domain.registry import envelope_model_for
from pgproof.domain.scenarios import ScenarioKind, ScenarioSet
from pgproof.domain.stages import StageName
from pgproof.ports.clock import SystemClock
from pgproof.ports.repository import RepositoryInventory
from pgproof.rules.base import RuleContext
from pgproof.store.artifacts import read_artifact
from pgproof.store.paths import ProjectLayout
from pgproof.store.run import RunSession, format_rfc3339
from pgproof.store.run_id import new_run_id

_SCENARIO_CHOICES = {
    "launch": ScenarioKind.LAUNCH_MINIMAL,
    "growth": ScenarioKind.GROWTH_READY,
    "availability": ScenarioKind.AVAILABILITY_READY,
}
_REQUIRED_PRIORITIES = (
    RecommendationPriority.REQUIRED_FOR_CORRECTNESS,
    RecommendationPriority.REQUIRED_BY_CONFIRMED_REQUIREMENTS,
)
_PRIORITY_SEVERITY = {
    RecommendationPriority.REQUIRED_FOR_CORRECTNESS: 0,
    RecommendationPriority.REQUIRED_BY_CONFIRMED_REQUIREMENTS: 1,
    RecommendationPriority.VERIFIED_IMPROVEMENT: 2,
    RecommendationPriority.WORTH_EVALUATING: 3,
    RecommendationPriority.OPTIONAL_HARDENING: 4,
}
_MAX_HEADLINE_SHOWN = 3


def _now() -> str:
    return format_rfc3339(SystemClock().now())


def _select_physical_schema(alembic_schemas: tuple[SchemaIR, ...]) -> SchemaIR:
    """The first unambiguously-replayed migration schema; empty when none replays.

    Reconciling against more than one Alembic environment at once is out of
    scope here: `inspect` already names each one individually, but the rule
    engine needs exactly one physical `SchemaIR`.
    """
    for schema in alembic_schemas:
        if schema.migration_head is not None:
            return schema
    return SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)


def _schema_reconstruction_cache_key(inventory: RepositoryInventory) -> str:
    file_hashes = {ref.path: ref.content_hash for ref in inventory.included}
    return stage_cache_key(file_hashes=file_hashes, tool_versions={"pgproof": __version__})


def _load_cached_schema_and_code(
    layout: ProjectLayout, cache_key: str
) -> tuple[SchemaIR, CodeIR] | None:
    """A prior run's physical schema and ORM code, if nothing they were built
    from has changed since. `docs/PRODUCT_SPEC.md` section 18: "static review
    under 60 seconds from cached inspection artifacts" — this is that cache.
    """
    schema_path = layout.analysis_path(ArtifactType.SCHEMA)
    code_path = layout.analysis_path(ArtifactType.CODE)
    if not schema_path.is_file() or not code_path.is_file():
        return None
    schema_envelope = read_artifact(schema_path, ArtifactType.SCHEMA)
    code_envelope = read_artifact(code_path, ArtifactType.CODE)
    if (
        schema_envelope.inputs.get("stage_cache_key") != cache_key
        or code_envelope.inputs.get("stage_cache_key") != cache_key
    ):
        return None
    assert isinstance(schema_envelope.data, SchemaIR)
    assert isinstance(code_envelope.data, CodeIR)
    return schema_envelope.data, code_envelope.data


def _write_artifact(
    session: RunSession,
    layout: ProjectLayout,
    artifact_type: ArtifactType,
    data: Contract,
    *,
    inputs: dict[str, str] | None = None,
) -> None:
    envelope_cls = envelope_model_for(artifact_type)
    envelope = envelope_cls(
        tool_version=__version__,
        artifact_type=artifact_type,
        created_at=_now(),
        run_id=session.run_id,
        data=data,
        inputs=inputs or {},
    )
    session.record_artifact(artifact_type, layout.analysis_path(artifact_type), envelope)


def _priority_label(priority: RecommendationPriority) -> str:
    if priority in _REQUIRED_PRIORITIES:
        return "required"
    if priority is RecommendationPriority.VERIFIED_IMPROVEMENT:
        return "verified"
    if priority is RecommendationPriority.WORTH_EVALUATING:
        return "worth eval."
    return "optional"


def _evidence_sources(recommendation: Recommendation, evidence: EvidenceGraph) -> list[str]:
    by_id = {ref.id: ref for ref in evidence.refs}
    sources = []
    for ref_id in recommendation.evidence_refs:
        ref = by_id.get(ref_id)
        if ref is None or ref.source is None:
            continue
        location = ref.source.path
        if ref.source.line is not None:
            location += f":{ref.source.line}"
        sources.append(location)
    return sources


def _sorted_headline(recommendations: tuple[Recommendation, ...]) -> list[Recommendation]:
    headline = [
        r for r in recommendations if r.priority is not RecommendationPriority.OPTIONAL_HARDENING
    ]
    return sorted(headline, key=lambda r: (_PRIORITY_SEVERITY[r.priority], r.id))


def render_review(
    result: ReviewResult, evidence: EvidenceGraph, *, caps: TerminalCapabilities, width: int
) -> str:
    recommendations = result.recommendations.recommendations
    required = sum(1 for r in recommendations if r.priority in _REQUIRED_PRIORITIES)
    worth_evaluating = sum(
        1 for r in recommendations if r.priority is RecommendationPriority.WORTH_EVALUATING
    )
    questions = len(result.recommendations.questions)

    lines = [
        trailer_line(f"{required} required", "correctness decisions"),
        trailer_line(f"{worth_evaluating} worth eval.", "candidate improvements"),
        trailer_line(f"{questions} questions", "material context missing"),
    ]
    headline = _sorted_headline(recommendations)
    if not headline:
        lines.append("")
        lines.append(stage_line(Mark.OK, "No headline result", caps=caps, width=width))
        return "\n".join(lines)

    lines.append("")
    for recommendation in headline[:_MAX_HEADLINE_SHOWN]:
        lines.append(
            finding_summary(
                category=_priority_label(recommendation.priority),
                title=recommendation.title,
                description=recommendation.statement,
                sources=_evidence_sources(recommendation, evidence),
                caps=caps,
                width=width,
            )
        )
    hidden = len(headline) - min(len(headline), _MAX_HEADLINE_SHOWN)
    if hidden > 0:
        lines.append(f"    ... and {hidden} more (--verbose to show all)")
    return "\n".join(lines)


def render_markdown_report(result: ReviewResult, evidence: EvidenceGraph) -> str:
    recommendations = result.recommendations.recommendations
    lines = ["# pgproof review", ""]
    if not recommendations:
        lines.append("No recommendations.")
        return "\n".join(lines) + "\n"
    for recommendation in sorted(
        recommendations, key=lambda r: (_PRIORITY_SEVERITY[r.priority], r.id)
    ):
        lines.append(f"## {recommendation.id}: {recommendation.title}")
        lines.append("")
        lines.append(f"- Priority: `{recommendation.priority.value}`")
        lines.append(f"- Category: `{recommendation.category.value}`")
        lines.append("")
        lines.append(recommendation.statement)
        sources = _evidence_sources(recommendation, evidence)
        if sources:
            lines.append("")
            lines.extend(f"- {source}" for source in sources)
        lines.append("")
    return "\n".join(lines)


def _build_review(
    root: Path, scenario_kind: ScenarioKind
) -> tuple[ReviewResult, EvidenceGraph, RunSession, Path]:
    layout = ProjectLayout(root)
    layout.ensure_base_layout()
    session = RunSession(layout, new_run_id(), __version__)

    session.start_stage(StageName.REPOSITORY_INVENTORY)
    inventory = discover(root)
    session.complete_stage(StageName.REPOSITORY_INVENTORY)

    session.start_stage(StageName.SCHEMA_RECONSTRUCTION)
    cache_key = _schema_reconstruction_cache_key(inventory)
    cached = _load_cached_schema_and_code(layout, cache_key)
    sqlalchemy_result = parse_sqlalchemy_models(inventory, root)
    orm_schema = sqlalchemy_result.schema
    if cached is not None:
        physical, code = cached
    else:
        alembic_results = parse_alembic_directories(inventory, root)
        physical = _select_physical_schema(tuple(r.schema for r in alembic_results.values()))
        code = sqlalchemy_result.code
    reconciliation = reconcile(physical, orm_schema, code)
    session.complete_stage(StageName.SCHEMA_RECONSTRUCTION, cache_key=cache_key)

    session.start_stage(StageName.CONTEXT_RESOLUTION)
    config = read_config(root / "pgproof.toml")
    session.complete_stage(StageName.CONTEXT_RESOLUTION)

    session.start_stage(StageName.CANDIDATE_SCREENING)
    rule_ctx = RuleContext(
        physical=physical,
        orm_schema=orm_schema,
        code=code,
        reconciliation=reconciliation,
        context=config.context,
    )
    result = run_review(rule_ctx, scenario_kind)
    session.complete_stage(StageName.CANDIDATE_SCREENING)

    session.start_stage(StageName.REPORT_GENERATION)
    layout_paths = layout
    _write_artifact(
        session, layout_paths, ArtifactType.SCHEMA, physical, inputs={"stage_cache_key": cache_key}
    )
    _write_artifact(
        session, layout_paths, ArtifactType.CODE, code, inputs={"stage_cache_key": cache_key}
    )
    _write_artifact(session, layout_paths, ArtifactType.EVIDENCE, reconciliation.evidence)
    _write_artifact(session, layout_paths, ArtifactType.RECOMMENDATIONS, result.recommendations)
    _write_artifact(
        session, layout_paths, ArtifactType.SCENARIOS, ScenarioSet(scenarios=(result.scenario,))
    )
    _write_artifact(session, layout_paths, ArtifactType.MIGRATION_PLAN, result.migration_plan)

    graph = build_graph(physical, orm_schema, code)
    graph_envelope_cls = envelope_model_for(ArtifactType.GRAPH)
    graph_envelope = graph_envelope_cls(
        tool_version=__version__,
        artifact_type=ArtifactType.GRAPH,
        created_at=_now(),
        run_id=session.run_id,
        data=graph,
    )
    session.record_artifact(ArtifactType.GRAPH, layout.diagram_path("current"), graph_envelope)

    report_dir = layout.pgproof_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_dir.chmod(0o700)
    markdown_path = report_dir / "review.md"
    markdown_path.write_text(
        render_markdown_report(result, reconciliation.evidence), encoding="utf-8"
    )
    session.complete_stage(StageName.REPORT_GENERATION)

    session.finish()
    return result, reconciliation.evidence, session, markdown_path


@click.command("review")
@click.argument(
    "path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
)
@click.option(
    "--scenario",
    type=click.Choice(sorted(_SCENARIO_CHOICES)),
    default="launch",
    help="Which deterministic projection to build the migration plan for.",
)
@click.option("--json", "as_json", is_flag=True, help="Write the review result as JSON.")
@click.pass_context
def review(ctx: click.Context, path: Path, scenario: str, as_json: bool) -> None:
    """Run the rule engine against PATH and write its artifacts under .pgproof/."""
    root = path.resolve()
    result, evidence, _session, markdown_path = _build_review(root, _SCENARIO_CHOICES[scenario])

    if as_json:
        click.echo(
            json.dumps(
                {
                    "recommendations": result.recommendations.canonical_dict(),
                    "scenario": result.scenario.canonical_dict(),
                    "migration_plan": result.migration_plan.canonical_dict(),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return

    obj = ctx.obj or {}
    caps = detect_capabilities(sys.stdout, force_ascii=bool(obj.get("force_ascii", False)))
    width = shutil.get_terminal_size((80, 24)).columns if caps.interactive else 80
    click.echo(render_review(result, evidence, caps=caps, width=width))
    click.echo("")
    click.echo(trailer_line("Report", str(markdown_path)))
    click.echo(next_command("pgproof ui ."))
