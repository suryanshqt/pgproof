# Iteration 1 — product wedge

**Status:** accepted

## First audience

Early-stage Python backend developers preparing a PostgreSQL application for launch and working without a dedicated database administrator.

## Trigger

Before launch, or before merging a substantial schema or query change.

## Core promise

> Show me the database my code creates, identify risky design decisions, propose a better architecture, and prove the improvements that can be safely tested.

## Differentiation

pgproof combines:

- Alembic and SQLAlchemy code analysis
- a short interview for business facts absent from code
- accurate current and proposed ER diagrams
- context-aware database design recommendations
- physical verification of supported performance changes

## Initial product boundary

- PostgreSQL
- Python, SQLAlchemy/SQLModel, Alembic, and pytest
- local-first CLI plus an interactive local report
- no production connection or automatic deployment
- stored procedures and replicas are recommended only when requirements justify them
- no hosted service until local adoption demonstrates demand

## Decision

The first release optimizes for clarity, trust, and useful pre-launch decisions rather than enterprise breadth.
