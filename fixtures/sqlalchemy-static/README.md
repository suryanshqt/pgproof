# SQLAlchemy/SQLModel static-analysis fixtures

Synthetic, standalone model modules used only by
`tests/unit/test_sqlalchemy_static.py` to exercise
`pgproof.adapters.repository.sqlalchemy_static`. Like `alembic-static/`,
these are analysed as data, never imported — excluded from Ruff and mypy for
the same reason `demo-broken/`/`demo-clean/` are: linting or "fixing" a
deliberately unsupported construct would erase the defect it exists to
carry.

| Directory | Exercises |
|---|---|
| `declarative_v2/` | SQLAlchemy 2.x `Mapped[]`/`mapped_column()`, sync |
| `declarative_async/` | The same declarations under an async session base |
| `classic/` | Legacy `Column(...)` mapping style |
| `sqlmodel/` | SQLModel's `Field(...)` style, `table=True` |
| `relationships/` | one-to-many, many-to-many with `secondary`, `back_populates`, `cascade`, `lazy`, and `uselist=False` |
| `unsupported/` | A helper-wrapped column, a non-literal `ForeignKey` target, and a loop-generated column, in a table that itself resolves. A dynamic `__tablename__` gates the whole class instead, and is covered inline in the test file. |
