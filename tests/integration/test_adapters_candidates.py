"""BE-27 accept criterion: "screening is never labeled measured/verified and
existing compatible indexes prevent duplicates." Real Docker, real
PostgreSQL, `fixtures/demo-broken`'s real reconciled schema — the same
`orders.user_id` gap `fixtures/demo-broken/EXPECTED.yaml` calls `IDX-001`,
which carries no index in this fixture, so a candidate for it must not be
deduplicated away.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from pgproof.adapters.candidates.generate import generate_candidates
from pgproof.adapters.candidates.screen import screen_candidates
from pgproof.adapters.parameters.extract import extract_predicates
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.runner.docker import (
    DockerRunner,
    create_network,
    probe_docker,
    remove_network,
)
from pgproof.adapters.sql.parser import parse_query
from pgproof.domain.execution import RunnerConfig
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import SchemaIR
from pgproof.ports.database import GeneratedCredentials
from pgproof.ports.runner import RunSpec

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_DEMO_BROKEN = Path(__file__).parents[2] / "fixtures" / "demo-broken"
_MIGRATION_COMMAND = (
    "sh",
    "-c",
    'DATABASE_URL=$(echo "$DATABASE_URL" | sed "s#^postgresql://#postgresql+psycopg://#") '
    "/opt/venv/bin/alembic upgrade head",
)
_ORDERS = table_id("public", "orders")


@pytest.fixture(scope="module")
def migrated() -> Iterator[tuple[GeneratedCredentials, SchemaIR]]:
    network = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(network)
    lifecycle = DockerPostgresLifecycle()
    database = lifecycle.start(image=_POSTGRES_IMAGE, timeout_seconds=180, network=network)
    try:
        assert database.internal_credentials is not None
        config = RunnerConfig(
            build="Dockerfile", migration_command=_MIGRATION_COMMAND, timeout_seconds=300
        )
        outcome = DockerRunner().run(
            RunSpec(
                source=_DEMO_BROKEN,
                config=config,
                command=_MIGRATION_COMMAND,
                environment={"DATABASE_URL": database.internal_credentials.dsn},
                network=network,
            )
        )
        assert outcome.succeeded, outcome.stderr
        yield database.credentials, PsycopgCatalogReader().introspect(database.credentials)
    finally:
        lifecycle.stop(database)
        remove_network(network)


def test_a_candidate_is_proposed_for_the_real_missing_index_gap(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    _, schema = migrated
    query = parse_query("SELECT id FROM orders WHERE user_id = $1", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    result = generate_candidates(schema, predicates)
    assert (column_id(_ORDERS, "user_id"),) in {c.columns for c in result.candidates}
    assert not any(d.reason.startswith("duplicate_of_existing_index") for d in result.discarded)


def test_a_candidate_for_an_already_indexed_column_is_a_duplicate(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    """`order_items.order_id` already has a real migration-created index
    (`ix_order_items_order_id`) — a fresh candidate for it must be discarded,
    not proposed as if the gap were real.
    """
    _, schema = migrated
    query = parse_query("SELECT id FROM order_items WHERE order_id = $1", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    result = generate_candidates(schema, predicates)
    assert result.candidates == ()
    assert result.discarded[0].reason == "duplicate_of_existing_index:ix_order_items_order_id"


def test_hypopg_screening_is_honestly_unavailable_in_this_sandbox(
    migrated: tuple[GeneratedCredentials, SchemaIR],
) -> None:
    """The standard `postgres` image ships no `hypopg`, and this project's
    isolated runner has no external network to install it — the expected,
    common outcome here, not a rare failure path.
    """
    credentials, schema = migrated
    query = parse_query("SELECT id FROM orders WHERE user_id = $1", schema=schema)
    predicates = extract_predicates(query, schema=schema)
    candidates = generate_candidates(schema, predicates).candidates
    assert candidates
    with psycopg.connect(credentials.dsn) as conn:
        results = screen_candidates(
            conn, "SELECT id FROM orders WHERE user_id = %s", (1,), candidates
        )
    assert len(results) == len(candidates)
    for result in results:
        assert result.screened is False
        assert result.skip_reason == "hypopg_extension_unavailable"
        assert result.estimated_cost_before is None
        assert result.estimated_cost_after is None
