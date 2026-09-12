"""Data access for the storefront application."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Order, OrderItem


def list_tenant_orders(session: Session, tenant_id: int, status: str, limit: int = 20) -> list[Order]:
    """Most recent orders for one tenant in one status.

    Supported by ix_orders_tenant_status_created.
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

    Supported by ix_orders_user_id.
    """
    statement = select(Order).where(Order.user_id == user_id)
    return list(session.scalars(statement))


def order_totals_by_item(session: Session, tenant_id: int, status: str) -> list[tuple[int, int]]:
    """Recompute each order total from its items.

    `items` is eager-loaded with selectinload, so this issues two queries in total
    regardless of how many orders are returned.
    """
    statement = (
        select(Order)
        .where(Order.tenant_id == tenant_id, Order.status == status)
        .order_by(Order.created_at.desc())
        .limit(20)
        .options(selectinload(Order.items))
    )
    totals: list[tuple[int, int]] = []
    for order in session.scalars(statement):
        totals.append((order.id, sum(item.quantity * item.unit_price_cents for item in order.items)))
    return totals


def count_order_items(session: Session, order_id: int) -> int:
    statement = select(OrderItem).where(OrderItem.order_id == order_id)
    return len(list(session.scalars(statement)))
