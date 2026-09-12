# pgproof ground-truth fixtures

These directories are the oracle the rule engine is judged against. They are
analysed as **data**, never imported or installed by the pgproof test suite, and
they are excluded from this repository's Ruff, mypy, and pytest configuration.

## Contents

| Path | Purpose |
|---|---|
| `demo-broken/` | Multi-tenant storefront carrying four planted design defects |
| `demo-clean/` | The same storefront with those four defects corrected |
| `demo-*/EXPECTED.yaml` | What pgproof must conclude, and the evidence category it may claim |
| `demo-*/dataset.sql` | Deterministic data for hand measurement |
| `demo-broken/MEASUREMENT.md` | Hand-measured baseline establishing the cases are real |
| `benchmark-corpus.yaml` | Pinned external repositories and the pinned PostgreSQL identity |

## The four planted cases

| ID | Kind | Defect in `demo-broken` | Fix in `demo-clean` |
|---|---|---|---|
| `TENANT-001` | Tenant ownership | `Order.tenant_id` is a foreign key in the model; migration `6a912ef4c1b8` creates the column without the constraint | Migration creates `fk_orders_tenant_id` |
| `IDX-001` | Single-column index | `orders.user_id` is an unindexed foreign key that `list_user_orders` filters on | Migration creates `ix_orders_user_id` |
| `IDX-002` | Composite index | No index supports `(tenant_id, status)` filtering with a `created_at DESC` sort | Migration creates `ix_orders_tenant_status_created` |
| `NPLUS1-001` | Observed N+1 | `order_totals_by_item` lazily loads `order.items`, one child query per order | `selectinload(Order.items)` |

## The fixture pair invariant

`demo-clean` must differ from `demo-broken` in the four planted cases and in
nothing else:

```bash
diff -rq fixtures/demo-broken fixtures/demo-clean
```

Only `app/models.py`, `app/repositories.py`,
`migrations/versions/0002_create_orders.py`, `pyproject.toml`, and
`EXPECTED.yaml` may differ, plus `MEASUREMENT.md` existing only in
`demo-broken`. `tests/unit/test_fixture_oracle.py` enforces this. A defect that
leaks into `demo-clean` destroys the clean control, and an unrelated difference
lets a rule pass for the wrong reason.

## Why `demo-clean` matters more than `demo-broken`

Finding a planted defect proves a rule fires. Only the clean control proves the
rule is not firing on everything. `demo-clean` is therefore deliberately clean
beyond the four cases: `orders.status` carries a check constraint, money is
integer cents, `users` and `products` are uniquely constrained per tenant, and
`order_items.order_id` is indexed in both fixtures. Each
`EXPECTED.yaml` records these as `must_not_report` entries so a future rule
cannot quietly start flagging them.

## What these fixtures do not contain

- No performance number. Measured values live only in `MEASUREMENT.md`, and
  `EXPECTED.yaml` is asserted to contain none.
- No frozen pgproof artifact. `SchemaIR`, `WorkloadIR`, and graph fixtures arrive
  with the roadmap items that define those contracts.
- No write-cost measurement. That is `BE-28`.
- No cross-platform reproduction. That is `BE-30`.
