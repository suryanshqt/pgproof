"""The eight semantic rendering primitives, `docs/TECHNICAL_DESIGN.md` section 28."""

from pgproof.cli.rendering.capabilities import TerminalCapabilities
from pgproof.cli.rendering.marks import Mark
from pgproof.cli.rendering.primitives import (
    decision_question_block,
    evidence_label,
    finding_summary,
    measurement_comparison,
    next_command,
    progress_line,
    stage_line,
    trailer_line,
    unresolved_error_block,
)
from pgproof.domain.evidence import EvidenceKind

_PLAIN = TerminalCapabilities(interactive=False, color=False, unicode=True)
_ASCII = TerminalCapabilities(interactive=False, color=False, unicode=False)


# --------------------------------------------------------------------------- #
# stage line
# --------------------------------------------------------------------------- #
def test_stage_line_without_detail_is_just_the_mark_and_text() -> None:
    assert stage_line(Mark.OK, "Reconstructed provisional design", caps=_PLAIN, width=80) == (
        "✓ Reconstructed provisional design"
    )


def test_stage_line_right_justifies_detail_when_it_fits() -> None:
    line = stage_line(Mark.OK, "left", detail="right", caps=_PLAIN, width=20)
    assert line == "✓ left" + " " * (20 - len("✓ left") - len("right")) + "right"
    assert len(line) == 20


def test_stage_line_wraps_detail_onto_its_own_line_when_it_does_not_fit() -> None:
    line = stage_line(Mark.OK, "a very long line of text", detail="detail", caps=_PLAIN, width=10)
    assert line == "✓ a very long line of text\n    detail"


def test_stage_line_alignment_ignores_ansi_color_codes() -> None:
    colored = TerminalCapabilities(interactive=True, color=True, unicode=True)
    line = stage_line(Mark.OK, "left", detail="right", caps=colored, width=20)
    visible = line.replace("\x1b[32m", "").replace("\x1b[0m", "")
    assert len(visible) == 20


# --------------------------------------------------------------------------- #
# progress line
# --------------------------------------------------------------------------- #
def test_progress_line_never_contains_a_control_code_in_plain_mode() -> None:
    line = progress_line("Analysing schema", caps=_ASCII)
    assert line == "-> Analysing schema"
    assert "\x1b" not in line


# --------------------------------------------------------------------------- #
# evidence label
# --------------------------------------------------------------------------- #
def test_evidence_labels_match_the_shared_language_table() -> None:
    assert evidence_label(EvidenceKind.OBSERVED) == "Observed"
    assert evidence_label(EvidenceKind.USER_CONFIRMED) == "User-confirmed"
    assert evidence_label(EvidenceKind.INFERRED) == "Inferred"
    assert evidence_label(EvidenceKind.VERIFIED_IN_FIXTURE) == "Verified in fixture"


# --------------------------------------------------------------------------- #
# finding summary / decision-question block
# --------------------------------------------------------------------------- #
def test_finding_summary_matches_the_interface_design_reference_shape() -> None:
    text = finding_summary(
        category="required",
        title="Enforce tenant ownership for orders",
        description="The ORM links orders to tenants, but PostgreSQL does not.",
        sources=("app/models/order.py:31 · migration 6a912e",),
        caps=_PLAIN,
        width=80,
    )
    lines = text.splitlines()
    assert lines[0] == "required  Enforce tenant ownership for orders"
    assert lines[1].startswith(" " * 10)
    assert lines[-1] == "        ↳ app/models/order.py:31 · migration 6a912e"


def test_decision_question_block_shares_the_finding_summary_shape() -> None:
    text = decision_question_block(
        kind="question",
        prompt="Must invoice reads be immediately consistent after checkout?",
        sources=("affects primary/replica routing in Availability-ready",),
        caps=_PLAIN,
        width=80,
    )
    assert text.splitlines()[0] == (
        "question  Must invoice reads be immediately consistent after checkout?"
    )


def test_a_block_with_no_description_or_sources_is_a_single_line() -> None:
    text = finding_summary(category="required", title="Title only", caps=_PLAIN, width=80)
    assert text == "required  Title only"


# --------------------------------------------------------------------------- #
# measurement comparison
# --------------------------------------------------------------------------- #
def test_measurement_comparison_aligns_labels_into_one_column() -> None:
    text = measurement_comparison(
        [
            (Mark.OK, "Control A1", "86.2 ms median"),
            (Mark.OK, "Treatment B", "14.3 ms median"),
            (Mark.OK, "Drift control", "84.9 ms median"),
        ],
        caps=_PLAIN,
    )
    lines = text.splitlines()
    value_columns = {line.index("ms") for line in lines}
    assert len(value_columns) == 1, "every value should start at the same column"


def test_measurement_comparison_allows_an_unmarked_row() -> None:
    text = measurement_comparison([(None, "index size", "38 MB")], caps=_PLAIN)
    assert text == "  index size  38 MB"


# --------------------------------------------------------------------------- #
# unresolved / error block
# --------------------------------------------------------------------------- #
def test_unresolved_error_block_matches_the_interface_design_reference_shape() -> None:
    text = unresolved_error_block(
        headline="Migration stopped at revision 91ca21",
        detail='PostgreSQL rejected: column "tenant_id" contains null values',
        boundary="No partial schema was analysed.",
        trailers=(("Logs", ".pgproof/runs/01J7D/migration.log"),),
        caps=_PLAIN,
        width=80,
    )
    lines = text.splitlines()
    assert lines[0] == "× Migration stopped at revision 91ca21"  # noqa: RUF001
    assert lines[1] == ""
    assert "PostgreSQL rejected" in lines[2]
    assert lines[3] == ""
    assert lines[4] == "No partial schema was analysed."
    assert lines[5] == "Logs    .pgproof/runs/01J7D/migration.log"


def test_unresolved_error_block_needs_no_trailers() -> None:
    text = unresolved_error_block(
        headline="Failed", detail="detail", boundary="boundary", caps=_PLAIN, width=80
    )
    assert text.splitlines() == ["× Failed", "", "detail", "", "boundary"]  # noqa: RUF001


# --------------------------------------------------------------------------- #
# next command / trailer line
# --------------------------------------------------------------------------- #
def test_next_command_uses_the_trailer_gutter() -> None:
    assert next_command("pgproof configure .") == "Next    pgproof configure ."


def test_trailer_line_is_reusable_for_other_labels() -> None:
    assert trailer_line("Report", ".pgproof/report/") == "Report  .pgproof/report/"


def test_trailer_line_keeps_one_space_when_the_label_fills_the_gutter() -> None:
    """A label as long as the gutter itself must not collide with its value."""
    assert trailer_line("Included", "3 files") == "Included 3 files"


def test_finding_summary_keeps_one_space_when_the_category_fills_the_gutter() -> None:
    """Same bug class as trailer_line's: a >=10-char category must not collide."""
    text = finding_summary(category="worth eval.", title="Title", caps=_PLAIN, width=80)
    assert text.splitlines()[0] == "worth eval. Title"
