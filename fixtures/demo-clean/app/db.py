"""Engine and session construction for the storefront application."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ["DATABASE_URL"]


def build_engine(echo: bool = False):
    return create_engine(database_url(), echo=echo, future=True)


def build_session_factory(echo: bool = False) -> sessionmaker[Session]:
    return sessionmaker(bind=build_engine(echo=echo), expire_on_commit=False)
