"""Semantic marks, `docs/INTERFACE_DESIGN.md` section 4.

"Icons never appear without nearby text." Only the glyph carries color, never
the surrounding line: `docs/INTERFACE_DESIGN.md` section 3 requires color to
reinforce meaning, never to carry it alone.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Final

from pgproof.cli.rendering.capabilities import TerminalCapabilities


class Mark(Enum):
    OK = auto()
    ATTENTION = auto()
    FAILURE = auto()
    UNAVAILABLE = auto()
    TRANSITION = auto()
    EVIDENCE = auto()


# (unicode glyph, ASCII fallback), `docs/INTERFACE_DESIGN.md` section 4's table.
_GLYPHS: Final[dict[Mark, tuple[str, str]]] = {
    Mark.OK: ("✓", "[ok]"),
    Mark.ATTENTION: ("!", "[!]"),
    Mark.FAILURE: ("×", "[x]"),  # noqa: RUF001 - the exact glyph INTERFACE_DESIGN.md specifies
    Mark.UNAVAILABLE: ("○", "[-]"),
    Mark.TRANSITION: ("→", "->"),
    Mark.EVIDENCE: ("↳", ">"),
}

# SGR codes. `docs/INTERFACE_DESIGN.md` section 3: green is completed/verified,
# amber is material attention, red is failure; blue is the one accent color.
_SGR: Final[dict[Mark, str]] = {
    Mark.OK: "32",
    Mark.ATTENTION: "33",
    Mark.FAILURE: "31",
    Mark.UNAVAILABLE: "90",
    Mark.TRANSITION: "34",
    Mark.EVIDENCE: "34",
}


def glyph(mark: Mark, caps: TerminalCapabilities) -> str:
    unicode_glyph, ascii_glyph = _GLYPHS[mark]
    text = unicode_glyph if caps.unicode else ascii_glyph
    if not caps.color:
        return text
    return f"\x1b[{_SGR[mark]}m{text}\x1b[0m"
