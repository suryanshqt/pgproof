"""Validated scalar types: paths, hashes, timestamps, decimals, durations, enums."""

import re
from enum import Enum

import pytest
from pydantic import ValidationError

from pgproof.domain import primitives
from pgproof.domain.primitives import (
    SNAKE_CASE_PATTERN,
    Contract,
    DecimalString,
    Microseconds,
    RepositoryPath,
    Rfc3339Utc,
    Sha256,
    SnakeCaseEnum,
)


class Probe(Contract):
    path: RepositoryPath | None = None
    digest: Sha256 | None = None
    moment: Rfc3339Utc | None = None
    amount: DecimalString | None = None
    duration: Microseconds | None = None


@pytest.mark.parametrize(
    "value",
    [
        "app/models.py",
        "a",
        ".github/workflows/ci.yml",
        "migrations/versions/0002_create_orders.py",
        "src/pgproof/domain/ir/schema.py",
    ],
)
def test_repository_relative_paths_are_accepted(value: str) -> None:
    assert Probe(path=value).path == value


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("/etc/passwd", "repository-relative"),
        ("C:/Windows/system32", "repository-relative"),
        ("~/secrets.txt", "home-relative"),
        ("app\\models.py", "POSIX separators"),
        ("app//models.py", "empty segment"),
        ("../outside.py", "'.' or '..'"),
        ("app/../../etc/passwd", "'.' or '..'"),
        ("app/./models.py", "'.' or '..'"),
        ("app/", "end with a separator"),
        ("", "empty"),
        ("app/\x00.py", "NUL"),
    ],
)
def test_unsafe_paths_are_rejected(value: str, reason: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(reason)):
        Probe(path=value)


@pytest.mark.parametrize("value", ["sha256:" + "0" * 64, "sha256:" + "abcdef0123456789" * 4])
def test_prefixed_lowercase_digests_are_accepted(value: str) -> None:
    assert Probe(digest=value).digest == value


@pytest.mark.parametrize(
    "value",
    [
        "a" * 64,
        "sha256:" + "A" * 64,
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha1:" + "0" * 40,
        "sha256:not-a-digest",
        "",
    ],
)
def test_malformed_digests_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Probe(digest=value)


@pytest.mark.parametrize(
    "value",
    ["2026-01-01T00:00:00Z", "2026-09-12T13:17:54Z", "2026-01-01T00:00:00.123456Z"],
)
def test_utc_timestamps_are_accepted(value: str) -> None:
    assert Probe(moment=value).moment == value


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T00:00:00+05:30",
        "2026-01-01T00:00:00-08:00",
        "2026-01-01T00:00:00",
        "2026-01-01 00:00:00Z",
        "2026-01-01",
        "not a timestamp",
    ],
)
def test_non_utc_or_malformed_timestamps_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="RFC 3339"):
        Probe(moment=value)


@pytest.mark.parametrize("value", ["0", "1", "-1", "400000", "1697400000", "0.0492", "-0.5"])
def test_exact_decimal_strings_are_accepted(value: str) -> None:
    assert Probe(amount=value).amount == value


@pytest.mark.parametrize("value", ["1.0e5", "01", "1.", ".5", "NaN", "Infinity", "1,000", ""])
def test_inexact_or_malformed_decimals_are_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        Probe(amount=value)


def test_durations_are_non_negative_integer_microseconds() -> None:
    assert Probe(duration=0).duration == 0
    assert Probe(duration=9520).duration == 9520
    with pytest.raises(ValidationError):
        Probe(duration=-1)


def test_contract_models_are_frozen() -> None:
    probe = Probe(path="app/models.py")
    with pytest.raises(ValidationError):
        probe.path = "other.py"


def test_additive_fields_are_tolerated_not_rejected() -> None:
    """`docs/ARCHITECTURE.md` section 7: readers tolerate additive fields."""
    probe = Probe.model_validate({"path": "app/models.py", "field_from_a_later_minor": 1})
    assert probe.path == "app/models.py"
    assert not hasattr(probe, "field_from_a_later_minor")


def test_canonical_json_is_byte_stable_and_key_sorted() -> None:
    probe = Probe(duration=1, path="a/b.py", digest="sha256:" + "0" * 64)
    first = probe.canonical_json()
    assert first == probe.canonical_json()
    assert first.index('"digest"') < first.index('"duration"') < first.index('"path"')
    assert " " not in first


def _domain_enums() -> list[type[Enum]]:
    import importlib
    import pkgutil

    import pgproof.domain as package

    found: dict[str, type[Enum]] = {}
    modules = [package]
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        modules.append(importlib.import_module(info.name))
    for module in modules:
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, type) and issubclass(value, Enum) and value is not Enum:
                found[f"{value.__module__}.{value.__name__}"] = value
    return list(found.values())


def test_every_stable_enum_serialises_as_lowercase_snake_case() -> None:
    enums = _domain_enums()
    assert len(enums) >= 15, "enum discovery found suspiciously few enums"
    for enum in enums:
        if enum in {SnakeCaseEnum, primitives.SnakeCaseEnum}:
            continue
        for member in enum:
            assert isinstance(member.value, str), f"{enum.__name__}.{member.name}"
            assert re.match(SNAKE_CASE_PATTERN, member.value), (
                f"{enum.__name__}.{member.name} = {member.value!r} is not snake case"
            )
