"""dynamic and unsupported constructs, one of each"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ._helpers import add_audit_columns

revision = "unsup_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLE_NAME = "reports"


def upgrade() -> None:
    op.create_table(
        "known_table",
        sa.Column("id", sa.Integer(), primary_key=True),
    )

    # Helper wrapper: not a direct `op.*` call, so its effect is opaque here.
    add_audit_columns(op, "known_table")

    # Raw SQL: the payload is not statically interpreted.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # DML: a data change, not a schema change, and not statically interpreted.
    op.execute("INSERT INTO known_table (id) VALUES (1)")

    # Conditional: the operation inside is not unconditionally applied.
    if sa.inspect(op.get_bind()).has_table("legacy"):
        op.drop_table("legacy")

    # Dynamic table name: not a string literal, so the table cannot be identified.
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("known_table")
