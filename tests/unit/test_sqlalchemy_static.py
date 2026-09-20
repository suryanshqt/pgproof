"""Static SQLAlchemy/SQLModel parsing against `fixtures/sqlalchemy-static/`."""

from pathlib import Path

from pgproof.adapters.repository.sqlalchemy_static import SqlAlchemyStaticResult, parse_models
from pgproof.domain.ir.code import Cardinality, LoadingStrategy
from pgproof.domain.ir.schema import ColumnIR, SchemaIR, TableIR

FIXTURES = Path(__file__).parents[2] / "fixtures" / "sqlalchemy-static"


def _parse(*relative_paths: str) -> SqlAlchemyStaticResult:
    root = FIXTURES
    paths = [root / relative for relative in relative_paths]
    return parse_models(paths, root=root)


def _table(schema: SchemaIR, name: str) -> TableIR:
    return next(t for t in schema.tables if t.name == name)


def _column(table: TableIR, name: str) -> ColumnIR:
    return next(c for c in table.columns if c.name == name)


# --------------------------------------------------------------------------- #
# SQLAlchemy 2.x declarative
# --------------------------------------------------------------------------- #
def test_declarative_v2_extracts_models_and_columns() -> None:
    result = _parse("declarative_v2/models.py")
    assert result.code.unsupported == ()
    class_names = {m.class_name for m in result.code.models}
    assert class_names == {"Account", "LoginSession"}

    accounts = _table(result.schema, "accounts")
    email = _column(accounts, "email")
    assert email.nullable is False
    assert email.data_type == "str"

    nickname = _column(accounts, "nickname")
    assert nickname.nullable is True

    assert {c.name for c in result.schema.constraints} == {
        "pk_accounts",
        "uq_accounts_email",
        "pk_sessions",
        "fk_sessions_account_id",
    }
    assert {i.name for i in result.schema.indexes} == {"ix_sessions_account_id"}


def test_a_base_class_with_no_tablename_is_not_a_model() -> None:
    result = _parse("declarative_v2/models.py")
    assert "Base" not in {m.class_name for m in result.code.models}


# --------------------------------------------------------------------------- #
# Async declarative: identical column declarations
# --------------------------------------------------------------------------- #
def test_async_declarative_parses_the_same_as_sync() -> None:
    result = _parse("declarative_async/models.py")
    assert result.code.unsupported == ()
    assert {m.class_name for m in result.code.models} == {"Widget"}
    widgets = _table(result.schema, "widgets")
    assert {c.name for c in widgets.columns} == {"id", "name"}


# --------------------------------------------------------------------------- #
# Classic Column() style
# --------------------------------------------------------------------------- #
def test_classic_column_style_extracts_models_and_constraints() -> None:
    result = _parse("classic/models.py")
    assert result.code.unsupported == ()
    products = _table(result.schema, "products")
    sku = _column(products, "sku")
    assert sku.data_type == "String(64)"
    assert sku.nullable is False

    assert {c.name for c in result.schema.constraints} == {
        "pk_products",
        "uq_products_sku",
        "pk_tags",
        "fk_tags_product_id",
    }


# --------------------------------------------------------------------------- #
# SQLModel Field() style
# --------------------------------------------------------------------------- #
def test_sqlmodel_style_extracts_models_and_constraints() -> None:
    result = _parse("sqlmodel/models.py")
    assert result.code.unsupported == ()
    customers = _table(result.schema, "customers")
    assert {c.name for c in customers.columns} == {"id", "name", "email", "is_active"}
    assert {c.name for c in result.schema.constraints} == {"pk_customers", "uq_customers_email"}
    assert {i.name for i in result.schema.indexes} == {"ix_customers_email"}


def test_sqlmodel_table_true_without_explicit_tablename_defaults_to_class_name(
    tmp_path: Path,
) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlmodel import Field, SQLModel\n"
        "class Widget(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert {t.name for t in result.schema.tables} == {"widget"}


# --------------------------------------------------------------------------- #
# Relationships
# --------------------------------------------------------------------------- #
def test_one_to_many_with_cascade_and_lazy_strategy() -> None:
    result = _parse("relationships/models.py")
    posts_rel = next(
        r for r in result.code.relationships if r.name == "posts" and r.back_populates == "author"
    )
    assert posts_rel.cardinality is Cardinality.ONE_TO_MANY
    assert posts_rel.cascade == ("all", "delete-orphan")
    assert posts_rel.loading_strategy is LoadingStrategy.SELECTIN


def test_many_to_one_from_the_foreign_key_holding_side() -> None:
    result = _parse("relationships/models.py")
    author_rel = next(
        r for r in result.code.relationships if r.name == "author" and r.back_populates == "posts"
    )
    assert author_rel.cardinality is Cardinality.MANY_TO_ONE
    assert author_rel.loading_strategy is LoadingStrategy.SELECT


def test_one_to_one_from_an_explicit_uselist_false() -> None:
    result = _parse("relationships/models.py")
    profile_rel = next(r for r in result.code.relationships if r.name == "profile")
    assert profile_rel.cardinality is Cardinality.ONE_TO_ONE


def test_many_to_many_resolves_the_secondary_table() -> None:
    result = _parse("relationships/models.py")
    tags_rel = next(
        r
        for r in result.code.relationships
        if r.name == "tags" and r.source_table.endswith("posts")
    )
    assert tags_rel.cardinality is Cardinality.MANY_TO_MANY
    assert tags_rel.secondary_table is not None
    assert "post_tags" in tags_rel.secondary_table


# --------------------------------------------------------------------------- #
# Unsupported constructs
# --------------------------------------------------------------------------- #
def test_every_unsupported_construct_is_reported_and_the_resolvable_ones_still_apply() -> None:
    result = _parse("unsupported/models.py")
    reasons = [u.reason for u in result.code.unsupported]
    assert any("dynamic/loop-generated class body statement" in r for r in reasons)
    assert any("not a direct Column/mapped_column/Field/relationship call" in r for r in reasons)
    assert any("non-literal argument" in r for r in reasons)
    # `id` still resolves even though its three siblings do not.
    reports = _table(result.schema, "reports")
    assert {c.name for c in reports.columns} == {"id"}


def test_a_dynamic_tablename_skips_the_class_but_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "TABLE_NAME = 'reports'\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class Report(Base):\n"
        "    __tablename__ = TABLE_NAME\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert result.code.models == ()
    assert result.schema.tables == ()
    assert any("__tablename__ is not a string literal" in u.reason for u in result.code.unsupported)


def test_a_plain_non_dunder_class_constant_is_reported_not_guessed(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class A(Base):\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    SOME_CONSTANT = 5\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert any(
        "not a recognized column/relationship statement" in u.reason
        for u in result.code.unsupported
    )
    assert {c.name for c in result.schema.tables[0].columns} == {"id"}


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_a_syntax_error_is_reported_not_raised(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("class Foo(:\n", encoding="utf-8")
    result = parse_models([broken], root=tmp_path)
    assert result.code.models == ()
    assert any(u.kind == "unparseable_module" for u in result.code.unsupported)


def test_a_module_with_no_models_is_empty_not_an_error(tmp_path: Path) -> None:
    path = tmp_path / "util.py"
    path.write_text("def helper():\n    pass\n", encoding="utf-8")
    result = parse_models([path], root=tmp_path)
    assert result.code.models == ()
    assert result.code.unsupported == ()


def test_a_class_with_bases_but_no_tablename_and_no_table_true_is_not_a_model(
    tmp_path: Path,
) -> None:
    path = tmp_path / "models.py"
    path.write_text("class Mixin:\n    created_at: int\n", encoding="utf-8")
    result = parse_models([path], root=tmp_path)
    assert result.code.models == ()


def test_a_relationship_target_not_found_among_parsed_models_is_unsupported(
    tmp_path: Path,
) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class Lonely(Base):\n"
        "    __tablename__ = 'lonely'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    ghost: Mapped['Ghost'] = relationship()\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert any("not found among parsed models" in u.reason for u in result.code.unsupported)


def test_a_relationship_with_a_kwargs_splat_is_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class A(Base):\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    opts = {}\n"
        "    other: Mapped['A'] = relationship(**opts)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert any(
        "relationship has a non-literal argument" in u.reason for u in result.code.unsupported
    )


# --------------------------------------------------------------------------- #
# Further coverage: statements/kwargs the golden fixtures do not exercise
# --------------------------------------------------------------------------- #
def test_a_docstring_in_a_model_body_is_not_flagged(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class A(Base):\n"
        "    '''An A.'''\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert result.code.unsupported == ()


def test_a_foreign_key_with_no_arguments_is_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "import sqlalchemy as sa\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class A(Base):\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    other_id: Mapped[int] = mapped_column(sa.ForeignKey())\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert any("non-literal argument" in u.reason for u in result.code.unsupported)


def test_a_mapped_column_kwargs_splat_is_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "OPTS = {}\n"
        "class A(Base):\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    other: Mapped[int] = mapped_column(**OPTS)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert any("non-literal argument" in u.reason for u in result.code.unsupported)


def test_a_malformed_foreign_key_target_with_no_dot_is_silently_skipped(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "import sqlalchemy as sa\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class A(Base):\n"
        "    __tablename__ = 'a'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    other_id: Mapped[int] = mapped_column(sa.ForeignKey('not_qualified'))\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert result.code.unsupported == ()
    assert {c.name for c in result.schema.constraints} == {"pk_a"}


def test_a_table_variable_with_a_non_literal_name_is_not_resolved(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "import sqlalchemy as sa\n"
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "NAME = 'link'\n"
        "link = sa.Table(NAME, Base.metadata)\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert result.code.models == ()  # no crash; nothing else to assert


def test_a_relationship_with_a_positional_target_and_no_annotation_is_unresolved_cardinality(
    tmp_path: Path,
) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class Author(Base):\n"
        "    __tablename__ = 'authors'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "class Book(Base):\n"
        "    __tablename__ = 'books'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    author = relationship('Author')\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    author_rel = next(r for r in result.code.relationships if r.name == "author")
    assert author_rel.cardinality is Cardinality.UNRESOLVED


def test_passive_deletes_and_non_literal_cascade_and_uselist(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "import sqlalchemy as sa\n"
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "SOME_CASCADE = 'all'\n"
        "SOME_USELIST = True\n"
        "class Author(Base):\n"
        "    __tablename__ = 'authors'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "class Book(Base):\n"
        "    __tablename__ = 'books'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    author_id: Mapped[int] = mapped_column(sa.ForeignKey('authors.id'))\n"
        "    author: Mapped['Author'] = relationship(\n"
        "        passive_deletes=True, cascade=SOME_CASCADE, uselist=SOME_USELIST\n"
        "    )\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    author_rel = next(r for r in result.code.relationships if r.name == "author")
    assert author_rel.passive_deletes is True
    assert author_rel.cascade == ()


def test_a_bare_sqlmodel_annotation_with_no_field_call_still_resolves(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlmodel import Field, SQLModel\n"
        "class Item(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    name: str\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    assert result.code.unsupported == ()
    item = result.schema.tables[0]
    name = next(c for c in item.columns if c.name == "name")
    assert name.nullable is False


def test_relationship_target_from_an_unquoted_mapped_class_reference(tmp_path: Path) -> None:
    path = tmp_path / "models.py"
    path.write_text(
        "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class Author(Base):\n"
        "    __tablename__ = 'authors'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "class Book(Base):\n"
        "    __tablename__ = 'books'\n"
        "    id: Mapped[int] = mapped_column(primary_key=True)\n"
        "    author: Mapped[Author | None] = relationship()\n",
        encoding="utf-8",
    )
    result = parse_models([path], root=tmp_path)
    author_rel = next(r for r in result.code.relationships if r.name == "author")
    assert author_rel.target_table.endswith("authors")
