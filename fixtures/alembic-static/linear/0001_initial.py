"""create accounts"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "lin_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_unique_constraint("uq_accounts_email", "accounts", ["email"])


def downgrade() -> None:
    op.drop_table("accounts")
