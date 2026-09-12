"""create orders and order items

Revision ID: 6a912ef4c1b8
Revises: b7c41d92a8f3
Create Date: 2026-02-11 16:02:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "6a912ef4c1b8"
down_revision = "b7c41d92a8f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_foreign_key(
        "fk_orders_tenant_id", "orders", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_orders_user_id", "orders", "users", ["user_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_check_constraint(
        "ck_orders_status",
        "orders",
        "status IN ('pending', 'paid', 'shipped', 'cancelled')",
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index(
        "ix_orders_tenant_status_created",
        "orders",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "fk_order_items_order_id", "order_items", "orders", ["order_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_order_items_product_id",
        "order_items",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
