"""merge branch a and branch b"""

from __future__ import annotations

revision = "bm_merge"
down_revision = ("bm_branch_a", "bm_branch_b")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
