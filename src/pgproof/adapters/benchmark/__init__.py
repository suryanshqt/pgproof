"""Raw benchmark and A1/B/A2 experiment engine. `docs/TECHNICAL_DESIGN.md`
section 20. `statistics.py` is pure (the exact formulas `scripts/
fixture_measurements.py` already validated by hand against
`fixtures/demo-broken`); `run.py` is the psycopg half that produces the raw
samples those formulas are computed over.
"""

from __future__ import annotations
