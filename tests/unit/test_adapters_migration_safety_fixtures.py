"""`adapters.migration_safety` against `fixtures/demo-broken`'s own real
migration history as a base, with a newly-added migration on top standing in
for a "current branch" — no Docker needed, this is pure static analysis over
real Alembic revision files, the same ground-truth corpus the rest of this
project's fixture-based tests already use.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pgproof.adapters.migration_safety.diff import added_revisions
from pgproof.adapters.migration_safety.risk import RiskCategory, assess_migration
from pgproof.adapters.repository.alembic_static import parse_migrations

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "demo-broken"
_NEW_MIGRATION = '''"""drop a column, unsafely

Revision ID: 0003_drop_status
Revises: 6a912ef4c1b8
Create Date: 2026-03-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_drop_status"
down_revision = "6a912ef4c1b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("orders", "status")
    op.create_index("ix_orders_total_cents", "orders", ["total_cents"])


def downgrade() -> None:
    op.add_column("orders", sa.Column("status", sa.String(length=32), nullable=False))
'''


def test_the_fixtures_own_real_migrations_carry_no_risk() -> None:
    """`fixtures/demo-broken`'s own two committed migrations are deliberately
    unremarkable schema creation — no destructive/constraint/type/index risk
    is expected of them at all.
    """
    result = parse_migrations(
        list((_FIXTURE / "migrations" / "versions").glob("*.py")), root=_FIXTURE
    )
    for revision in result.revisions:
        source_text = (_FIXTURE / revision.source.path).read_text(encoding="utf-8")
        assert (
            assess_migration(source_text, revision=revision.revision, source=revision.source) == ()
        )


def test_a_new_migration_on_the_current_branch_is_detected_and_assessed(tmp_path: Path) -> None:
    current_root = tmp_path / "current"
    shutil.copytree(_FIXTURE, current_root)
    new_file = current_root / "migrations" / "versions" / "0003_drop_status.py"
    new_file.write_text(_NEW_MIGRATION, encoding="utf-8")

    base_result = parse_migrations(
        list((_FIXTURE / "migrations" / "versions").glob("*.py")), root=_FIXTURE
    )
    current_result = parse_migrations(
        list((current_root / "migrations" / "versions").glob("*.py")), root=current_root
    )

    added = added_revisions(base_result.graph, current_result.graph, current_result.revisions)
    assert [item.revision for item in added] == ["0003_drop_status"]

    source_text = (current_root / added[0].source.path).read_text(encoding="utf-8")
    risks = assess_migration(source_text, revision=added[0].revision, source=added[0].source)
    categories = {risk.category for risk in risks}
    assert categories == {RiskCategory.DESTRUCTIVE, RiskCategory.INDEX}

    destructive = next(risk for risk in risks if risk.category is RiskCategory.DESTRUCTIVE)
    assert destructive.operation == "drop_column"
    assert destructive.reversible is False
