"""Semantic terminal rendering primitives, `docs/TECHNICAL_DESIGN.md` section 28.

Eight components: stage line, progress line, evidence label, finding summary,
decision/question block, measurement comparison, unresolved/error block, and
next command. Each is a pure function of structured data and
`TerminalCapabilities`; nothing here writes to a stream. Alignment ignores
ANSI escape sequences so column math is correct whether or not color is on.
"""

from __future__ import annotations

import re
import textwrap
from collections.abc import Sequence
from typing import Final

from pgproof.cli.rendering.capabilities import TerminalCapabilities
from pgproof.cli.rendering.marks import Mark, glyph
from pgproof.domain.evidence import EvidenceKind

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_EVIDENCE_LABELS: Final[dict[EvidenceKind, str]] = {
    EvidenceKind.OBSERVED: "Observed",
    EvidenceKind.USER_CONFIRMED: "User-confirmed",
    EvidenceKind.INFERRED: "Inferred",
    EvidenceKind.VERIFIED_IN_FIXTURE: "Verified in fixture",
}

_LABEL_GUTTER: Final = 10
_TRAILER_GUTTER: Final = 8


def _visible_length(text: str) -> int:
    return len(_ANSI.sub("", text))


def _two_column(left: str, right: str, width: int) -> str:
    """Right-justify `right` if it fits on one line; otherwise wrap it below, indented."""
    gap = width - _visible_length(left) - _visible_length(right)
    if gap >= 2:
        return f"{left}{' ' * gap}{right}"
    return f"{left}\n    {right}"


def stage_line(
    mark: Mark, text: str, *, detail: str | None = None, caps: TerminalCapabilities, width: int
) -> str:
    left = f"{glyph(mark, caps)} {text}"
    return left if detail is None else _two_column(left, detail, width)


def progress_line(text: str, *, caps: TerminalCapabilities) -> str:
    """A stable stage-start/stage-end line. Never animated: safe for CI and non-TTY logs."""
    return f"{glyph(Mark.TRANSITION, caps)} {text}"


def evidence_label(kind: EvidenceKind) -> str:
    """The shared-language display label, `docs/INTERFACE_DESIGN.md` section 2."""
    return _EVIDENCE_LABELS[kind]


def _labeled_block(
    *,
    label: str,
    title: str,
    body: str | None,
    sources: Sequence[str],
    caps: TerminalCapabilities,
    width: int,
) -> str:
    lines = [f"{label:<{_LABEL_GUTTER}}{title}"]
    indent = " " * _LABEL_GUTTER
    if body:
        wrapped = textwrap.fill(body, width=max(width - _LABEL_GUTTER, 20))
        lines.extend(f"{indent}{line}" for line in wrapped.splitlines())
    source_indent = " " * (_LABEL_GUTTER - 2)
    lines.extend(f"{source_indent}{glyph(Mark.EVIDENCE, caps)} {source}" for source in sources)
    return "\n".join(lines)


def finding_summary(
    *,
    category: str,
    title: str,
    description: str | None = None,
    sources: Sequence[str] = (),
    caps: TerminalCapabilities,
    width: int = 80,
) -> str:
    return _labeled_block(
        label=category, title=title, body=description, sources=sources, caps=caps, width=width
    )


def decision_question_block(
    *,
    kind: str,
    prompt: str,
    note: str | None = None,
    sources: Sequence[str] = (),
    caps: TerminalCapabilities,
    width: int = 80,
) -> str:
    return _labeled_block(
        label=kind, title=prompt, body=note, sources=sources, caps=caps, width=width
    )


def measurement_comparison(
    rows: Sequence[tuple[Mark | None, str, str]], *, caps: TerminalCapabilities
) -> str:
    """Tabular label/value rows, numbers aligned in one column across all rows."""
    label_width = max((len(label) for _, label, _ in rows), default=0)
    lines = []
    for mark, label, value in rows:
        prefix = f"{glyph(mark, caps)} " if mark is not None else "  "
        lines.append(f"{prefix}{label:<{label_width}}  {value}")
    return "\n".join(lines)


def unresolved_error_block(
    *,
    headline: str,
    detail: str,
    boundary: str,
    trailers: Sequence[tuple[str, str]] = (),
    caps: TerminalCapabilities,
    width: int = 80,
) -> str:
    lines = [
        f"{glyph(Mark.FAILURE, caps)} {headline}",
        "",
        textwrap.fill(detail, width=width),
        "",
        textwrap.fill(boundary, width=width),
    ]
    lines.extend(trailer_line(label, value) for label, value in trailers)
    return "\n".join(lines)


def trailer_line(label: str, value: str) -> str:
    return f"{label:<{_TRAILER_GUTTER}}{value}"


def next_command(command: str) -> str:
    return trailer_line("Next", command)
