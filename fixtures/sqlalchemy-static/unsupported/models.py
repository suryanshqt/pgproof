"""Unsupported constructs within an otherwise-resolvable model.

A dynamic `__tablename__` is a separate scenario (it gates the whole class
before its body is ever walked) and is not exercised here; see
`tests/unit/test_sqlalchemy_static.py`'s dedicated case for it.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ._helpers import audit_column

FK_TARGET = "accounts.id"


class Base(DeclarativeBase):
    pass


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by = audit_column()  # helper wrapper: not a direct Column/mapped_column call
    owner_id: Mapped[int] = mapped_column(sa.ForeignKey(FK_TARGET))  # non-literal FK target

    for _extra in range(2):
        # Loop-generated column: never a simple class-body statement.
        locals()[f"extra_{_extra}"] = mapped_column(sa.Integer(), nullable=True)
