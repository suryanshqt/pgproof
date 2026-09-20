"""root"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bm_root"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("widgets")
