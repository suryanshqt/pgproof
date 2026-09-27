"""Index candidate generation and HypoPG screening. `docs/TECHNICAL_DESIGN.md`
section 21. `generate.py` is pure (structural comparison against the physical
schema BE-17/18 already introspected); `screen.py` is the optional psycopg
half — screening is never evidence of improvement, only a physical treatment
verified by BE-25's real benchmark ever is.
"""

from __future__ import annotations
