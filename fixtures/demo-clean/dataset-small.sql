-- Small deterministic dataset for continuous integration.
--
-- Same generator arithmetic as dataset.sql at 1/200th the scale, so CI can
-- assert the N+1 statement count and result equivalence without loading the
-- 400,000-row benchmark dataset. Performance measurement uses dataset.sql and
-- deliberately does not run in ordinary CI.
--
-- Row counts: 5 tenants, 100 users, 20 products, 2,000 orders, 4,000 order items.

TRUNCATE order_items, orders, products, users, tenants;

INSERT INTO tenants (id, slug, name, created_at)
SELECT i, 'tenant-' || lpad(i::text, 4, '0'), 'Tenant ' || i,
       TIMESTAMPTZ '2026-01-01 00:00:00+00'
FROM generate_series(1, 5) AS i;

INSERT INTO users (id, tenant_id, email, created_at)
SELECT i, ((i - 1) % 5) + 1, 'user' || i || '@tenant' || (((i - 1) % 5) + 1) || '.test',
       TIMESTAMPTZ '2026-01-01 00:00:00+00'
FROM generate_series(1, 100) AS i;

INSERT INTO products (id, tenant_id, sku, name, price_cents)
SELECT i, ((i - 1) % 5) + 1, 'SKU-' || lpad(i::text, 6, '0'), 'Product ' || i,
       500 + (i % 400) * 7
FROM generate_series(1, 20) AS i;

-- Status is keyed on (i - 1) / 5 rather than i % 10, for the same reason as
-- dataset.sql: 5 divides 10, so i % 10 would make status a function of tenant_id.
INSERT INTO orders (id, tenant_id, user_id, status, total_cents, created_at)
SELECT i,
       ((i - 1) % 5) + 1,
       ((i - 1) % 100) + 1,
       (ARRAY['paid','paid','paid','paid','paid','paid','pending','pending','shipped','cancelled'])[(((i - 1) / 5) % 10) + 1],
       1000 + (i % 500) * 13,
       TIMESTAMPTZ '2026-01-01 00:00:00+00' + (((i::bigint * 7919) % 2000) * INTERVAL '1 minute')
FROM generate_series(1, 2000) AS i;

INSERT INTO order_items (id, order_id, product_id, quantity, unit_price_cents)
SELECT i, ((i - 1) % 2000) + 1, ((i - 1) % 20) + 1, 1 + (i % 4), 500 + (i % 400) * 7
FROM generate_series(1, 4000) AS i;

SELECT setval(pg_get_serial_sequence('tenants','id'), (SELECT max(id) FROM tenants));
SELECT setval(pg_get_serial_sequence('users','id'), (SELECT max(id) FROM users));
SELECT setval(pg_get_serial_sequence('products','id'), (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('orders','id'), (SELECT max(id) FROM orders));
SELECT setval(pg_get_serial_sequence('order_items','id'), (SELECT max(id) FROM order_items));

ANALYZE;
