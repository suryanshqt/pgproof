"""orphaned revision"""

from __future__ import annotations

revision = "orphan_rev"
down_revision = "does_not_exist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
