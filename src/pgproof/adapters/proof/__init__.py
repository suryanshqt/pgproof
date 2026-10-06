"""Portable proof bundle and reproduction. `docs/TECHNICAL_DESIGN.md` section
26. `bundle.py` writes/reads the on-disk directory (pure, no database, no
subprocess); `reproduce.py` re-runs the measurement against a live database
and compares against what the bundle recorded.
"""

from __future__ import annotations
