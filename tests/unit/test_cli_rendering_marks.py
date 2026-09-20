"""Semantic mark glyphs: Unicode/ASCII fallback and color-off plain text."""

import pytest

from pgproof.cli.rendering.capabilities import TerminalCapabilities
from pgproof.cli.rendering.marks import Mark, glyph

_UNICODE_NO_COLOR = TerminalCapabilities(interactive=True, color=False, unicode=True)
_ASCII_NO_COLOR = TerminalCapabilities(interactive=False, color=False, unicode=False)
_UNICODE_COLOR = TerminalCapabilities(interactive=True, color=True, unicode=True)


@pytest.mark.parametrize(
    ("mark", "expected"),
    [
        (Mark.OK, "✓"),
        (Mark.ATTENTION, "!"),
        (Mark.FAILURE, "×"),  # noqa: RUF001 - the exact glyph INTERFACE_DESIGN.md specifies
        (Mark.UNAVAILABLE, "○"),
        (Mark.TRANSITION, "→"),
        (Mark.EVIDENCE, "↳"),
    ],
)
def test_unicode_glyphs_match_the_interface_design_table(mark: Mark, expected: str) -> None:
    assert glyph(mark, _UNICODE_NO_COLOR) == expected


@pytest.mark.parametrize(
    ("mark", "expected"),
    [
        (Mark.OK, "[ok]"),
        (Mark.ATTENTION, "[!]"),
        (Mark.FAILURE, "[x]"),
        (Mark.UNAVAILABLE, "[-]"),
        (Mark.TRANSITION, "->"),
        (Mark.EVIDENCE, ">"),
    ],
)
def test_ascii_fallbacks_match_the_interface_design_table(mark: Mark, expected: str) -> None:
    assert glyph(mark, _ASCII_NO_COLOR) == expected


def test_every_mark_has_no_color_output_free_of_escape_codes() -> None:
    for mark in Mark:
        assert "\x1b" not in glyph(mark, _UNICODE_NO_COLOR)


def test_color_wraps_the_glyph_in_an_sgr_sequence_and_resets_it() -> None:
    text = glyph(Mark.OK, _UNICODE_COLOR)
    assert text.startswith("\x1b[32m")
    assert text.endswith("\x1b[0m")
    assert "✓" in text
