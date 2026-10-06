"""Share inventory and leak scanning.

`docs/PRODUCT_SPEC.md` section 15 requires a "share inventory before export".
`domain.primitives.RepositoryPath` already rejects an absolute path by
construction everywhere source locations are modeled, so the realistic leak
left for this module to catch is an absolute path or secret slipping into the
rendered bundle TEXT itself (an f-string that forgot to use the relative
field). `find_leaked_text` is a plain substring scan, not a general secret
detector: it only catches what the caller names as forbidden, which is enough
to make "no seeded private canary in the export" (`docs/PR_ROADMAP.md`
BE-34) a checkable fact rather than a guess.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class ShareInventoryEntry:
    """One artifact included in a share export."""

    name: str
    byte_size: int
    content_hash: str


def build_share_inventory(artifacts: dict[str, bytes]) -> tuple[ShareInventoryEntry, ...]:
    """One entry per artifact, sorted by name for a deterministic listing."""
    return tuple(
        ShareInventoryEntry(
            name=name,
            byte_size=len(data),
            content_hash=f"sha256:{hashlib.sha256(data).hexdigest()}",
        )
        for name, data in sorted(artifacts.items())
    )


def find_leaked_text(bundle_text: str, *, forbidden: tuple[str, ...]) -> tuple[str, ...]:
    """Which `forbidden` strings actually appear in `bundle_text`, in call order."""
    return tuple(needle for needle in forbidden if needle and needle in bundle_text)
