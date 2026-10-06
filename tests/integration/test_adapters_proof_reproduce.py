"""BE-30 accept criterion: "index proof reproduces without source repository
... and tampering is detected." Real Docker, two independent disposable
PostgreSQL instances: one produces the original measurement and writes the
bundle, the other starts empty and reproduces from the bundle alone — no
Alembic migration, no fixture repository, nothing but `schema.sql` and
`dataset.yaml`.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from pgproof.adapters.benchmark.explain import parse_explain
from pgproof.adapters.benchmark.run import CandidateDDL, run_experiment
from pgproof.adapters.postgres.catalog import PsycopgCatalogReader
from pgproof.adapters.postgres.lifecycle import DockerPostgresLifecycle
from pgproof.adapters.proof.bundle import write_proof_bundle
from pgproof.adapters.proof.reproduce import reproduce_bundle
from pgproof.adapters.runner.docker import create_network, probe_docker, remove_network
from pgproof.adapters.seeder.load import load_dataset
from pgproof.ports.database import GeneratedCredentials

requires_docker = pytest.mark.skipif(
    not probe_docker().daemon_reachable, reason="Docker daemon not reachable"
)
pytestmark = requires_docker

_POSTGRES_IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
_SCHEMA_SQL = "CREATE TABLE orders (id serial PRIMARY KEY, user_id integer NOT NULL);"
_QUERY_SQL = "SELECT id FROM orders WHERE user_id = %(user_id)s"
_CANDIDATE = CandidateDDL(
    apply_sql="CREATE INDEX ix_orders_user_id ON orders (user_id)",
    revert_sql="DROP INDEX ix_orders_user_id",
)
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_SCALE = {"public.orders": 200_000}
_GLOBAL_SEED = 17


@pytest.fixture
def network() -> Iterator[str]:
    name = f"pgproof-net-{uuid.uuid4().hex[:12]}"
    create_network(name)
    try:
        yield name
    finally:
        remove_network(name)


def _disposable_database(network: str) -> Iterator[GeneratedCredentials]:
    lifecycle = DockerPostgresLifecycle()
    database = lifecycle.start(image=_POSTGRES_IMAGE, timeout_seconds=180, network=network)
    try:
        yield database.credentials
    finally:
        lifecycle.stop(database)


@pytest.fixture
def origin_database(network: str) -> Iterator[GeneratedCredentials]:
    yield from _disposable_database(network)


@pytest.fixture
def reproduction_database(network: str) -> Iterator[GeneratedCredentials]:
    yield from _disposable_database(network)


def _write_bundle_from_a_real_measurement(
    directory: Path,
    credentials: GeneratedCredentials,
    *,
    parameters: dict[str, object] | None = None,
) -> None:
    with psycopg.connect(credentials.dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
        conn.commit()
        schema = PsycopgCatalogReader().introspect(credentials)
        load_dataset(conn, schema, global_seed=_GLOBAL_SEED, scale=_SCALE, epoch=_EPOCH)

        result = run_experiment(conn, _QUERY_SQL, {"user_id": 1}, candidate=_CANDIDATE)
        assert result.control_a1 is not None
        assert result.treatment_b is not None
        assert result.drift_control_a2 is not None
        assert result.explain_b is not None
        plan = parse_explain(result.explain_b)

    write_proof_bundle(
        directory,
        proof_id="IDX-TEST@sha256:" + "a" * 64,
        tool_version="0.1.0",
        generator_version=1,
        schema_sql=_SCHEMA_SQL,
        query_sql=_QUERY_SQL,
        parameters=parameters or {"user_id": {"is_redacted": False, "redacted_value": 1}},
        dataset={
            "global_seed": _GLOBAL_SEED,
            "scale": _SCALE,
            "epoch": _EPOCH.isoformat(),
        },
        config={
            "candidate": {
                "apply_sql": _CANDIDATE.apply_sql,
                "revert_sql": _CANDIDATE.revert_sql,
            },
            "postgres_settings": {},
        },
        evidence={
            "control-a1": dataclasses.asdict(result.control_a1),
            "treatment-b": dataclasses.asdict(result.treatment_b),
            "control-a2": dataclasses.asdict(result.drift_control_a2),
        },
        plans={
            "treatment-b": {
                "plan_fingerprint": plan.plan_fingerprint,
                "normalized_shape": plan.normalized_shape,
            }
        },
        readme="# Proof IDX-TEST\n",
    )


def test_the_bundle_reproduces_against_an_independent_fresh_database(
    tmp_path: Path,
    origin_database: GeneratedCredentials,
    reproduction_database: GeneratedCredentials,
) -> None:
    """BE-25's own variance gate (`docs/TECHNICAL_DESIGN.md` section 20) can
    legitimately mark one real run's new measurement unstable under shared
    CI/Docker scheduling noise — confirmed directly in
    `tests/integration/test_adapters_benchmark_run.py` and
    `tests/integration/test_adapters_candidates_verify.py`. A real
    `pgproof reproduce` caller would simply re-run; this test does the same.
    """
    _write_bundle_from_a_real_measurement(tmp_path, origin_database)

    result = None
    for _ in range(5):
        with psycopg.connect(reproduction_database.dsn, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS orders")
        with psycopg.connect(reproduction_database.dsn) as conn:
            attempt = reproduce_bundle(conn, reproduction_database, tmp_path)
        assert attempt.tampered is False
        assert attempt.schema_version_compatible is True
        assert attempt.direction_matches is True
        assert attempt.plan_shape_compatible is True
        if attempt.stable:
            result = attempt
            break
    assert result is not None, "never stable across 5 attempts"
    assert result.reproduced is True


def test_a_tampered_bundle_is_detected_and_never_reaches_the_database(
    tmp_path: Path,
    origin_database: GeneratedCredentials,
    reproduction_database: GeneratedCredentials,
) -> None:
    _write_bundle_from_a_real_measurement(tmp_path, origin_database)
    (tmp_path / "query.sql").write_text("SELECT * FROM orders", encoding="utf-8")

    with psycopg.connect(reproduction_database.dsn) as conn:
        result = reproduce_bundle(conn, reproduction_database, tmp_path)
        # The reproduction database must still be empty: a tampered bundle's
        # schema.sql/dataset were never applied.
        row = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'orders'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0

    assert result.tampered is True
    assert result.tamper_problems != ()
    assert result.reproduced is False


def test_redacted_parameters_with_no_recoverable_value_are_reported_not_guessed(
    tmp_path: Path,
    origin_database: GeneratedCredentials,
    reproduction_database: GeneratedCredentials,
) -> None:
    _write_bundle_from_a_real_measurement(
        tmp_path, origin_database, parameters={"user_id": {"is_redacted": True}}
    )

    with psycopg.connect(reproduction_database.dsn) as conn:
        result = reproduce_bundle(conn, reproduction_database, tmp_path)
        row = conn.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = 'orders'"
        ).fetchone()
        assert row is not None
        assert row[0] == 0, "the dataset must never be loaded when the query cannot be re-run"

    assert result.tampered is False
    assert result.schema_version_compatible is True
    assert result.parameters_available is False
    assert result.reproduced is False
