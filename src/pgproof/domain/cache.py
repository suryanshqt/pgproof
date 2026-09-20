"""Stage cache-key derivation.

`docs/ARCHITECTURE.md` section 7 ("Stage cache") fixes the inputs: normalized
stage configuration, upstream artifact hashes, relevant repository file hashes,
adapter/parser/generator version, and PostgreSQL/container identity when
applicable. This is a pure function of those inputs so two runs with identical
inputs always produce the identical `StageSummary.cache_key`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from pgproof.domain.primitives import Sha256


def stage_cache_key(
    *,
    stage_config: Mapping[str, str] | None = None,
    upstream_hashes: Mapping[str, Sha256] | None = None,
    file_hashes: Mapping[str, Sha256] | None = None,
    tool_versions: Mapping[str, str] | None = None,
    environment_identity: Mapping[str, str] | None = None,
) -> Sha256:
    """Hash the declared cache-key inputs, sorted so key order cannot matter."""
    canonical = json.dumps(
        {
            "stage_config": dict(sorted((stage_config or {}).items())),
            "upstream_hashes": dict(sorted((upstream_hashes or {}).items())),
            "file_hashes": dict(sorted((file_hashes or {}).items())),
            "tool_versions": dict(sorted((tool_versions or {}).items())),
            "environment_identity": dict(sorted((environment_identity or {}).items())),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
