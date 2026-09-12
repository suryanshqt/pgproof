# pgproof

> Understand the design. Ask what code cannot reveal. Recommend with evidence. Verify what can be tested.

pgproof is a local-first database design reviewer and experimental performance lab for PostgreSQL applications built with SQLAlchemy/SQLModel and Alembic.

The repository is currently in the **design-complete, implementation-not-started** stage.

## Documents

- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — product, users, scope, and success
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, boundaries, processes, and data flow
- [`docs/TECHNICAL_DESIGN.md`](docs/TECHNICAL_DESIGN.md) — contracts, algorithms, safety, and testing
- [`docs/INTERFACE_DESIGN.md`](docs/INTERFACE_DESIGN.md) — terminal and local UI design system and quality gates
- [`docs/PR_ROADMAP.md`](docs/PR_ROADMAP.md) — dependency-ordered `BE-*` and `FE-*` implementation path
- [`ideation/`](ideation/) — the three accepted product iterations

## Status

- Ideation loops: accepted
- Product specification: accepted baseline
- Architecture: accepted baseline
- Technical design: accepted baseline
- Interface design: accepted baseline
- PR roadmap: accepted baseline
- Code: not started

Implementation begins with `BE-01`, followed by the dependency order in `docs/PR_ROADMAP.md`.
