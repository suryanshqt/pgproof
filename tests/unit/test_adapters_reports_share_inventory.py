"""`adapters.reports.share_inventory`: deterministic listing and leak scanning."""

from __future__ import annotations

from pgproof.adapters.reports.share_inventory import build_share_inventory, find_leaked_text


def test_inventory_entries_are_sorted_by_name() -> None:
    inventory = build_share_inventory({"b": b"22", "a": b"1"})
    assert [entry.name for entry in inventory] == ["a", "b"]


def test_inventory_records_byte_size_and_a_sha256_content_hash() -> None:
    inventory = build_share_inventory({"report": b"hello"})
    entry = inventory[0]
    assert entry.byte_size == 5
    assert entry.content_hash.startswith("sha256:")
    assert len(entry.content_hash) == len("sha256:") + 64


def test_find_leaked_text_reports_nothing_when_nothing_matches() -> None:
    assert find_leaked_text("clean text", forbidden=("/Users/alice/secret-repo",)) == ()


def test_find_leaked_text_reports_a_seeded_canary_actually_present() -> None:
    canary = "PGPROOF-SEEDED-TEST-CANARY-0000000000000000"
    bundle = f"...context before...{canary}...context after..."
    assert find_leaked_text(bundle, forbidden=(canary,)) == (canary,)


def test_find_leaked_text_ignores_an_empty_forbidden_string() -> None:
    assert find_leaked_text("anything", forbidden=("",)) == ()
