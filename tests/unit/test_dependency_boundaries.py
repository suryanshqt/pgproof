"""Layer-boundary enforcement for the dependency rule in ARCHITECTURE.md section 4."""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "src"

_LAYERS = frozenset(
    {
        "adapters",
        "application",
        "cli",
        "contracts",
        "domain",
        "local_api",
        "ports",
        "rules",
        "store",
    }
)

# Every top-level package under src/pgproof must appear here, so a new layer cannot
# silently escape the dependency rule.
ALLOWED_INTERNAL: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "ports": frozenset({"domain", "ports"}),
    "application": frozenset({"application", "domain", "ports"}),
    "rules": frozenset({"domain", "rules"}),
    "adapters": frozenset({"adapters", "domain", "ports"}),
    # Generated contract resources. Reads packaged JSON Schemas, so it may touch
    # the filesystem, which is why it is a layer of its own rather than part of
    # the pure domain.
    "contracts": frozenset({"contracts", "domain"}),
    # The artifact store. Reads and writes `.pgproof`, so it needs domain models
    # and the clock port, but no application service and no adapter.
    "store": frozenset({"domain", "ports", "store"}),
    "cli": _LAYERS,
    "local_api": _LAYERS,
}

_INFRASTRUCTURE = frozenset(
    {
        "alembic",
        "click",
        "docker",
        "fastapi",
        "pglast",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "sqlmodel",
        "starlette",
        "uvicorn",
    }
)

_IO_MODULES = frozenset(
    {
        "http",
        "os",
        "pathlib",
        "shutil",
        "socket",
        "sqlite3",
        "subprocess",
        "tempfile",
        "urllib",
    }
)

BANNED_EXTERNAL: dict[str, frozenset[str]] = {
    # The domain carries no I/O either. It defines the contract; BE-04 owns
    # reading and writing it. Pydantic is permitted, per TECHNICAL_DESIGN
    # section 1, because the transport models generate the JSON Schemas.
    "domain": _INFRASTRUCTURE | _IO_MODULES,
    "ports": _INFRASTRUCTURE,
    "application": _INFRASTRUCTURE,
    "rules": _INFRASTRUCTURE | _IO_MODULES,
    "adapters": frozenset(),
    "contracts": _INFRASTRUCTURE,
    # I/O is the point of the store, but it has no business talking to Docker,
    # PostgreSQL or an ORM directly; adapters own those.
    "store": _INFRASTRUCTURE,
    "cli": frozenset(),
    "local_api": frozenset(),
}


def _imports(source: str) -> Iterator[tuple[int, str | None]]:
    """Yield (line, dotted module) per import; a relative import yields None."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, None if node.level else node.module


def _layer_of(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 else None


def check_module(module: str, source: str) -> list[str]:
    layer = _layer_of(module)
    if layer is None:
        return []
    if layer not in ALLOWED_INTERNAL:
        return [f"{module}: package 'pgproof.{layer}' has no declared dependency rule"]

    problems: list[str] = []
    for lineno, name in _imports(source):
        if name is None:
            problems.append(f"{module}:{lineno} uses a relative import; use absolute imports")
            continue
        root = name.split(".")[0]
        if root == "pgproof":
            target = _layer_of(name)
            if target is not None and target not in ALLOWED_INTERNAL[layer]:
                allowed = ", ".join(sorted(ALLOWED_INTERNAL[layer]))
                problems.append(
                    f"{module}:{lineno} imports pgproof.{target}; "
                    f"{layer} may import only: {allowed}"
                )
        elif root in BANNED_EXTERNAL[layer]:
            problems.append(f"{module}:{lineno} imports {root}, which is forbidden in {layer}")
    return problems


def _source_modules() -> list[tuple[str, str]]:
    modules: list[tuple[str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append((".".join(parts), path.read_text(encoding="utf-8")))
    return modules


def test_source_tree_is_discoverable() -> None:
    modules = dict(_source_modules())
    assert "pgproof.cli.app" in modules


def test_source_tree_respects_layer_boundaries() -> None:
    problems = [
        problem for module, source in _source_modules() for problem in check_module(module, source)
    ]
    assert problems == []


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        ("pgproof.domain.ir", "import pgproof.adapters.postgres", "may import only"),
        ("pgproof.domain.ir", "from pgproof.cli import app", "may import only"),
        ("pgproof.domain.ir", "import sqlalchemy", "forbidden in domain"),
        ("pgproof.ports.database", "import psycopg", "forbidden in ports"),
        ("pgproof.application.review", "import docker", "forbidden in application"),
        ("pgproof.rules.schema", "from pathlib import Path", "forbidden in rules"),
        ("pgproof.rules.schema", "import pgproof.ports.artifacts", "may import only"),
        ("pgproof.domain.ir", "from . import evidence", "relative import"),
        ("pgproof.seed.generator", "import pgproof.domain.ir", "no declared dependency rule"),
    ],
)
def test_violations_are_detected(module: str, source: str, expected: str) -> None:
    problems = check_module(module, source)
    assert len(problems) == 1
    assert expected in problems[0]


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("pgproof", "from importlib.metadata import version"),
        ("pgproof.domain.ir", "from dataclasses import dataclass\nimport pgproof.domain.evidence"),
        ("pgproof.ports.database", "from typing import Protocol\nimport pgproof.domain.ir"),
        ("pgproof.application.review", "import pgproof.ports.artifacts"),
        ("pgproof.adapters.postgres.catalog", "import psycopg\nimport pgproof.ports.database"),
        ("pgproof.cli.app", "import click\nimport pgproof.application.review"),
        ("pgproof.local_api.server", "import fastapi\nimport pgproof.adapters.reports"),
    ],
)
def test_permitted_imports_pass(module: str, source: str) -> None:
    assert check_module(module, source) == []


def test_domain_is_pure_and_uses_only_the_sanctioned_transport_library() -> None:
    """The domain may import Pydantic and the standard library, nothing else."""
    allowed_third_party = {"pydantic"}
    seen: set[str] = set()
    for module, source in _source_modules():
        if _layer_of(module) != "domain":
            continue
        for _lineno, name in _imports(source):
            assert name is not None, f"{module}: relative import"
            root = name.split(".")[0]
            if root in {"pgproof"} or root in sys.stdlib_module_names:
                continue
            seen.add(root)
    assert seen <= allowed_third_party, f"domain imports unsanctioned packages: {sorted(seen)}"
    assert "pydantic" in seen, "the domain should define its transport models with Pydantic"


def test_domain_performs_no_filesystem_access() -> None:
    problems = [
        problem
        for module, source in _source_modules()
        if _layer_of(module) == "domain"
        for problem in check_module(module, source)
    ]
    assert problems == []
    for module, source in _source_modules():
        if _layer_of(module) != "domain":
            continue
        for _lineno, name in _imports(source):
            assert name is not None
            assert name.split(".")[0] not in _IO_MODULES, f"{module} imports {name}"


def test_contracts_layer_may_read_packaged_resources() -> None:
    """The resource accessor is allowed filesystem access; the domain is not."""
    modules = {module for module, _ in _source_modules() if _layer_of(module) == "contracts"}
    assert modules, "the contracts layer should exist once schemas are generated"
    problems = [
        problem
        for module, source in _source_modules()
        if _layer_of(module) == "contracts"
        for problem in check_module(module, source)
    ]
    assert problems == []
