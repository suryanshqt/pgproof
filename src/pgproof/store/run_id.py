"""ULID generation for `RunId`.

A run id is a per-invocation correlation label, not a stable content identity;
`docs/ARCHITECTURE.md` section 6 bars wall-clock time from identity, and this is
not identity. `pgproof.domain.primitives.RUN_ID_PATTERN` fixes the alphabet and
length this must produce.
"""

from __future__ import annotations

import os
import time

_CROCKFORD_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    characters = []
    for _ in range(length):
        value, remainder = divmod(value, 32)
        characters.append(_CROCKFORD_BASE32[remainder])
    return "".join(reversed(characters))


def new_run_id() -> str:
    """A 26-character, time-sortable ULID: 10 chars of millisecond timestamp, 16 of randomness."""
    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    return _encode(timestamp_ms, 10) + _encode(randomness, 16)
