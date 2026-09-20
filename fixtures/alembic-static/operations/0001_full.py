"""exercise every supported operation kind in one revision"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ops_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("legacy_code", sa.String(length=10), nullable=True),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer()),
    )
    op.create_table(
        "scratch",
        sa.Column("id", sa.Integer()),
    )

    op.add_column("widgets", sa.Column("sku", sa.String(length=32), nullable=True))
    op.drop_column("widgets", "legacy_code")
    op.alter_column("widgets", "sku", nullable=False, server_default=sa.text("''"))
    op.alter_column("widgets", "name", new_column_name="display_name")

    op.create_primary_key("pk_tags", "tags", ["id"])
    op.create_unique_constraint("uq_widgets_sku", "widgets", ["sku"])
    op.create_check_constraint("ck_widgets_sku_not_empty", "widgets", "sku <> ''")
    op.create_foreign_key(
        "fk_tags_widget", "tags", "widgets", ["id"], ["id"], ondelete="CASCADE"
    )
    op.drop_constraint("ck_widgets_sku_not_empty", "widgets", type_="check")

    op.create_index("ix_widgets_sku", "widgets", ["sku"], unique=True)
    op.drop_index("ix_widgets_sku", table_name="widgets")

    # `scratch` has no dependent constraint: renaming does not need to cascade
    # rewrite anything else in the accumulated schema.
    op.rename_table("scratch", "scratch_renamed")
    op.drop_table("scratch_renamed")


def downgrade() -> None:
    pass
