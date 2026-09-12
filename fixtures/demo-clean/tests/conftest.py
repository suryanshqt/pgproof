"""Test fixtures for the storefront application."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.db import build_session_factory
from app.models import Order, OrderItem, Product, Tenant, User

EPOCH = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


@pytest.fixture
def session() -> Iterator[Session]:
    factory = build_session_factory()
    with factory() as session:
        yield session
        session.rollback()


@pytest.fixture
def seeded_tenant(session: Session) -> Tenant:
    tenant = Tenant(slug="acme", name="Acme Supply")
    session.add(tenant)
    session.flush()

    user = User(tenant_id=tenant.id, email="buyer@acme.test")
    product = Product(tenant_id=tenant.id, sku="SKU-1", name="Widget", price_cents=2500)
    session.add_all([user, product])
    session.flush()

    for index in range(5):
        order = Order(
            tenant_id=tenant.id,
            user_id=user.id,
            status="paid",
            total_cents=5000,
            created_at=EPOCH + datetime.timedelta(days=index),
        )
        session.add(order)
        session.flush()
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=2,
                unit_price_cents=product.price_cents,
            )
        )

    session.flush()
    return tenant
