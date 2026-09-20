"""SQLAlchemy 2.x declarative style: Mapped[] and mapped_column()."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(sa.String(320), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=sa.text("true"))
    nickname: Mapped[str | None] = mapped_column(sa.String(64))


class LoginSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("accounts.id"), index=True)
    token: Mapped[str] = mapped_column(sa.String(64), nullable=False)
