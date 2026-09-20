"""Static Alembic parsing against `fixtures/alembic-static/`, one scenario per directory."""

from pathlib import Path

from pgproof.adapters.repository.alembic_static import AlembicStaticResult, parse_migrations
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, SchemaProvenance, TableIR

FIXTURES = Path(__file__).parents[2] / "fixtures" / "alembic-static"


def _parse(*relative_paths: str) -> AlembicStaticResult:
    root = FIXTURES
    paths = [root / relative for relative in relative_paths]
    return parse_migrations(paths, root=root)


def _table(schema: SchemaIR, name: str) -> TableIR:
    return next(t for t in schema.tables if t.name == name)


def _column(table: TableIR, name: str) -> ColumnIR:
    return next(c for c in table.columns if c.name == name)


# --------------------------------------------------------------------------- #
# Linear chain: the common case
# --------------------------------------------------------------------------- #
def test_linear_chain_has_one_root_and_one_head() -> None:
    result = _parse("linear/0001_initial.py", "linear/0002_add_sessions.py")
    assert result.graph.roots == ("lin_0001",)
    assert result.graph.heads == ("lin_0002",)
    assert result.graph.merge_revisions == ()
    assert result.graph.missing_predecessors == ()
    assert result.graph.cycle == ()


def test_linear_chain_replays_into_a_cumulative_schema() -> None:
    result = _parse("linear/0001_initial.py", "linear/0002_add_sessions.py")
    schema = result.schema
    assert schema.provenance is SchemaProvenance.STATIC_MIGRATION
    assert schema.migration_head == "lin_0002"
    assert schema.migration_revisions == ("lin_0001", "lin_0002")
    assert {t.name for t in schema.tables} == {"accounts", "sessions"}

    accounts = _table(schema, "accounts")
    assert {c.name for c in accounts.columns} == {"id", "email", "is_active"}
    email = _column(accounts, "email")
    assert email.nullable is False
    assert email.data_type == "sa.String(length=320)"

    assert {c.name for c in schema.constraints} == {
        "pk_accounts",
        "pk_sessions",
        "uq_accounts_email",
        "fk_sessions_account_id",
    }
    fk = next(c for c in schema.constraints if c.name == "fk_sessions_account_id")
    assert fk.referenced_table == accounts.id
    assert fk.on_delete is not None
    assert fk.on_delete.value == "cascade"

    assert {i.name for i in schema.indexes} == {"ix_sessions_account_id"}
    assert schema.unsupported == ()


def test_the_real_be02_fixture_migrations_parse_cleanly() -> None:
    """The two migrations BE-02's demo-broken app already ships, as an independent check."""
    demo = Path(__file__).parents[2] / "fixtures" / "demo-broken" / "migrations" / "versions"
    result = parse_migrations(sorted(demo.glob("*.py")), root=demo.parent.parent.parent)
    assert len(result.revisions) == 2
    assert result.graph.heads == ("6a912ef4c1b8",)
    schema = result.schema
    assert {t.name for t in schema.tables} == {
        "tenants",
        "users",
        "products",
        "orders",
        "order_items",
    }
    assert "fk_orders_user_id" in {c.name for c in schema.constraints}
    assert "fk_orders_tenant_id" not in {c.name for c in schema.constraints}


# --------------------------------------------------------------------------- #
# Branches and merges
# --------------------------------------------------------------------------- #
def test_two_divergent_branches_are_both_reported_as_heads() -> None:
    result = _parse(
        "branch_and_merge/0001_root.py",
        "branch_and_merge/0002_branch_a.py",
        "branch_and_merge/0002_branch_b.py",
    )
    assert result.graph.heads == ("bm_branch_a", "bm_branch_b")
    # Roadmap: "Multiple heads are reported; execution never auto-selects one."
    assert result.schema.tables == ()
    assert any("2 heads" in u.reason for u in result.schema.unsupported)


def test_a_merge_revision_resolves_back_to_one_head() -> None:
    result = _parse(
        "branch_and_merge/0001_root.py",
        "branch_and_merge/0002_branch_a.py",
        "branch_and_merge/0002_branch_b.py",
        "branch_and_merge/0003_merge.py",
    )
    assert result.graph.heads == ("bm_merge",)
    assert result.graph.merge_revisions == ("bm_merge",)
    widgets = _table(result.schema, "widgets")
    assert {c.name for c in widgets.columns} == {"id", "name", "color", "weight_grams"}


# --------------------------------------------------------------------------- #
# Cycle and missing predecessor
# --------------------------------------------------------------------------- #
def test_a_cycle_is_detected_and_blocks_replay() -> None:
    result = _parse("cycle/a.py", "cycle/b.py")
    assert set(result.graph.cycle) == {"cycle_a", "cycle_b"}
    assert result.schema.tables == ()
    assert any("cycle" in u.reason for u in result.schema.unsupported)


def test_a_missing_predecessor_is_reported_and_blocks_replay() -> None:
    result = _parse("missing_predecessor/orphan.py")
    assert result.graph.missing_predecessors == ("does_not_exist",)
    assert result.schema.tables == ()
    assert any("missing predecessor" in u.reason for u in result.schema.unsupported)


# --------------------------------------------------------------------------- #
# Unsupported constructs: helper, raw SQL, DML, conditional, dynamic name
# --------------------------------------------------------------------------- #
def test_every_unsupported_construct_is_reported_and_the_resolvable_one_still_applies() -> None:
    result = _parse("unsupported/dynamic.py")
    reasons = [u.reason for u in result.schema.unsupported]
    assert len(reasons) == 5
    assert any("not a direct op" in r for r in reasons)  # helper wrapper AND the conditional
    assert sum("not a direct op" in r for r in reasons) == 2
    assert any("payload not statically interpreted" in r for r in reasons)
    assert sum("payload not statically interpreted" in r for r in reasons) == 2  # raw SQL + DML
    assert any("non-literal argument" in r for r in reasons)
    assert {t.name for t in result.schema.tables} == {"known_table"}


# --------------------------------------------------------------------------- #
# Every operation kind
# --------------------------------------------------------------------------- #
def test_every_operation_kind_mutates_the_replayed_schema_correctly() -> None:
    result = _parse("operations/0001_full.py")
    assert result.schema.unsupported == ()
    schema = result.schema

    assert {t.name for t in schema.tables} == {"widgets", "tags"}

    widgets = _table(schema, "widgets")
    assert {c.name for c in widgets.columns} == {"id", "display_name", "sku"}
    sku = _column(widgets, "sku")
    assert sku.nullable is False
    assert sku.default_expression == "sa.text(\"''\")"

    assert {c.name for c in schema.constraints} == {
        "pk_widgets",
        "pk_tags",
        "uq_widgets_sku",
        "fk_tags_widget",
    }
    assert "ck_widgets_sku_not_empty" not in {c.name for c in schema.constraints}

    assert schema.indexes == ()  # created then dropped


def test_a_syntax_error_is_reported_not_raised(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def upgrade(:\n", encoding="utf-8")
    result = parse_migrations([broken], root=tmp_path)
    assert result.revisions == ()
    assert any(u.kind == "unparseable_migration" for u in result.schema.unsupported)


def test_a_file_with_no_revision_assignment_is_silently_skipped(tmp_path: Path) -> None:
    env = tmp_path / "env.py"
    env.write_text("from alembic import context\n", encoding="utf-8")
    result = parse_migrations([env], root=tmp_path)
    assert result.revisions == ()
    assert result.schema.unsupported == ()


def test_no_revisions_at_all_produces_an_empty_but_valid_schema(tmp_path: Path) -> None:
    result = parse_migrations([], root=tmp_path)
    assert result.revisions == ()
    assert result.graph.heads == ()
    assert result.schema.tables == ()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Metadata edge cases
# --------------------------------------------------------------------------- #
def test_a_down_revision_that_is_not_a_literal_string_or_list_is_ignored(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        "revision = 'r1'\n"
        "down_revision = 123\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    pass\n",
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.revisions[0].down_revisions == ()


def test_a_down_revision_list_with_a_non_literal_element_is_unresolved(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        "SOME_ID = 'x'\n"
        "revision = 'r1'\n"
        "down_revision = (SOME_ID, 'r0')\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "def upgrade():\n"
        "    pass\n",
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.revisions[0].down_revisions == ()


def test_a_multi_target_module_assignment_is_ignored(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        "revision = 'r1'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "a = b = 'not a revision field'\n"
        "def upgrade():\n"
        "    pass\n",
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.revisions[0].revision == "r1"


def test_a_revision_with_no_upgrade_function_has_no_operations(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        "revision = 'r1'\ndown_revision = None\nbranch_labels = None\ndepends_on = None\n",
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.unsupported == ()
    assert result.schema.tables == ()


# --------------------------------------------------------------------------- #
# Operation-argument resolution edge cases
# --------------------------------------------------------------------------- #
def _upgrade_module(body: str, *, preamble: str = "") -> str:
    return (
        "import sqlalchemy as sa\n"
        "from alembic import op\n"
        "revision = 'r1'\n"
        "down_revision = None\n"
        "branch_labels = None\n"
        "depends_on = None\n" + preamble + "def upgrade():\n" + body
    )


def test_an_unmodeled_op_method_is_unsupported(tmp_path: Path) -> None:
    path = _write(tmp_path, "rev.py", _upgrade_module("    op.bulk_insert(sa.table('t'), [])\n"))
    result = parse_migrations([path], root=tmp_path)
    assert len(result.schema.unsupported) == 1
    assert "op.bulk_insert is not modeled" in result.schema.unsupported[0].reason


def test_a_kwargs_splat_makes_the_call_unresolved(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module("    op.create_table('t', **CONFIG)\n", preamble="CONFIG = {}\n"),
    )
    result = parse_migrations([path], root=tmp_path)
    assert len(result.schema.unsupported) == 1
    assert "non-literal argument" in result.schema.unsupported[0].reason


def test_a_non_literal_keyword_outside_the_tolerated_set_is_unresolved(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module(
            "    op.create_index('ix', 't', ['c'], unique=IS_UNIQUE)\n",
            preamble="IS_UNIQUE = True\n",
        ),
    )
    result = parse_migrations([path], root=tmp_path)
    assert len(result.schema.unsupported) == 1
    assert "non-literal argument" in result.schema.unsupported[0].reason


def test_a_bare_column_call_without_the_sa_prefix_is_recognised(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module("    op.create_table('t', Column('id', sa.Integer()))\n"),
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.unsupported == ()
    assert {c.name for c in result.schema.tables[0].columns} == {"id"}


def test_a_column_call_with_a_non_literal_name_is_unresolved(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module(
            "    op.create_table('t', sa.Column(COLNAME, sa.Integer()))\n",
            preamble="COLNAME = 'id'\n",
        ),
    )
    result = parse_migrations([path], root=tmp_path)
    assert len(result.schema.unsupported) == 1


def test_a_column_position_argument_that_is_not_a_column_call_is_unresolved(
    tmp_path: Path,
) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module("    op.add_column('t', (lambda: None)())\n"),
    )
    result = parse_migrations([path], root=tmp_path)
    assert len(result.schema.unsupported) == 1
    assert "non-literal argument" in result.schema.unsupported[0].reason


# --------------------------------------------------------------------------- #
# Replay edge cases: operations against a table that was never created
# --------------------------------------------------------------------------- #
def test_add_column_on_an_unknown_table_is_reported(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module("    op.add_column('ghost', sa.Column('x', sa.Integer()))\n"),
    )
    result = parse_migrations([path], root=tmp_path)
    assert any("add_column on unknown table" in u.reason for u in result.schema.unsupported)


def test_drop_column_on_an_unknown_table_does_not_crash(tmp_path: Path) -> None:
    path = _write(tmp_path, "rev.py", _upgrade_module("    op.drop_column('ghost', 'x')\n"))
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.tables == ()


def test_rename_of_an_unknown_table_does_not_crash(tmp_path: Path) -> None:
    path = _write(
        tmp_path, "rev.py", _upgrade_module("    op.rename_table('ghost', 'still_ghost')\n")
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.tables == ()


def test_alter_column_on_an_unknown_table_or_column_does_not_crash(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module(
            "    op.create_table('t', sa.Column('id', sa.Integer()))\n"
            "    op.alter_column('t', 'missing_column', nullable=False)\n"
            "    op.alter_column('ghost', 'x', nullable=False)\n"
        ),
    )
    result = parse_migrations([path], root=tmp_path)
    assert {c.name for c in result.schema.tables[0].columns} == {"id"}


def test_drop_table_removes_its_own_constraints_and_indexes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module(
            "    op.create_table(\n"
            "        't', sa.Column('id', sa.Integer()), sa.Column('sku', sa.String(length=8))\n"
            "    )\n"
            "    op.create_unique_constraint('uq_t_sku', 't', ['sku'])\n"
            "    op.create_index('ix_t_sku', 't', ['sku'])\n"
            "    op.drop_table('t')\n"
        ),
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.tables == ()
    assert result.schema.constraints == ()
    assert result.schema.indexes == ()


def test_a_column_keyword_outside_the_modeled_set_is_ignored_not_fatal(tmp_path: Path) -> None:
    """`unique=True` on a `Column` is not modeled; the column itself still resolves."""
    path = _write(
        tmp_path,
        "rev.py",
        _upgrade_module(
            "    op.create_table('t', sa.Column('id', sa.Integer(), unique=True, nullable=False))\n"
        ),
    )
    result = parse_migrations([path], root=tmp_path)
    assert result.schema.unsupported == ()
    assert {c.name for c in result.schema.tables[0].columns} == {"id"}
