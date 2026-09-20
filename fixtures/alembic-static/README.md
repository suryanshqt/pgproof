# Alembic static-analysis fixtures

Synthetic, standalone Alembic revision modules used only by
`tests/unit/test_alembic_static.py` to exercise
`pgproof.adapters.repository.alembic_static`. Unlike `demo-broken/` and
`demo-clean/`, these are not runnable applications with an `EXPECTED.yaml`
oracle — they exist purely as AST input, several deliberately malformed
(a cycle, a missing predecessor, dynamic/unsupported constructs).

They are analysed as data, never imported: `pgproof`'s parser reads Python
AST without executing it, and this directory is excluded from Ruff and mypy
for the same reason `demo-broken/` and `demo-clean/` are — linting or
"fixing" a deliberately defective file would erase the defect it exists to
carry.

| Directory | Exercises |
|---|---|
| `linear/` | A single root-to-head chain; the common case |
| `branch_and_merge/` | Two heads from one root, then a merge revision |
| `cycle/` | Two revisions whose `down_revision`s point at each other |
| `missing_predecessor/` | A `down_revision` naming a revision that does not exist |
| `unsupported/` | A helper-wrapped call, `op.execute` (raw SQL and DML), a conditional, and a dynamic table name |
| `operations/` | Every operation kind in `docs/TECHNICAL_DESIGN.md` section 6 in one file |
