"""`adapters.migration_safety.risk.assess_migration` against a hand-authored
safe/unsafe migration corpus. `docs/PR_ROADMAP.md`'s BE-31 accept criterion:
"Accept on safe/unsafe migration corpus without invented production
duration" — checked directly: no `MigrationRisk.reason` contains a number of
seconds/minutes/hours, matching the rest of this codebase's evidence
discipline.
"""

from __future__ import annotations

import re

from pgproof.adapters.migration_safety.risk import MigrationRisk, RiskCategory, assess_migration
from pgproof.domain.recommendations import ChangeKind
from pgproof.domain.sources import SourceRef

_DIGEST = "sha256:" + "a" * 64
_SOURCE = SourceRef(path="migrations/versions/0001_x.py", content_hash=_DIGEST)

_DURATION_WORDS = re.compile(r"\b\d+\s*(second|minute|hour|ms|millisecond)s?\b", re.IGNORECASE)


def _assess(source_text: str) -> tuple[MigrationRisk, ...]:
    return assess_migration(source_text, revision="0001", source=_SOURCE)


# --------------------------------------------------------------------------- #
# Safe migrations: no risk, or a risk this module itself marks reversible.
# --------------------------------------------------------------------------- #


def test_creating_a_table_is_not_a_risk() -> None:
    risks = _assess(
        "def upgrade():\n"
        "    op.create_table('widgets', sa.Column('id', sa.Integer, primary_key=True))\n"
    )
    assert risks == ()


def test_adding_a_nullable_column_is_not_a_risk() -> None:
    risks = _assess(
        "def upgrade():\n    op.add_column('widgets', sa.Column('note', sa.Text, nullable=True))\n"
    )
    assert risks == ()


def test_adding_a_not_null_column_with_a_default_is_not_a_risk() -> None:
    risks = _assess(
        "def upgrade():\n"
        "    op.add_column('widgets', sa.Column('active', sa.Boolean, "
        "nullable=False, server_default='true'))\n"
    )
    assert risks == ()


def test_a_concurrent_index_is_not_a_risk() -> None:
    risks = _assess(
        "def upgrade():\n"
        "    op.create_index('ix_widgets_name', 'widgets', ['name'], "
        "postgresql_concurrently=True)\n"
    )
    assert risks == ()


def test_an_unrecognized_operation_is_not_a_risk() -> None:
    risks = _assess('def upgrade():\n    op.execute("SELECT 1")\n')
    assert risks == ()


def test_downgrades_own_drop_table_is_not_a_risk_of_the_upgrade() -> None:
    risks = _assess(
        "def upgrade():\n"
        "    op.create_table('widgets', sa.Column('id', sa.Integer, primary_key=True))\n"
        "\n"
        "def downgrade():\n"
        "    op.drop_table('widgets')\n"
    )
    assert risks == ()


# --------------------------------------------------------------------------- #
# Unsafe migrations: a real, categorized risk.
# --------------------------------------------------------------------------- #


def test_dropping_a_table_is_destructive_and_irreversible() -> None:
    (risk,) = _assess("def upgrade():\n    op.drop_table('widgets')\n")
    assert risk.category is RiskCategory.DESTRUCTIVE
    assert risk.reversible is False


def test_dropping_a_column_is_destructive_and_irreversible() -> None:
    (risk,) = _assess("def upgrade():\n    op.drop_column('widgets', 'note')\n")
    assert risk.category is RiskCategory.DESTRUCTIVE
    assert risk.reversible is False


def test_an_ordinary_create_index_is_an_index_risk_linked_to_the_add_index_template() -> None:
    (risk,) = _assess(
        "def upgrade():\n    op.create_index('ix_widgets_name', 'widgets', ['name'])\n"
    )
    assert risk.category is RiskCategory.INDEX
    assert risk.expand_contract_change_kind is ChangeKind.ADD_INDEX
    assert risk.reversible is True


def test_a_not_null_column_with_no_default_has_a_version_assumption() -> None:
    (risk,) = _assess(
        "def upgrade():\n"
        "    op.add_column('widgets', sa.Column('active', sa.Boolean, nullable=False))\n"
    )
    assert risk.category is RiskCategory.CONSTRAINT
    assert risk.assumption is not None
    assert "PostgreSQL 11" in risk.assumption


def test_a_type_change_is_a_type_risk_linked_to_the_alter_column_template() -> None:
    (risk,) = _assess(
        "def upgrade():\n    op.alter_column('widgets', 'price', type_=sa.Numeric(10, 2))\n"
    )
    assert risk.category is RiskCategory.TYPE_CHANGE
    assert risk.expand_contract_change_kind is ChangeKind.ALTER_COLUMN
    assert risk.reversible is False


def test_dropping_a_constraint_is_a_constraint_risk() -> None:
    (risk,) = _assess("def upgrade():\n    op.drop_constraint('uq_widgets_sku', 'widgets')\n")
    assert risk.category is RiskCategory.CONSTRAINT


def test_adding_a_foreign_key_links_to_the_add_constraint_template() -> None:
    (risk,) = _assess(
        "def upgrade():\n"
        "    op.create_foreign_key('fk_widgets_tenant', 'widgets', 'tenants', "
        "['tenant_id'], ['id'])\n"
    )
    assert risk.category is RiskCategory.CONSTRAINT
    assert risk.expand_contract_change_kind is ChangeKind.ADD_CONSTRAINT


def test_a_constraint_on_a_table_created_in_the_same_migration_is_not_a_risk() -> None:
    """A table created earlier in this same `upgrade()` holds no pre-existing
    rows, so a constraint added to it right after carries none of the
    existing-row-validation cost this module's constraint risk is about.
    `create_foreign_key`'s table argument is its *second* positional
    argument (the first is the constraint name) — this is the regression
    this test exists to pin.
    """
    risks = _assess(
        "def upgrade():\n"
        "    op.create_table('widgets', sa.Column('id', sa.Integer, primary_key=True))\n"
        "    op.create_foreign_key('fk_widgets_tenant', 'widgets', 'tenants', "
        "['tenant_id'], ['id'])\n"
        "    op.create_unique_constraint('uq_widgets_sku', 'widgets', ['sku'])\n"
        "    op.create_index('ix_widgets_sku', 'widgets', ['sku'])\n"
    )
    assert risks == ()


def test_the_same_constraint_on_a_pre_existing_table_is_still_a_risk() -> None:
    (risk,) = _assess(
        "def upgrade():\n"
        "    op.create_foreign_key('fk_widgets_tenant', 'widgets', 'tenants', "
        "['tenant_id'], ['id'])\n"
    )
    assert risk.category is RiskCategory.CONSTRAINT


def test_a_migration_with_several_operations_reports_each_one() -> None:
    risks = _assess(
        "def upgrade():\n"
        "    op.drop_table('widgets')\n"
        "    op.create_index('ix_gadgets_name', 'gadgets', ['name'])\n"
    )
    assert {risk.operation for risk in risks} == {"drop_table", "create_index"}


# --------------------------------------------------------------------------- #
# Accept criterion: never an invented production duration.
# --------------------------------------------------------------------------- #


def test_no_risk_reason_or_assumption_states_a_duration() -> None:
    corpus = [
        "def upgrade():\n    op.drop_table('widgets')\n",
        "def upgrade():\n    op.drop_column('widgets', 'note')\n",
        "def upgrade():\n    op.create_index('ix_widgets_name', 'widgets', ['name'])\n",
        "def upgrade():\n"
        "    op.add_column('widgets', sa.Column('active', sa.Boolean, nullable=False))\n",
        "def upgrade():\n    op.alter_column('widgets', 'price', type_=sa.Numeric(10, 2))\n",
        "def upgrade():\n    op.drop_constraint('uq_widgets_sku', 'widgets')\n",
    ]
    for source_text in corpus:
        for risk in _assess(source_text):
            assert not _DURATION_WORDS.search(risk.reason)
            if risk.assumption is not None:
                assert not _DURATION_WORDS.search(risk.assumption)


def test_malformed_source_yields_no_risks_not_an_exception() -> None:
    assert _assess("def upgrade(:\n    this is not valid python\n") == ()


def test_a_file_with_no_upgrade_function_yields_no_risks() -> None:
    assert _assess("def something_else():\n    pass\n") == ()
