"""Static report, share inventory, and PR-diff rendering. `docs/PR_ROADMAP.md`'s
BE-34. Pure text/structure logic only; reading `.pgproof` artifacts and writing
the share bundle to disk is `pgproof.cli.commands.share` (adapters cannot
import `pgproof.store`, per `tests/unit/test_dependency_boundaries.py`).
"""

from __future__ import annotations
