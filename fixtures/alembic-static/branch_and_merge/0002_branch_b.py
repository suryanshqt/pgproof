"""branch b"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "bm_branch_b"
down_revision = "bm_root"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("widgets", sa.Column("weight_grams", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("widgets", "weight_grams")
