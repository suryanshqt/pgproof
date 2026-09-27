"""`adapters.seeder.plan` against synthetic `SchemaIR` fixtures.

`docs/PR_ROADMAP.md`'s BE-23 accept criterion: "property tests for integrity,
repeatability, unrelated-stream stability, and explicit unsupported
constraints."
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pgproof.adapters.seeder.plan import (
    TableGenerationResult,
    build_table_order,
    generate_table_rows,
)
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    SchemaIR,
    SchemaProvenance,
    TableIR,
)

_P = SchemaProvenance.PHYSICAL_CATALOG
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)
_TENANTS = table_id("public", "tenants")
_USERS = table_id("public", "users")
_ORDERS = table_id("public", "orders")
_UNRELATED = table_id("public", "unrelated")


def _column(
    table: str,
    name: str,
    data_type: str,
    *,
    nullable: bool = True,
    default: str | None = None,
) -> ColumnIR:
    return ColumnIR(
        id=column_id(table, name),
        name=name,
        data_type=data_type,
        nullable=nullable,
        default_expression=default,
        provenance=_P,
    )


def _table(identity: str, name: str, *columns: ColumnIR) -> TableIR:
    return TableIR(id=identity, schema_name="public", name=name, provenance=_P, columns=columns)


def _primary_key(table: str, column: str) -> ConstraintIR:
    return ConstraintIR(
        name=f"pk_{column}",
        kind=ConstraintKind.PRIMARY_KEY,
        table=table,
        columns=(column_id(table, column),),
        provenance=_P,
    )


def _foreign_key(table: str, column: str, parent: str, parent_column: str) -> ConstraintIR:
    return ConstraintIR(
        name=f"fk_{table}_{column}",
        kind=ConstraintKind.FOREIGN_KEY,
        table=table,
        columns=(column_id(table, column),),
        referenced_table=parent,
        referenced_columns=(column_id(parent, parent_column),),
        provenance=_P,
    )


def _check(table: str, name: str, expression: str) -> ConstraintIR:
    return ConstraintIR(
        name=name,
        kind=ConstraintKind.CHECK,
        table=table,
        columns=(),
        expression=expression,
        provenance=_P,
    )


_ORDERS_TABLE = _table(
    _ORDERS,
    "orders",
    _column(_ORDERS, "id", "integer", nullable=False, default="nextval('orders_id_seq'::regclass)"),
    _column(_ORDERS, "tenant_id", "integer", nullable=False),
    _column(_ORDERS, "reference", "character varying(64)", nullable=False),
    _column(_ORDERS, "status", "character varying(32)", nullable=False),
    _column(_ORDERS, "total_cents", "integer", nullable=False),
    _column(_ORDERS, "paid", "boolean", nullable=False),
    _column(_ORDERS, "created_at", "timestamp with time zone", nullable=False),
    _column(_ORDERS, "note", "text"),
)

_TENANTS_TABLE = _table(
    _TENANTS,
    "tenants",
    _column(
        _TENANTS, "id", "integer", nullable=False, default="nextval('tenants_id_seq'::regclass)"
    ),
    _column(_TENANTS, "slug", "character varying(64)", nullable=False),
)

_SCHEMA = SchemaIR(
    provenance=_P,
    tables=(_TENANTS_TABLE, _ORDERS_TABLE),
    constraints=(
        _primary_key(_TENANTS, "id"),
        _primary_key(_ORDERS, "id"),
        _foreign_key(_ORDERS, "tenant_id", _TENANTS, "id"),
        ConstraintIR(
            name="uq_orders_reference",
            kind=ConstraintKind.UNIQUE,
            table=_ORDERS,
            columns=(column_id(_ORDERS, "reference"),),
            provenance=_P,
        ),
        _check(
            _ORDERS,
            "ck_orders_status",
            "((status)::text = ANY ((ARRAY['pending'::character varying, "
            "'paid'::character varying])::text[]))",
        ),
        _check(_ORDERS, "ck_orders_total", "total_cents >= 100 AND total_cents <= 900"),
    ),
)

_POOL = {_TENANTS: (1, 2, 3, 4, 5)}


def _generate(
    schema: SchemaIR = _SCHEMA,
    *,
    table: TableIR = _ORDERS_TABLE,
    seed: int = 7,
    row_count: int = 40,
    existing: dict[str, frozenset[object]] | None = None,
) -> TableGenerationResult:
    return generate_table_rows(
        table,
        schema,
        global_seed=seed,
        generator_version=1,
        epoch=_EPOCH,
        row_count=row_count,
        parent_key_pools=_POOL,
        existing_unique_values=existing or {},
    )


def test_two_calls_with_the_same_seed_produce_identical_rows() -> None:
    assert _generate().rows == _generate().rows


def test_a_different_seed_produces_different_rows() -> None:
    assert _generate(seed=7).rows != _generate(seed=8).rows


def test_an_unrelated_table_does_not_shift_this_tables_streams() -> None:
    unrelated = _table(
        _UNRELATED,
        "unrelated",
        _column(_UNRELATED, "id", "integer", nullable=False),
        _column(_UNRELATED, "label", "text", nullable=False),
    )
    widened = _SCHEMA.model_copy(
        update={
            "tables": (*_SCHEMA.tables, unrelated),
            "constraints": (*_SCHEMA.constraints, _primary_key(_UNRELATED, "id")),
        }
    )
    assert _generate(widened).rows == _generate().rows


def test_generated_foreign_key_values_come_only_from_the_parent_pool() -> None:
    values = {row["tenant_id"] for row in _generate().rows}
    assert values <= set(_POOL[_TENANTS])


def test_a_serial_primary_key_is_left_to_the_database_default() -> None:
    result = _generate()
    assert all("id" not in row for row in result.rows)
    strategies = {a.column: a.strategy for a in result.assumptions}
    assert strategies[column_id(_ORDERS, "id")] == "database_default"


def test_unique_column_values_are_distinct_and_avoid_existing_rows() -> None:
    reserved = frozenset({f"reference-{index:08d}" for index in range(1, 200)})
    result = _generate(existing={column_id(_ORDERS, "reference"): reserved})
    values = [row["reference"] for row in result.rows]
    assert len(set(values)) == len(values)
    assert not set(values) & reserved


def test_every_assumption_names_the_tier_actually_used() -> None:
    strategies = {a.column: (a.strategy, a.inferred) for a in _generate().assumptions}
    assert strategies == {
        column_id(_ORDERS, "id"): ("database_default", False),
        column_id(_ORDERS, "tenant_id"): ("foreign_key", False),
        column_id(_ORDERS, "reference"): ("unique_sequential_text", False),
        column_id(_ORDERS, "status"): ("check_recognized_set", False),
        column_id(_ORDERS, "total_cents"): ("check_recognized_range", False),
        column_id(_ORDERS, "paid"): ("boolean", False),
        column_id(_ORDERS, "created_at"): ("timestamp_heuristic", True),
        column_id(_ORDERS, "note"): ("uniform_fallback", True),
    }


def test_a_timestamp_heuristic_never_generates_a_moment_after_the_epoch() -> None:
    moments = [row["created_at"] for row in _generate().rows]
    assert all(_EPOCH - timedelta(days=365) <= m <= _EPOCH for m in moments)  # type: ignore[operator]


def test_an_email_column_uses_the_reserved_test_tld() -> None:
    table = _table(
        _USERS, "users", _column(_USERS, "email", "character varying(320)", nullable=False)
    )
    schema = SchemaIR(provenance=_P, tables=(table,))
    values = [row["email"] for row in _generate(schema, table=table, row_count=3).rows]
    assert values == ["user0@example.test", "user1@example.test", "user2@example.test"]


@settings(max_examples=25, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**32))
def test_a_recognized_set_check_only_ever_generates_a_listed_literal(seed: int) -> None:
    values = {row["status"] for row in _generate(seed=seed, row_count=60).rows}
    assert values <= {"pending", "paid"}


@settings(max_examples=25, deadline=None)
@given(
    low=st.integers(min_value=-10_000, max_value=10_000),
    span=st.integers(min_value=0, max_value=5_000),
    seed=st.integers(min_value=0, max_value=2**32),
)
def test_a_recognized_range_check_only_ever_generates_values_inside_it(
    low: int, span: int, seed: int
) -> None:
    high = low + span
    table = _table(_ORDERS, "orders", _column(_ORDERS, "amount", "integer", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck_amount", f"amount >= {low} AND amount <= {high}"),),
    )
    result = _generate(schema, table=table, seed=seed, row_count=30)
    assert {a.strategy for a in result.assumptions} == {"check_recognized_range"}
    assert all(low <= row["amount"] <= high for row in result.rows)  # type: ignore[operator]


def test_an_unrecognized_check_expression_is_reported_exactly_once() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "name", "text", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck_name", "length(name) > 3"),),
    )
    result = _generate(schema, table=table, row_count=5)
    assert [c.kind for c in result.unsupported] == ["unsupported_check_constraint"]
    assert result.unsupported[0].reason == "length(name) > 3"
    # The column still gets a tier-4 value: an unenforced check on a column that
    # can hold one is reported, not a reason to drop the table.
    assert len(result.rows) == 5


def test_a_not_null_column_of_an_unrecognized_type_drops_the_whole_table() -> None:
    table = _table(
        _ORDERS,
        "orders",
        _column(_ORDERS, "total_cents", "integer", nullable=False),
        _column(_ORDERS, "payload", "jsonb", nullable=False),
    )
    schema = SchemaIR(provenance=_P, tables=(table,))
    result = _generate(schema, table=table, row_count=5)
    assert result.rows == ()
    assert [c.kind for c in result.unsupported] == ["unsupported_column_type"]


def test_a_nullable_column_of_an_unrecognized_type_is_generated_as_null() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "payload", "jsonb"))
    schema = SchemaIR(provenance=_P, tables=(table,))
    result = _generate(schema, table=table, row_count=3)
    assert [row["payload"] for row in result.rows] == [None, None, None]
    assert result.unsupported == ()
    assert result.assumptions[0].strategy == "null_fallback"


def test_a_not_null_foreign_key_with_an_empty_parent_pool_drops_the_table() -> None:
    result = generate_table_rows(
        _ORDERS_TABLE,
        _SCHEMA,
        global_seed=1,
        generator_version=1,
        epoch=_EPOCH,
        row_count=5,
        parent_key_pools={},
        existing_unique_values={},
    )
    assert result.rows == ()
    assert [c.kind for c in result.unsupported] == ["unsupported_column_type"]


def test_a_composite_foreign_key_is_reported_unsupported() -> None:
    table = _table(
        _ORDERS,
        "orders",
        _column(_ORDERS, "tenant_id", "integer"),
        _column(_ORDERS, "user_id", "integer"),
    )
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(
            ConstraintIR(
                name="fk_orders_tenant_user",
                kind=ConstraintKind.FOREIGN_KEY,
                table=_ORDERS,
                columns=(column_id(_ORDERS, "tenant_id"), column_id(_ORDERS, "user_id")),
                referenced_table=_TENANTS,
                referenced_columns=(column_id(_TENANTS, "id"), column_id(_TENANTS, "id")),
                provenance=_P,
            ),
        ),
    )
    result = _generate(schema, table=table, row_count=2)
    assert [c.kind for c in result.unsupported] == ["unsupported_composite_foreign_key"]


def test_a_deferred_column_is_generated_as_null_on_this_pass() -> None:
    result = generate_table_rows(
        _ORDERS_TABLE,
        _SCHEMA,
        global_seed=1,
        generator_version=1,
        epoch=_EPOCH,
        row_count=4,
        parent_key_pools=_POOL,
        existing_unique_values={},
        defer_columns=frozenset({column_id(_ORDERS, "tenant_id")}),
    )
    assert [row["tenant_id"] for row in result.rows] == [None] * 4
    strategies = {a.column: a.strategy for a in result.assumptions}
    assert strategies[column_id(_ORDERS, "tenant_id")] == "deferred_foreign_key"


@pytest.mark.parametrize(
    ("data_type", "expected"),
    [
        ("numeric(10,2)", "uniform_fallback"),
        ("double precision", "uniform_fallback"),
        ("date", "uniform_fallback"),
        ("uuid", "null_fallback"),
        ("integer[]", "null_fallback"),
    ],
)
def test_tier_four_covers_the_recognized_families_and_nothing_else(
    data_type: str, expected: str
) -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "value", data_type))
    schema = SchemaIR(provenance=_P, tables=(table,))
    result = _generate(schema, table=table, row_count=3)
    assert result.assumptions[0].strategy == expected


def _chain_schema() -> SchemaIR:
    tables = (
        _table(_TENANTS, "tenants", _column(_TENANTS, "id", "integer", nullable=False)),
        _table(
            _USERS,
            "users",
            _column(_USERS, "id", "integer", nullable=False),
            _column(_USERS, "tenant_id", "integer", nullable=False),
        ),
        _table(
            _ORDERS,
            "orders",
            _column(_ORDERS, "id", "integer", nullable=False),
            _column(_ORDERS, "user_id", "integer", nullable=False),
        ),
    )
    return SchemaIR(
        provenance=_P,
        tables=tables,
        constraints=(
            _foreign_key(_USERS, "tenant_id", _TENANTS, "id"),
            _foreign_key(_ORDERS, "user_id", _USERS, "id"),
        ),
    )


def test_an_acyclic_chain_orders_parents_before_children() -> None:
    result = build_table_order(_chain_schema())
    assert result.order == (_TENANTS, _USERS, _ORDERS)
    assert result.unsupported == ()
    assert result.deferred_columns == ()


def _self_referential_schema(*, nullable: bool) -> SchemaIR:
    table = _table(
        _USERS,
        "users",
        _column(_USERS, "id", "integer", nullable=False),
        _column(_USERS, "manager_id", "integer", nullable=nullable),
    )
    return SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_foreign_key(_USERS, "manager_id", _USERS, "id"),),
    )


def test_a_nullable_self_referential_cycle_is_kept_and_deferred() -> None:
    result = build_table_order(_self_referential_schema(nullable=True))
    assert result.order == (_USERS,)
    assert result.deferred_columns == (column_id(_USERS, "manager_id"),)
    assert result.unsupported == ()


def test_a_not_null_self_referential_cycle_is_dropped_explicitly() -> None:
    result = build_table_order(_self_referential_schema(nullable=False))
    assert result.order == ()
    assert [c.kind for c in result.unsupported] == ["fk_cycle"]
    assert _USERS in result.unsupported[0].reason


def test_a_not_null_two_table_cycle_is_dropped_explicitly() -> None:
    tables = (
        _table(
            _USERS,
            "users",
            _column(_USERS, "id", "integer", nullable=False),
            _column(_USERS, "order_id", "integer", nullable=False),
        ),
        _table(
            _ORDERS,
            "orders",
            _column(_ORDERS, "id", "integer", nullable=False),
            _column(_ORDERS, "user_id", "integer", nullable=False),
        ),
    )
    schema = SchemaIR(
        provenance=_P,
        tables=tables,
        constraints=(
            _foreign_key(_USERS, "order_id", _ORDERS, "id"),
            _foreign_key(_ORDERS, "user_id", _USERS, "id"),
        ),
    )
    result = build_table_order(schema)
    assert result.order == ()
    assert [c.kind for c in result.unsupported] == ["fk_cycle"]


def test_a_nullable_two_table_cycle_is_kept_with_both_columns_deferred() -> None:
    tables = (
        _table(
            _USERS,
            "users",
            _column(_USERS, "id", "integer", nullable=False),
            _column(_USERS, "order_id", "integer"),
        ),
        _table(
            _ORDERS,
            "orders",
            _column(_ORDERS, "id", "integer", nullable=False),
            _column(_ORDERS, "user_id", "integer"),
        ),
    )
    schema = SchemaIR(
        provenance=_P,
        tables=tables,
        constraints=(
            _foreign_key(_USERS, "order_id", _ORDERS, "id"),
            _foreign_key(_ORDERS, "user_id", _USERS, "id"),
        ),
    )
    result = build_table_order(schema)
    assert set(result.order) == {_USERS, _ORDERS}
    assert result.deferred_columns == (
        column_id(_ORDERS, "user_id"),
        column_id(_USERS, "order_id"),
    )


def test_an_or_chain_of_equalities_is_a_recognized_set() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "status", "text", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck", "status = 'new' OR status = 'old'"),),
    )
    result = _generate(schema, table=table, row_count=20)
    assert result.unsupported == ()
    assert {row["status"] for row in result.rows} <= {"new", "old"}


def test_a_between_check_is_a_recognized_range() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "quantity", "integer", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck", "quantity BETWEEN 3 AND 9"),),
    )
    result = _generate(schema, table=table, row_count=20)
    assert result.unsupported == ()
    assert all(3 <= row["quantity"] <= 9 for row in result.rows)  # type: ignore[operator]


def test_a_one_sided_check_still_respects_its_stated_bound() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "price", "integer", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck", "price > 500"),),
    )
    result = _generate(schema, table=table, row_count=20)
    assert all(row["price"] > 500 for row in result.rows)  # type: ignore[operator]


@pytest.mark.parametrize(
    "expression",
    [
        "status NOT IN ('a', 'b')",
        "status IN (SELECT slug FROM tenants)",
        "quantity > 0 OR status = 'a'",
        "status LIKE 'a%'",
        "amount > 5 AND amount < 6",
        "not valid sql at all",
    ],
)
def test_an_unrecognized_check_shape_falls_through_to_a_lower_tier(expression: str) -> None:
    table = _table(
        _ORDERS,
        "orders",
        _column(_ORDERS, "status", "text", nullable=False),
        _column(_ORDERS, "quantity", "integer", nullable=False),
        _column(_ORDERS, "amount", "integer", nullable=False),
    )
    schema = SchemaIR(
        provenance=_P, tables=(table,), constraints=(_check(_ORDERS, "ck", expression),)
    )
    result = _generate(schema, table=table, row_count=3)
    assert [c.kind for c in result.unsupported] == ["unsupported_check_constraint"]
    assert {a.strategy for a in result.assumptions} == {"uniform_fallback"}


def test_a_zero_row_count_generates_nothing_but_still_reports_assumptions() -> None:
    result = _generate(row_count=0)
    assert result.rows == ()
    assert len(result.assumptions) == len(_ORDERS_TABLE.columns)


def test_a_boolean_literal_set_check_is_recognized() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "flag", "boolean", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck", "flag = true OR flag = false"),),
    )
    result = _generate(schema, table=table, row_count=5)
    assert result.unsupported == ()
    # `boolean` is itself a tier-2 fact and wins over the check that repeats it.
    assert result.assumptions[0].strategy == "boolean"


def test_a_float_literal_range_check_is_not_recognized() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "price", "numeric(10,2)", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(_check(_ORDERS, "ck", "price >= 1.5 AND price <= 9.5"),),
    )
    result = _generate(schema, table=table, row_count=5)
    assert [c.kind for c in result.unsupported] == ["unsupported_check_constraint"]
    assert result.assumptions[0].strategy == "uniform_fallback"


def test_an_integer_unique_column_without_a_sequence_gets_distinct_values() -> None:
    table = _table(_ORDERS, "orders", _column(_ORDERS, "code", "bigint", nullable=False))
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(
            ConstraintIR(
                name="uq_orders_code",
                kind=ConstraintKind.UNIQUE,
                table=_ORDERS,
                columns=(column_id(_ORDERS, "code"),),
                provenance=_P,
            ),
        ),
    )
    result = _generate(
        schema,
        table=table,
        row_count=30,
        existing={column_id(_ORDERS, "code"): frozenset({1, 2, 3})},
    )
    values = [row["code"] for row in result.rows]
    assert result.assumptions[0].strategy == "unique_sequential_int"
    assert len(set(values)) == 30
    assert not set(values) & {1, 2, 3}


def test_an_identity_column_is_never_copied_even_without_a_unique_constraint() -> None:
    column = ColumnIR(
        id=column_id(_ORDERS, "id"),
        name="id",
        data_type="integer",
        nullable=False,
        is_identity=True,
        provenance=_P,
    )
    table = _table(_ORDERS, "orders", column)
    schema = SchemaIR(provenance=_P, tables=(table,))
    result = _generate(schema, table=table, row_count=3)
    assert result.rows == ({}, {}, {})
    assert result.assumptions[0].strategy == "database_default"


def test_a_unique_column_of_a_family_without_a_sequence_falls_through() -> None:
    table = _table(
        _ORDERS, "orders", _column(_ORDERS, "at", "timestamp with time zone", nullable=False)
    )
    schema = SchemaIR(
        provenance=_P,
        tables=(table,),
        constraints=(
            ConstraintIR(
                name="uq_orders_at",
                kind=ConstraintKind.UNIQUE,
                table=_ORDERS,
                columns=(column_id(_ORDERS, "at"),),
                provenance=_P,
            ),
        ),
    )
    result = _generate(schema, table=table, row_count=3)
    assert result.assumptions[0].strategy == "uniform_fallback"
    # A collision risks a real COPY failure, since this family has no
    # distinctness strategy — reported, not silently risked.
    assert [c.kind for c in result.unsupported] == ["unsupported_unique_constraint"]
