"""Deterministic data generation. `docs/TECHNICAL_DESIGN.md` section 18.

`plan` is pure (no psycopg import, no wall clock, no `random` module state);
`load` is the psycopg half that runs it against a live database.
"""
