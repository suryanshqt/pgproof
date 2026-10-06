"""Branch diff and migration-safety planner. `docs/PR_ROADMAP.md`'s BE-31:
base/current schema comparison, destructive/constraint/type/index risks,
version-sensitive lock/rewrite facts, expand-contract templates,
reversibility, and ordered deployment boundaries.

`diff.py` finds which revisions are new on the current branch relative to a
base (pure, over two already-parsed `RevisionGraphReport`s —
`adapters.repository.alembic_static` is never touched: a new revision's own
operations are walked independently here, not by reusing that module's
private replay internals). `risk.py` classifies each added revision's
operations; it never invents a production duration, matching
`docs/PR_ROADMAP.md`'s own accept criterion.
"""

from __future__ import annotations
