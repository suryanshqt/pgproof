"""Migration execution and physical reconciliation.

`docs/ARCHITECTURE.md:307-329`'s `pgproof capture` sequence, the steps up
through "introspect final catalog" — BE-20 adds the pytest-capture half of
that same command. Orchestration only, over already-injected ports
(`Runner`, `DatabaseLifecycle`, `CatalogReader`): no adapter construction, no
`RunSession`, no filesystem writes, no `pgproof.toml` reading. Those belong
to `cli/commands/capture.py` (not built yet — BE-20's own deliverable),
mirroring how `cli/commands/review.py` owns all I/O around
`application/review.py`'s pure decision logic.

A failed migration returns with `physical_schema=None` and
`reconciliation=None` — the caller never has a `SchemaIR` to write as
`analysis/schema.json`, which is what `docs/PR_ROADMAP.md`'s "failed
migrations produce no physical-analysis manifest" means mechanically: this
function simply never produces the artifact, rather than a store-level rule
suppressing one that exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from pgproof.domain.execution import RunnerConfig, RunOutcome
from pgproof.domain.ir.code import CodeIR
from pgproof.domain.ir.schema import SchemaIR, UnsupportedConstruct
from pgproof.domain.reconciliation import ReconciliationReport, reconcile
from pgproof.ports.database import CatalogReader, DatabaseLifecycle
from pgproof.ports.runner import Runner, RunSpec


@dataclass(frozen=True)
class CaptureResult:
    outcome: RunOutcome
    head_matched: bool | None
    physical_schema: SchemaIR | None
    reconciliation: ReconciliationReport | None
    # The static migration's own `UnsupportedConstruct`s (e.g. an unresolved
    # `op.execute`) — BE-18's "DML preservation metadata": surfaced, not
    # newly verified, since nothing in this codebase diffs row contents yet.
    unverified_migration_operations: tuple[UnsupportedConstruct, ...]

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded


def run_capture(
    *,
    root: Path,
    runner: Runner,
    database_lifecycle: DatabaseLifecycle,
    catalog_reader: CatalogReader,
    config: RunnerConfig,
    postgres_image: str,
    network_name: str,
    allowlisted_environment: Mapping[str, str],
    static_schema: SchemaIR,
    orm_schema: SchemaIR,
    code: CodeIR,
    cancel_event: Event | None = None,
) -> CaptureResult:
    """`docs/TECHNICAL_DESIGN.md` section 8, steps 2-9. Step 1 (statically
    resolving the expected head) is the caller's job — it's already
    `static_schema.migration_head`, from `adapters.repository.alembic_static`.

    `network_name` must already exist (`adapters.runner.docker.create_network`)
    and is *required*, not optional: without a shared network the runner
    container has no route to the disposable database at all, host-bound
    `127.0.0.1` credentials meaning nothing from inside another container.
    """
    if not config.migration_command:
        raise ValueError("config.migration_command must be set to run a capture")

    database = database_lifecycle.start(
        image=postgres_image, timeout_seconds=config.timeout_seconds, network=network_name
    )
    try:
        assert database.internal_credentials is not None  # network_name was given above
        environment = dict(allowlisted_environment)
        environment[config.database_url_env] = database.internal_credentials.dsn
        spec = RunSpec(
            source=root,
            config=config,
            command=config.migration_command,
            environment=environment,
            cancel_event=cancel_event,
            network=network_name,
        )
        outcome = runner.run(spec)
        if not outcome.succeeded:
            return CaptureResult(
                outcome=outcome,
                head_matched=None,
                physical_schema=None,
                reconciliation=None,
                unverified_migration_operations=static_schema.unsupported,
            )

        physical_schema = catalog_reader.introspect(database.credentials)
        head_matched = (
            static_schema.migration_head is None
            or physical_schema.migration_head == static_schema.migration_head
        )
        report = reconcile(physical_schema, orm_schema, code)
        return CaptureResult(
            outcome=outcome,
            head_matched=head_matched,
            physical_schema=physical_schema,
            reconciliation=report,
            unverified_migration_operations=static_schema.unsupported,
        )
    finally:
        database_lifecycle.stop(database)
