"""Terminal capability detection: TTY, `NO_COLOR`, and Unicode support."""

from pgproof.cli.rendering.capabilities import detect_capabilities


class _Stream:
    def __init__(self, *, tty: bool, encoding: str | None = "utf-8") -> None:
        self._tty = tty
        if encoding is not None:
            self.encoding = encoding

    def isatty(self) -> bool:
        return self._tty


def test_a_tty_stream_with_no_env_overrides_gets_color_and_unicode() -> None:
    caps = detect_capabilities(_Stream(tty=True), env={})
    assert caps.interactive is True
    assert caps.color is True
    assert caps.unicode is True


def test_a_non_tty_stream_never_gets_color() -> None:
    caps = detect_capabilities(_Stream(tty=False), env={})
    assert caps.interactive is False
    assert caps.color is False


def test_no_color_env_disables_color_even_on_a_tty() -> None:
    caps = detect_capabilities(_Stream(tty=True), env={"NO_COLOR": "1"})
    assert caps.color is False


def test_no_color_disables_color_regardless_of_its_value() -> None:
    """`NO_COLOR`'s presence disables color; the convention ignores the value."""
    caps = detect_capabilities(_Stream(tty=True), env={"NO_COLOR": ""})
    assert caps.color is False


def test_force_ascii_disables_unicode_even_on_a_utf8_stream() -> None:
    caps = detect_capabilities(_Stream(tty=True), force_ascii=True, env={})
    assert caps.unicode is False


def test_a_non_utf8_encoding_falls_back_to_ascii() -> None:
    caps = detect_capabilities(_Stream(tty=True, encoding="ascii"), env={})
    assert caps.unicode is False


def test_a_missing_encoding_attribute_falls_back_to_ascii() -> None:
    caps = detect_capabilities(_Stream(tty=True, encoding=None), env={})
    assert caps.unicode is False


def test_defaults_to_the_real_process_environment() -> None:
    caps = detect_capabilities(_Stream(tty=True))
    assert isinstance(caps.color, bool)
