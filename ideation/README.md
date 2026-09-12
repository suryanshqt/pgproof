# pgproof ideation

This directory records the product decisions made before implementation begins.

## Iteration sequence

1. **Product wedge** — target user, painful job, promise, scope, and differentiation.
2. **Analysis contract** — inputs, questions, recommendation categories, evidence levels, and boundaries of what pgproof can know.
3. **Product experience** — CLI and local UI journey, outputs, trust model, adoption loop, and success criteria.

After all three loops, the accepted decisions will be consolidated into:

- `docs/PRODUCT_SPEC.md`
- `docs/TECHNICAL_DESIGN.md`
- `docs/ARCHITECTURE.md`
- `docs/PR_ROADMAP.md`

The PR roadmap will use dependency-ordered identifiers such as `BE-01`, `BE-02`, `FE-01`, and `FE-02`. No production implementation begins until the three ideation loops are complete.

## Current hypothesis

pgproof is a local-first database design reviewer and experimental performance lab for PostgreSQL applications. It reconstructs the database implied by Alembic migrations and SQLAlchemy code, asks only for business context the repository cannot reveal, generates current and proposed ER designs, and experimentally verifies supported performance recommendations.

## Status

- Iteration 1: accepted
- Iteration 2: accepted
- Iteration 3: accepted
- Final design documents: complete
- Implementation: not started
