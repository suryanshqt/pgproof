"""Data access for the storefront application."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderItem


def list_tenant_orders(session: Session, tenant_id: int, status: str, limit: int = 20) -> list[Order]:
    """Most recent orders for one tenant in one status.

    IDX-002: filters on (tenant_id, status) and orders by created_at descending.
    """
    statement = (
        select(Order)
        .where(Order.tenant_id == tenant_id, Order.status == status)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(statement))


def list_user_orders(session: Session, user_id: int) -> list[Order]:
    """Every order belonging to one user.

    IDX-001: filters on orders.user_id, a foreign key with no index.
    """
    statement = select(Order).where(Order.user_id == user_id)
    return list(session.scalars(statement))


def order_totals_by_item(session: Session, tenant_id: int, status: str) -> list[tuple[int, int]]:
    """Recompute each order total from its items.

    NPLUS1-001: `order.items` is lazily loaded, so this issues one query for the
    orders and one further query per order returned.
    """
    totals: list[tuple[int, int]] = []
    for order in list_tenant_orders(session, tenant_id, status):
        totals.append((order.id, sum(item.quantity * item.unit_price_cents for item in order.items)))
    return totals


def count_order_items(session: Session, order_id: int) -> int:
    statement = select(OrderItem).where(OrderItem.order_id == order_id)
    return len(list(session.scalars(statement)))
