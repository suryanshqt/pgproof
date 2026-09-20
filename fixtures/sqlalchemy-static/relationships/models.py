"""Relationship configurations: one-to-many, many-to-many, one-to-one, cascade, lazy."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


post_tags = sa.Table(
    "post_tags",
    Base.metadata,
    sa.Column("post_id", sa.ForeignKey("posts.id"), primary_key=True),
    sa.Column("tag_id", sa.ForeignKey("tags.id"), primary_key=True),
)


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list["Post"]] = relationship(
        back_populates="author", cascade="all, delete-orphan", lazy="selectin"
    )
    profile: Mapped["Profile"] = relationship(back_populates="author", uselist=False)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(sa.ForeignKey("authors.id"))
    author: Mapped["Author"] = relationship(back_populates="profile")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(sa.ForeignKey("authors.id"))
    author: Mapped["Author"] = relationship(back_populates="posts")
    tags: Mapped[list["Tag"]] = relationship(secondary=post_tags, back_populates="posts")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    posts: Mapped[list["Post"]] = relationship(secondary=post_tags, back_populates="tags")
