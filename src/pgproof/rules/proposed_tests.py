"""Proposed test sketches: `docs/PR_ROADMAP.md` BE-33's "proposed catalog/
Alembic/query-count/raiseload/equivalence tests". Every function here returns
plain text for a developer to paste and adapt — none writes a file, matching
`ProposedChange`'s existing "sketch, never applied" contract (`docs/
PRODUCT_SPEC.md` section 17 forbids automatic repository mutation).

v1 covers the five named kinds as independent, explicitly-parameterized
renderers rather than consuming `RuleContext`/adapter IR directly: migration
risk (`adapters.migration_safety`) and treatment comparison
(`adapters.treatment.compare`) are not yet part of the `rules` pipeline
`RuleContext` feeds, and routing that data through here would be a pipeline
change out of scope for a test-sketch renderer.
ponytail: callers pass fields by hand today; wiring a rule's own IR straight
into these functions is the upgrade path once a rule needs one.
"""

from __future__ import annotations

from pgproof.domain.primitives import SnakeCaseEnum


class ProposedTestKind(SnakeCaseEnum):
    CATALOG = "catalog"
    ALEMBIC = "alembic"
    QUERY_COUNT = "query_count"
    RAISELOAD = "raiseload"
    EQUIVALENCE = "equivalence"


def render_catalog_test(*, table: str, index_columns: tuple[str, ...]) -> str:
    """Asserts a physical index exists; a migration that drops it fails loudly."""
    columns = ", ".join(repr(column) for column in index_columns)
    return (
        f"def test_{table}_has_a_covering_index(connection) -> None:\n"
        f"    indexes = fetch_indexes(connection, {table!r})\n"
        f"    assert any(index.columns[:1] == [{columns}][:1] for index in indexes)\n"
    )


def render_alembic_test(*, revision: str, table: str) -> str:
    """Runs one migration forward and checks the table it claims to touch exists."""
    return (
        f"def test_migration_{revision}_creates_{table}(alembic_runner) -> None:\n"
        f"    alembic_runner.migrate_up_to({revision!r})\n"
        f"    assert alembic_runner.table_exists({table!r})\n"
    )


def render_query_count_test(*, operation: str, expected_count: int) -> str:
    """Pins a query count so a future change that reintroduces N+1 fails CI."""
    return (
        f"def test_{operation}_issues_{expected_count}_queries(query_counter) -> None:\n"
        f"    with query_counter() as counter:\n"
        f"        {operation}()\n"
        f"    assert counter.count == {expected_count}\n"
    )


def render_raiseload_test(*, relationship: str) -> str:
    """SQLAlchemy `raiseload` turns an accidental lazy load into a test failure."""
    return (
        f"def test_{relationship}_is_eager_loaded(session) -> None:\n"
        f"    obj = session.execute(\n"
        f"        select(Model).options(raiseload({relationship!r}))\n"
        f"    ).scalar_one()\n"
        f"    obj.{relationship}  # raises if this relationship was not eager-loaded\n"
    )


def render_equivalence_test(*, operation: str) -> str:
    """Baseline and treatment must agree on results; `treatment.compare` already
    computes this at proof time — this sketch pins it as a standing regression test.
    """
    return (
        f"def test_{operation}_treatment_matches_baseline(baseline, treatment) -> None:\n"
        f"    assert baseline.{operation}() == treatment.{operation}()\n"
    )


_RENDERERS = {
    ProposedTestKind.CATALOG: render_catalog_test,
    ProposedTestKind.ALEMBIC: render_alembic_test,
    ProposedTestKind.QUERY_COUNT: render_query_count_test,
    ProposedTestKind.RAISELOAD: render_raiseload_test,
    ProposedTestKind.EQUIVALENCE: render_equivalence_test,
}


def render_test_sketch(kind: ProposedTestKind, **params: object) -> str:
    """Dispatch to the one renderer for `kind`. Raises `TypeError` on a
    missing/extra keyword, same as calling the renderer directly would.
    """
    return _RENDERERS[kind](**params)  # type: ignore[operator,no-any-return]
