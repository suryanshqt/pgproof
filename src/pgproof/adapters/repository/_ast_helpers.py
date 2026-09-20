"""AST literal resolution shared by `alembic_static` and `sqlalchemy_static`.

Both parsers apply the same rule: a construct resolves only if every argument
that identifies it is a literal (or a tuple/list of literals); anything else
— a variable, an imported constant, a helper call — is left for the caller to
report as unresolved rather than guessed at.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Final

UNRESOLVED: Final = object()


def literal(node: ast.expr) -> object:
    """A statically resolvable literal, or `UNRESOLVED`."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [literal(elt) for elt in node.elts]
        if any(value is UNRESOLVED for value in values):
            return UNRESOLVED
        return tuple(values) if isinstance(node, ast.Tuple) else list(values)
    return UNRESOLVED


def as_str_tuple(value: object) -> tuple[str, ...]:
    if value is None or value is UNRESOLVED:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def callee_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def content_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"
