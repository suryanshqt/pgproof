"""add sessions"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "lin_0002"
down_revision = "lin_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
    )
    op.create_foreign_key(
        "fk_sessions_account_id", "sessions", "accounts", ["account_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_sessions_account_id", "sessions", ["account_id"])


def downgrade() -> None:
    op.drop_table("sessions")
