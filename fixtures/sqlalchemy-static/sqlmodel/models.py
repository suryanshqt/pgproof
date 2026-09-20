"""SQLModel's Field()-based declarative style."""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=200)
    email: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)
