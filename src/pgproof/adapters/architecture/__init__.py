"""Stored-procedure, topology, and tenant assessment. `docs/PR_ROADMAP.md`'s
BE-32. `routing.py` is section 25's primary/replica decision tree; `tenancy.py`
is a best-effort tenant-enforcement scan over the captured workload.

v1 scope: stored-procedure candidacy and architecture-graph overlays are not
built here. Procedure candidacy's own signals (`docs/TECHNICAL_DESIGN.md`
section 24 — "shared operation across services", cross-service duplication)
need a cross-repository/cross-service fact this codebase captures nowhere
yet; inventing one would be exactly the kind of guess
`docs/PRODUCT_SPEC.md` section 7 forbids. Graph overlays would mean
extending the frozen, already-tested `domain.graph.GraphIR` model, a
separate-enough change to not rush alongside the above.
"""

from __future__ import annotations
