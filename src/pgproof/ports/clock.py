"""Time source seam.

Stage timestamps must be deterministic in tests, so every wall-clock read in
`pgproof.store` goes through this port rather than calling `datetime.now`
directly.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class Clock(Protocol):
    def now(self) -> dt.datetime: ...


class SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.UTC)
