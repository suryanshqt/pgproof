# Hand-measured baseline for demo-broken

These numbers were produced by hand, before any pgproof measurement code exists.
They establish that the two planted index cases and the planted N+1 are real and
that their direction of effect reproduces. They are **not** a proof bundle, not a
pgproof artifact, and not a production prediction.

## Environment

| Item | Value |
|---|---|
| PostgreSQL | 17.11 (Debian 17.11-1.pgdg13+2) |
| Image | `postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675` |
| Host | macOS arm64 (Apple silicon), Docker Desktop 28.3.2 |
| Python | 3.13.5 |
| Client | SQLAlchemy 2.0.52, Alembic 1.20.0, psycopg 3.3.5, pytest 9.1.1 |
| Client pins | `pyproject.toml` and `uv.lock` in this directory |
| Session settings | `max_parallel_workers_per_gather = 0`, `jit = off`, `statement_timeout = '30s'` |

Every client version above is pinned with `==` and locked. The reproduction below
installs from that lockfile and pulls the image by digest, so it cannot silently
run against a different stack than the one these numbers came from.

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

Two independent sessions on the same host, six runs total. Session B was taken
during the BE-02 reproducibility audit, from the pinned lockfile and the
digest-addressed image.

| Session | Run | A1 median | A1 IQR | B median | A2 median | A1 to A2 drift | Absolute saving |
|---|---|---|---|---|---|---|---|
| A | 1 | 7.81 ms | 24.2% | 0.21 ms | 7.54 ms | 3.46% | 7.60 ms |
| A | 2 | 7.47 ms | 4.9% | 0.27 ms | 7.52 ms | 0.67% | 7.20 ms |
| A | 3 | 7.53 ms | 1.6% | 0.17 ms | 7.64 ms | 1.46% | 7.36 ms |
| B | 1 | 8.05 ms | 22.0% | 0.24 ms | 9.02 ms | 12.05% | 7.81 ms |
| B | 2 | 7.87 ms | 3.4% | 0.19 ms | 7.70 ms | 2.16% | 7.68 ms |
| B | 3 | 9.25 ms | 6.9% | 0.18 ms | 7.69 ms | 16.86% | 9.07 ms |

Plan shape changes from `Seq Scan on orders` to
`Bitmap Heap Scan on orders -> Bitmap Index Scan using ix_orders_user_id`, in
every run of both sessions. Index build 0.05 to 0.06 s, index size 3056 kB in
every run.

What reproduces: the plan change, the index size, and a saving between 7.20 ms
and 9.07 ms, roughly two orders of magnitude. What does not reproduce is any
individual median. Nothing in this table should be quoted as *the* baseline
figure for this case.

**This case is measurably unstable and that is the finding.** Control IQR reached
24.2% in session A and 22.0% in session B, both above the 20%
`max_iqr_fraction` in `docs/TECHNICAL_DESIGN.md` section 3, so under the
product's own variance gate those runs would be suppressed as inconclusive rather
than reported. A1 to A2 drift reached 16.86%, meaning the control moved by more
than twice the treatment's entire duration between the start and end of one
experiment. Per section 20 that is exactly the condition A2 exists to detect.

The practical consequence for `BE-25` and `BE-28`: a query returning 20 of
400,000 rows in single-digit milliseconds is too short to verify stably with 7
samples on a laptop. Either the scale must grow or the sample count must, and the
engine must be willing to return inconclusive here rather than a number. A
fixture that only ever produced clean measurements would have hidden that.

## IDX-002 — composite B-tree on orders(tenant_id, status, created_at DESC)

```sql
SELECT id, tenant_id, user_id, status, total_cents, created_at
FROM orders WHERE tenant_id = 7 AND status = 'paid'
ORDER BY created_at DESC LIMIT 20;
CREATE INDEX ix_orders_tenant_status_created
  ON orders (tenant_id, status, created_at DESC);
```

| Session | Run | A1 median | A1 IQR | B median | A2 median | A1 to A2 drift | Absolute saving |
|---|---|---|---|---|---|---|---|
| A | 1 | 7.97 ms | 2.9% | 0.24 ms | 7.99 ms | 0.25% | 7.73 ms |
| A | 2 | 7.78 ms | 3.3% | 0.19 ms | 7.96 ms | 2.31% | 7.59 ms |
| A | 3 | 8.06 ms | 4.0% | 0.16 ms | 8.08 ms | 0.25% | 7.90 ms |
| B | 1 | 7.99 ms | 2.9% | 0.24 ms | 8.00 ms | 0.13% | 7.75 ms |
| B | 2 | 8.83 ms | 4.8% | 0.24 ms | 8.18 ms | 7.36% | 8.59 ms |
| B | 3 | 8.12 ms | 0.4% | 0.23 ms | 8.34 ms | 2.71% | 7.89 ms |

Plan shape changes from `Limit -> Sort -> Seq Scan on orders` to
`Limit -> Index Scan using ix_orders_tenant_status_created`, in every run of both
sessions, so the sort is eliminated rather than merely accelerated. Index build
0.13 to 0.16 s, index size 16 MB in every run.

This case is the stabler of the two. Control IQR stayed at or below 4.8% in all
six runs, inside the 20% gate, and drift exceeded 5% once. Saving ranges from
7.59 ms to 8.59 ms.

Treatment IQR ranges from 3.3% to 16.9% here, and reached 37.1% for `IDX-001`
in session A. At a 0.2 ms median, relative spread is dominated by timer and
scheduling granularity, so the IQR gate is not informative for the treatment arm.
Absolute saving is the reportable quantity, which is also why
`docs/PRODUCT_SPEC.md` section 12 sorts by absolute time saved.

## NPLUS1-001 — observed N+1 in order_totals_by_item

Statements were counted with a SQLAlchemy `before_cursor_execute` listener while
calling `order_totals_by_item(session, 7, "paid")` in each fixture.

| Fixture | Orders returned | SELECT statements | Totals checksum |
|---|---|---|---|
| demo-broken | 20 | 21 | 199840 |
| demo-clean | 20 | 2 | 199840 |

Reproduced identically in both sessions. `21 = 1 + 20` confirms the broken path
issues one query per order returned; `2` is independent of the row count. All
twenty order ids match between fixtures in the same sequence, beginning
`376007, 40207, 104407`, and the checksums agree. The `selectinload` treatment therefore
satisfies a result-equivalence contract while reducing statement count from
1 + N to a fixed 2. No wall-clock claim is made for this case; the finding is the
amplification, and `BE-29` owns its timed verification.

## Write cost

Not measured. The index write-cost guard is `BE-28`. Nothing in this document may
be read as a keep-or-drop verdict for either index.

## Reproducing this by hand

Run from this directory. `PG_IMAGE` is the digest recorded above; do not
substitute a floating version tag.

```bash
PG_IMAGE=postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675

docker run -d --name pgproof-fixture-pg \
  -e POSTGRES_PASSWORD=fixture -e POSTGRES_USER=fixture -e POSTGRES_DB=postgres \
  -p 55432:5432 "$PG_IMAGE"
until docker exec pgproof-fixture-pg pg_isready -U fixture -q; do sleep 1; done
docker exec pgproof-fixture-pg psql -U fixture -d postgres -c 'CREATE DATABASE demo_broken;'

# Installs the exact locked client stack, not a fresh resolution.
uv sync --all-groups --frozen

export DATABASE_URL='postgresql+psycopg://fixture:fixture@127.0.0.1:55432/demo_broken'
uv run --frozen alembic upgrade head
docker cp dataset.sql pgproof-fixture-pg:/tmp/dataset.sql
docker exec pgproof-fixture-pg psql -U fixture -d demo_broken -v ON_ERROR_STOP=1 -f /tmp/dataset.sql

uv run --frozen pytest
docker rm -f pgproof-fixture-pg
```

`demo-clean` reproduces with the same commands, substituting `demo_clean` for
`demo_broken`; it carries the same pins and the same `uv.lock`.

Confirm the planted schema defects directly:

```sql
SELECT conname FROM pg_constraint WHERE conrelid = 'orders'::regclass AND contype = 'f';
-- demo-broken lists fk_orders_user_id only; fk_orders_tenant_id is absent.
SELECT indexname FROM pg_indexes WHERE tablename = 'orders';
-- demo-broken lists orders_pkey only.
```
