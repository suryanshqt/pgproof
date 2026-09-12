-- Deterministic dataset for the storefront fixture.
--
-- Every value is derived arithmetically from generate_series. No random(),
-- setseed(), or clock call appears, so the same rows are produced on every run
-- and on every machine. Re-running the script replaces the data.
--
-- Row counts: 200 tenants, 20,000 users, 2,000 products, 400,000 orders,
-- 800,000 order items.

TRUNCATE order_items, orders, products, users, tenants;

INSERT INTO tenants (id, slug, name, created_at)
SELECT i, 'tenant-' || lpad(i::text, 4, '0'), 'Tenant ' || i,
       TIMESTAMPTZ '2026-01-01 00:00:00+00'
FROM generate_series(1, 200) AS i;

INSERT INTO users (id, tenant_id, email, created_at)
SELECT i, ((i - 1) % 200) + 1, 'user' || i || '@tenant' || (((i - 1) % 200) + 1) || '.test',
       TIMESTAMPTZ '2026-01-01 00:00:00+00'
FROM generate_series(1, 20000) AS i;

INSERT INTO products (id, tenant_id, sku, name, price_cents)
SELECT i, ((i - 1) % 200) + 1, 'SKU-' || lpad(i::text, 6, '0'), 'Product ' || i,
       500 + (i % 400) * 7
FROM generate_series(1, 2000) AS i;

-- Status is keyed on (i - 1) / 200 rather than i % 10. tenant_id is keyed on
-- i % 200 and 10 divides 200, so i % 10 would make status a function of
-- tenant_id and leave every tenant holding exactly one status.
INSERT INTO orders (id, tenant_id, user_id, status, total_cents, created_at)
SELECT i,
       ((i - 1) % 200) + 1,
       ((i - 1) % 20000) + 1,
       (ARRAY['paid','paid','paid','paid','paid','paid','pending','pending','shipped','cancelled'])[(((i - 1) / 200) % 10) + 1],
       1000 + (i % 500) * 13,
       -- i::bigint is required: i * 7919 overflows int4 beyond i = 271,246.
       TIMESTAMPTZ '2026-01-01 00:00:00+00' + (((i::bigint * 7919) % 400000) * INTERVAL '1 minute')
FROM generate_series(1, 400000) AS i;

INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_cents)
SELECT i, ((i - 1) % 400000) + 1, ((i - 1) % 2000) + 1, 1 + (i % 4), 500 + (i % 400) * 7
FROM generate_series(1, 800000) AS i;

SELECT setval(pg_get_serial_sequence('tenants','id'), (SELECT max(id) FROM tenants));
SELECT setval(pg_get_serial_sequence('users','id'), (SELECT max(id) FROM users));
SELECT setval(pg_get_serial_sequence('products','id'), (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('orders','id'), (SELECT max(id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items','id'), (SELECT max(id) FROM order_items));

ANALYZE;
