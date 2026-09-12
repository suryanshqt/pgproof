# pgproof

> Understand the design. Ask what code cannot reveal. Recommend with evidence. Verify what can be tested.

pgproof is a local-first database design reviewer and experimental performance lab for PostgreSQL applications built with SQLAlchemy/SQLModel and Alembic.

The accepted design baseline is complete. Implementation has started with the
repository and quality foundation; no analysis command is implemented yet.

## Documents

- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — product, users, scope, and success
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, boundaries, processes, and data flow
- [`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md) — contracts, algorithms, safety, and testing
- [`docs/INTERFACE_DESIGN.md`](docs/INTERFACE_DESIGN.md) — terminal and local UI design system and quality gates
- [`docs/PR_ROADMAP.md`](docs/PR_ROADMAP.md) — dependency-ordered `BE-*` and `FE-*` implementation path
- [`ideation/`](ideation/) — the three accepted product iterations
- [`docs/adr/`](docs/adr/) — architectural decision records
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — development commands, dependency boundaries, and PR conventions

## Status

- Ideation loops: accepted
- Product specification: accepted baseline
- Architecture: accepted baseline
- Technical design: accepted baseline
- Interface design: accepted baseline
- PR roadmap: accepted baseline
- Code: `BE-01` repository and quality foundation

Implementation follows the dependency order in `docs/PR_ROADMAP.md`.

## Development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
uv run pgproof --help
```

Quality gate:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full command reference.
