"""Terminal capability detection, `docs/INTERFACE_DESIGN.md` section 4.

"Honor `NO_COLOR` and non-TTY output. Detect Unicode support; `--ascii`
forces fallback." Detection takes the stream and environment as arguments
rather than reading `sys.stdout`/`os.environ` directly, so it is deterministic
in tests.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class _TextStream(Protocol):
    """The minimal stream shape detection needs; satisfied by `sys.stdout`."""

    def isatty(self) -> bool: ...

    @property
    def encoding(self) -> str: ...


@dataclass(frozen=True)
class TerminalCapabilities:
    interactive: bool
    color: bool
    unicode: bool


def detect_capabilities(
    stream: _TextStream,
    *,
    force_ascii: bool = False,
    env: Mapping[str, str] | None = None,
) -> TerminalCapabilities:
    resolved_env = env if env is not None else os.environ
    interactive = stream.isatty()
    color = interactive and "NO_COLOR" not in resolved_env
    unicode_supported = not force_ascii and _stream_supports_unicode(stream)
    return TerminalCapabilities(interactive=interactive, color=color, unicode=unicode_supported)


def _stream_supports_unicode(stream: _TextStream) -> bool:
    encoding = getattr(stream, "encoding", None) or ""
    return "utf" in encoding.lower()
