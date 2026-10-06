"""N+1 treatment and equivalence verification. `docs/TECHNICAL_DESIGN.md`
section 23's `verified_treatment`: "optimized operation executed,
result-equivalence contract passed, and query/time comparison stable."
`compare.py` is pure, over two already-captured `WorkloadIR`s (BE-20/21/22's
own two-run output); running a baseline and a treatment capture is the
caller's job (a later `pgproof verify`), the same split every other adapter
under `adapters/` since BE-23 already follows.
"""

from __future__ import annotations
