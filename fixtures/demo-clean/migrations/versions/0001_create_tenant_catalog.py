"""create tenant catalog

Revision ID: b7c41d92a8f3
Revises:
Create Date: 2026-02-03 09:14:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7c41d92a8f3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_unique_constraint("uq_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_foreign_key(
        "fk_users_tenant_id", "users", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_unique_constraint("uq_users_tenant_email", "users", ["tenant_id", "email"])
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        "fk_products_tenant_id", "products", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_unique_constraint("uq_products_tenant_sku", "products", ["tenant_id", "sku"])
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("products")
    op.drop_table("users")
    op.drop_table("tenants")
