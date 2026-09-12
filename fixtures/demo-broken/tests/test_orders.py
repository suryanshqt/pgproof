"""Storefront operations that pgproof captures as application operations."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Tenant
from app.repositories import (
    count_order_items,
    list_tenant_orders,
    list_user_orders,
    order_totals_by_item,
)


def test_list_tenant_orders_returns_recent_first(session: Session, seeded_tenant: Tenant) -> None:
    orders = list_tenant_orders(session, seeded_tenant.id, "paid")
    assert len(orders) == 5
    assert orders == sorted(orders, key=lambda order: order.created_at, reverse=True)


def test_list_user_orders_returns_every_order(session: Session, seeded_tenant: Tenant) -> None:
    user_id = seeded_tenant.users[0].id
    assert len(list_user_orders(session, user_id)) == 5


def test_order_totals_by_item_matches_stored_total(
    session: Session, seeded_tenant: Tenant
) -> None:
    totals = order_totals_by_item(session, seeded_tenant.id, "paid")
    assert len(totals) == 5
    assert all(total == 5000 for _, total in totals)


def test_count_order_items(session: Session, seeded_tenant: Tenant) -> None:
    order_id = seeded_tenant.orders[0].id
    assert count_order_items(session, order_id) == 1
