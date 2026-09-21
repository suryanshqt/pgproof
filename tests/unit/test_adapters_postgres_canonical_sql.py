from pgproof.adapters.postgres.canonical_sql import render_canonical_schema_sql
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    IndexIR,
    IndexKeyIR,
    ReferentialAction,
    SchemaIR,
    SchemaProvenance,
    SortDirection,
    TableIR,
    UnsupportedConstruct,
)

_P = SchemaProvenance.PHYSICAL_CATALOG


def test_empty_schema_renders_to_an_empty_string() -> None:
    assert render_canonical_schema_sql(SchemaIR(provenance=_P)) == ""


def test_renders_a_table_with_a_not_null_and_a_default() -> None:
    table = TableIR(
        id="public.tenants",
        schema_name="public",
        name="tenants",
        provenance=_P,
        columns=(
            ColumnIR(
                id="public.tenants.created_at",
                name="created_at",
                data_type="timestamp with time zone",
                nullable=False,
                default_expression="now()",
                provenance=_P,
            ),
            ColumnIR(
                id="public.tenants.note",
                name="note",
                data_type="text",
                nullable=True,
                provenance=_P,
            ),
        ),
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, tables=(table,)))
    assert text == (
        'CREATE TABLE "public"."tenants" (\n'
        '    "created_at" timestamp with time zone NOT NULL DEFAULT now(),\n'
        '    "note" text\n'
        ");\n"
    )


def test_a_sequence_backed_default_is_never_rendered() -> None:
    """`SchemaIR` has no sequence model; emitting `DEFAULT nextval(...)` for a
    sequence that will not exist in a fresh database is invalid SQL."""
    table = TableIR(
        id="public.tenants",
        schema_name="public",
        name="tenants",
        provenance=_P,
        columns=(
            ColumnIR(
                id="public.tenants.id",
                name="id",
                data_type="integer",
                nullable=False,
                default_expression="nextval('tenants_id_seq'::regclass)",
                provenance=_P,
            ),
        ),
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, tables=(table,)))
    assert "nextval" not in text
    assert text == 'CREATE TABLE "public"."tenants" (\n    "id" integer NOT NULL\n);\n'


def test_renders_a_primary_key_unique_and_check_constraint() -> None:
    constraints = (
        ConstraintIR(
            name="orders_pkey",
            kind=ConstraintKind.PRIMARY_KEY,
            table="public.orders",
            columns=("public.orders.id",),
            provenance=_P,
        ),
        ConstraintIR(
            name="uq_orders_slug",
            kind=ConstraintKind.UNIQUE,
            table="public.orders",
            columns=("public.orders.slug",),
            provenance=_P,
        ),
        ConstraintIR(
            name="orders_amount_check",
            kind=ConstraintKind.CHECK,
            table="public.orders",
            expression="(amount > 0)",
            provenance=_P,
        ),
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, constraints=constraints))
    assert 'ADD CONSTRAINT "orders_pkey" PRIMARY KEY ("id");' in text
    assert 'ADD CONSTRAINT "uq_orders_slug" UNIQUE ("slug");' in text
    assert 'ADD CONSTRAINT "orders_amount_check" CHECK (amount > 0);' in text


def test_renders_a_foreign_key_with_actions() -> None:
    fk = ConstraintIR(
        name="fk_orders_tenant",
        kind=ConstraintKind.FOREIGN_KEY,
        table="public.orders",
        columns=("public.orders.tenant_id",),
        referenced_table="public.tenants",
        referenced_columns=("public.tenants.id",),
        on_delete=ReferentialAction.CASCADE,
        on_update=ReferentialAction.RESTRICT,
        provenance=_P,
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, constraints=(fk,)))
    assert (
        'ALTER TABLE "public"."orders" ADD CONSTRAINT "fk_orders_tenant" '
        'FOREIGN KEY ("tenant_id") REFERENCES "public"."tenants" ("id") '
        "ON DELETE CASCADE ON UPDATE RESTRICT;"
    ) in text


def test_a_foreign_key_without_explicit_actions_omits_the_on_clauses() -> None:
    fk = ConstraintIR(
        name="fk_orders_tenant",
        kind=ConstraintKind.FOREIGN_KEY,
        table="public.orders",
        columns=("public.orders.tenant_id",),
        referenced_table="public.tenants",
        referenced_columns=("public.tenants.id",),
        provenance=_P,
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, constraints=(fk,)))
    assert "ON DELETE" not in text
    assert "ON UPDATE" not in text
    assert text.strip().endswith('REFERENCES "public"."tenants" ("id");')


def test_a_not_null_constraint_kind_renders_nothing_extra() -> None:
    constraint = ConstraintIR(
        name="orders_id_not_null",
        kind=ConstraintKind.NOT_NULL,
        table="public.orders",
        provenance=_P,
    )
    assert render_canonical_schema_sql(SchemaIR(provenance=_P, constraints=(constraint,))) == ""


def test_renders_a_plain_and_an_expression_index_with_direction_and_predicate() -> None:
    plain = IndexIR(
        name="ix_orders_tenant_id",
        table="public.orders",
        keys=(IndexKeyIR(column="public.orders.tenant_id", direction=SortDirection.DESC),),
        provenance=_P,
    )
    expr = IndexIR(
        name="ix_orders_partial",
        table="public.orders",
        is_unique=True,
        keys=(IndexKeyIR(expression="lower(email)"),),
        predicate="(active)",
        provenance=_P,
    )
    text = render_canonical_schema_sql(SchemaIR(provenance=_P, indexes=(plain, expr)))
    assert (
        'CREATE INDEX "ix_orders_tenant_id" ON "public"."orders" USING btree ("tenant_id" DESC);'
        in text
    )
    assert (
        'CREATE UNIQUE INDEX "ix_orders_partial" ON "public"."orders" USING btree '
        "(lower(email)) WHERE (active);"
    ) in text


def test_unsupported_constructs_are_not_rendered_but_do_not_break_anything() -> None:
    schema = SchemaIR(
        provenance=_P, unsupported=(UnsupportedConstruct(kind="view", reason="not supported"),)
    )
    assert render_canonical_schema_sql(schema) == ""
