# Hand-measured baseline for demo-broken

These numbers were produced by hand, before any pgproof measurement code exists.
They establish that the two planted index cases and the planted N+1 are real and
that their direction of effect reproduces. They are **not** a proof bundle, not a
pgproof artifact, and not a production prediction.

## Environment

| Item | Value |
|---|---|
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg13+2), `postgres:17` |
| Image digest | `sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675` |
| Host | macOS arm64 (Apple silicon), Docker Desktop 28.3.2 |
| Client | psycopg 3.3.5, SQLAlchemy 2.0.52, Alembic 1.20.0 |
| Session settings | `max_parallel_workers_per_gather = 0`, `jit = off`, `statement_timeout = '30s'` |

Linux amd64 numbers are deliberately absent. Cross-platform reproduction is a
`BE-30` gate, not a `BE-02` claim.

## Dataset

Deterministic, derived arithmetically from `generate_series` so no `random()` or
clock call can shift a stream. See `dataset.sql` in this directory.

| Table | Rows |
|---|---|
| tenants | 200 |
| users | 20,000 |
| products | 2,000 |
| orders | 400,000 |
| order_items | 800,000 |

Status distribution: `paid` 240,000, `pending` 80,000, `shipped` 40,000,
`cancelled` 40,000. All four statuses occur in every tenant. `orders` occupies
32 MB. Probe values: tenant 7 has 2,000 orders of which 1,200 are `paid`; user 42
has 20 orders. `SELECT sum(total_cents) FROM orders` returns `1697400000`; a
different value means the dataset is not the one these numbers came from.

## Protocol

Per `docs/TECHNICAL_DESIGN.md` section 20: 3 discarded warmups, then 7 samples
timed around statement execution plus a full fetch. Median and IQR are reported;
no p95 is reported, because 7 samples cannot support one. Each case runs
control A1, then the physical index treatment B, then A2 with the index dropped,
so cache and environment drift are visible.

## IDX-001 — single-column B-tree on orders(user_id)

```sql
SELECT id, tenant_id, user_id, status, total_cents, created_at
FROM orders WHERE user_id = 42;              -- 20 rows
CREATE INDEX ix_orders_user_id ON orders (user_id);
```

| Run | A1 median | A1 IQR | B median | A2 median | A1 to A2 drift | Absolute saving |
|---|---|---|---|---|---|---|
| 1 | 7.81 ms | 24.2% | 0.21 ms | 7.54 ms | 3.46% | 7.60 ms |
| 2 | 7.47 ms | 4.9% | 0.27 ms | 7.52 ms | 0.67% | 7.20 ms |
| 3 | 7.53 ms | 1.6% | 0.17 ms | 7.64 ms | 1.46% | 7.36 ms |

Plan shape changes from `Seq Scan on orders` to
`Bitmap Heap Scan on orders -> Bitmap Index Scan using ix_orders_user_id`.
Index build 0.05 s, index size 3056 kB.

Run 1's control IQR of 24.2% exceeds the 20% `max_iqr_fraction` in
`docs/TECHNICAL_DESIGN.md` section 3, so under the product's own variance gate
run 1 would be suppressed as inconclusive rather than reported. It is kept in this
table because a baseline document that silently deletes its noisy run is not a
baseline. Runs 2 and 3 satisfy the gate.

## IDX-002 — composite B-tree on orders(tenant_id, status, created_at DESC)

```sql
SELECT id, tenant_id, user_id, status, total_cents, created_at
FROM orders WHERE tenant_id = 7 AND status = 'paid'
ORDER BY created_at DESC LIMIT 20;
CREATE INDEX ix_orders_tenant_status_created
  ON orders (tenant_id, status, created_at DESC);
```

| Run | A1 median | A1 IQR | B median | A2 median | A1 to A2 drift | Absolute saving |
|---|---|---|---|---|---|---|
| 1 | 7.97 ms | 2.9% | 0.24 ms | 7.99 ms | 0.25% | 7.73 ms |
| 2 | 7.78 ms | 3.3% | 0.19 ms | 7.96 ms | 2.31% | 7.59 ms |
| 3 | 8.06 ms | 4.0% | 0.16 ms | 8.08 ms | 0.25% | 7.90 ms |

Plan shape changes from `Limit -> Sort -> Seq Scan on orders` to
`Limit -> Index Scan using ix_orders_tenant_status_created`, so the sort is
eliminated rather than merely accelerated. Index build 0.15 s, index size 16 MB.

Treatment IQR ranges from 4.0% to 37.1% across runs. At a 0.2 ms median, relative
spread is dominated by timer and scheduling granularity, so the IQR gate is not
informative for the treatment arm. Absolute saving is the reportable quantity,
which is also why `docs/PRODUCT_SPEC.md` section 12 sorts by absolute time saved.

## NPLUS1-001 — observed N+1 in order_totals_by_item

Statements were counted with a SQLAlchemy `before_cursor_execute` listener while
calling `order_totals_by_item(session, 7, "paid")` in each fixture.

| Fixture | Orders returned | SELECT statements | Totals checksum |
|---|---|---|---|
| demo-broken | 20 | 21 | 199840 |
| demo-clean | 20 | 2 | 199840 |

The first three order ids are `376007, 40207, 104407` in both fixtures, in the
same sequence, and the checksums agree. The `selectinload` treatment therefore
satisfies a result-equivalence contract while reducing statement count from
1 + N to a fixed 2. No wall-clock claim is made for this case; the finding is the
amplification, and `BE-29` owns its timed verification.

## Write cost

Not measured. The index write-cost guard is `BE-28`. Nothing in this document may
be read as a keep-or-drop verdict for either index.

## Reproducing this by hand

```bash
docker run -d --name pgproof-fixture-pg \
  -e POSTGRES_PASSWORD=fixture -e POSTGRES_USER=fixture -e POSTGRES_DB=postgres \
  -p 55432:5432 postgres:17
docker exec pgproof-fixture-pg psql -U fixture -d postgres -c 'CREATE DATABASE demo_broken;'

uv venv /tmp/fixture-venv
VIRTUAL_ENV=/tmp/fixture-venv uv pip install 'sqlalchemy>=2.0' 'alembic>=1.13' 'psycopg[binary]>=3.1' pytest

export DATABASE_URL='postgresql+psycopg://fixture:fixture@127.0.0.1:55432/demo_broken'
/tmp/fixture-venv/bin/alembic upgrade head
docker cp dataset.sql pgproof-fixture-pg:/tmp/dataset.sql
docker exec pgproof-fixture-pg psql -U fixture -d demo_broken -v ON_ERROR_STOP=1 -f /tmp/dataset.sql

/tmp/fixture-venv/bin/python -m pytest
docker rm -f pgproof-fixture-pg
```

Confirm the planted schema defects directly:

```sql
SELECT conname FROM pg_constraint WHERE conrelid = 'orders'::regclass AND contype = 'f';
-- demo-broken lists fk_orders_user_id only; fk_orders_tenant_id is absent.
SELECT indexname FROM pg_indexes WHERE tablename = 'orders';
-- demo-broken lists orders_pkey only.
```
