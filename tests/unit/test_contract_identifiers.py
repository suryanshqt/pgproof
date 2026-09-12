"""Stable identity rules from `docs/ARCHITECTURE.md` section 6.

Database OIDs, absolute paths, transient container ids and wall-clock time MUST
NOT define a stable identity. Each test below is one of those prohibitions.
"""

import datetime as dt
import re

import pytest
from pydantic import ValidationError

from pgproof.domain.identifiers import (
    COLUMN_ID_PATTERN,
    TABLE_ID_PATTERN,
    canonical_recommendation_identity,
    column_id,
    column_names,
    decode_identity,
    encode_identity,
    node_id,
    node_parts,
    proof_id,
    table_id,
    table_names,
)
from pgproof.domain.primitives import Contract
from pgproof.domain.recommendations import (
    ChangeKind,
    ProposedChange,
    Recommendation,
    RecommendationCategory,
    RecommendationPriority,
)
from pgproof.domain.sources import SourceRef

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


class IdProbe(Contract):
    table: str | None = None
    column: str | None = None


LEGAL_NAMES = [
    ("public", "orders"),
    ("public", "2024"),
    ("public", "My Table"),
    ("public", "a.b"),
    ("public", "\u00f6rd\u00e9r"),
    ("Public", "Orders"),
    ("public", 'say"hi'),
    ("weird.schema", "weird.table"),
    ("back\\slash", "trailing "),
    ("\u4e2d\u6587", "\u8868"),
]


def test_table_identity_is_schema_qualified() -> None:
    assert table_id("public", "orders") == "public.orders"
    assert column_id("public.orders", "tenant_id") == "public.orders.tenant_id"


@pytest.mark.parametrize(("schema", "table"), LEGAL_NAMES)
def test_every_legal_postgresql_name_round_trips(schema: str, table: str) -> None:
    """Quoted numeric, mixed case, spaces, Unicode, quotes and dots are all legal."""
    identity = table_id(schema, table)
    assert table_names(identity) == (schema, table)
    assert re.match(TABLE_ID_PATTERN, identity), f"pattern rejects {identity!r}"


@pytest.mark.parametrize(("schema", "table"), LEGAL_NAMES)
def test_column_identity_round_trips_over_legal_names(schema: str, table: str) -> None:
    identity = column_id(table_id(schema, table), "a.weird.column")
    assert column_names(identity) == (schema, table, "a.weird.column")
    assert re.match(COLUMN_ID_PATTERN, identity)


def test_a_numeric_logical_name_is_not_treated_as_an_oid() -> None:
    """`"2024"` is a legal table name. Rejecting it confused numeric with OID-derived."""
    assert table_id("public", "2024") == "public.2024"
    assert table_names("public.2024") == ("public", "2024")
    assert table_id("16384", "16385") == "16384.16385"


def test_no_contract_model_carries_an_oid_field() -> None:
    """How OIDs are actually excluded: identity is built from logical names, and
    no model has anywhere to put a catalog number."""
    import importlib
    import pkgutil

    import pgproof.domain as package
    from pgproof.domain.primitives import Contract

    checked = 0
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        module = importlib.import_module(info.name)
        for name in dir(module):
            value = getattr(module, name)
            if isinstance(value, type) and issubclass(value, Contract) and value is not Contract:
                checked += 1
                for field in value.model_fields:
                    assert "oid" not in field.lower().split("_"), f"{name}.{field}"
    assert checked > 20, "model discovery found suspiciously few models"


def test_the_codec_is_collision_free() -> None:
    """Two different part tuples can never encode to the same identity."""
    assert encode_identity("public", "a.b") != encode_identity("public.a", "b")
    seen: dict[str, tuple[str, ...]] = {}
    parts_sets = [
        ("public", "a.b"),
        ("public.a", "b"),
        ("public", "a\\b"),
        ("public\\a", "b"),
        ("a", "b", "c"),
        ("a.b", "c"),
        ("a", "b.c"),
        ("a.b.c",),
    ]
    for parts in parts_sets:
        encoded = encode_identity(*parts)
        assert encoded not in seen, f"{parts} collides with {seen.get(encoded)}"
        seen[encoded] = parts
        assert decode_identity(encoded) == parts


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("not-qualified", "must decode to 2 logical names"),
        ("public", "must decode to 2 logical names"),
        ("public.orders.extra", "must decode to 2 logical names"),
        ("public.", "empty logical name"),
        (".orders", "empty logical name"),
        ("public..orders", "empty logical name"),
        ("public.orders\\", "dangling escape"),
        ("public.ord\\xers", "invalid escape"),
        ("public.orders\x00", "NUL"),
    ],
)
def test_malformed_table_identities_are_rejected(value: str, reason: str) -> None:
    from pgproof.domain.identifiers import _validate_table_id

    with pytest.raises(ValueError, match=re.escape(reason)):
        _validate_table_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "not-qualified",
        "public",
        "public.orders.extra",
        "public.",
        ".orders",
        "public..orders",
        "public.orders\\",
        "public.ord\\xers",
    ],
)
def test_the_json_schema_pattern_rejects_what_python_rejects(value: str) -> None:
    """The reported defect was exactly this disagreement."""
    from pgproof.domain.identifiers import _validate_table_id

    with pytest.raises(ValueError, match=r"logical name|escape|NUL"):
        _validate_table_id(value)
    assert not re.match(TABLE_ID_PATTERN, value), f"pattern accepts {value!r}"


@pytest.mark.parametrize("name", ["", "\x00", "a\x00b"])
def test_empty_and_nul_logical_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match=r"empty|NUL"):
        encode_identity("public", name)


def test_node_identity_keeps_quoted_names_representable() -> None:
    identity = table_id("public", "My Table")
    node = node_id("table", identity)
    assert node == "table:public.My Table"
    assert node_parts(node) == ("table", identity)
    assert table_names(node_parts(node)[1]) == ("public", "My Table")


def test_node_identity_splits_on_the_first_colon_only() -> None:
    node = node_id("query", "sha256:" + "a" * 64)
    assert node_parts(node) == ("query", "sha256:" + "a" * 64)


@pytest.mark.parametrize("kind", ["Table", "1table", "", "table kind"])
def test_malformed_node_kinds_are_rejected(kind: str) -> None:
    with pytest.raises(ValueError, match="not a node id"):
        node_id(kind, "public.orders")


def test_node_identity_needs_a_key() -> None:
    with pytest.raises(ValueError, match="non-empty key"):
        node_id("table", "")


def test_source_identity_is_content_hash_backed_and_relative() -> None:
    ref = SourceRef(path="app/models.py", line=31, content_hash=DIGEST)
    assert ref.identity == f"app/models.py#31@{DIGEST}"
    with pytest.raises(ValidationError, match="repository-relative"):
        SourceRef(path="/abs/app/models.py", line=31, content_hash=DIGEST)


def test_source_identity_changes_when_content_changes() -> None:
    first = SourceRef(path="app/models.py", line=31, content_hash=DIGEST)
    second = SourceRef(path="app/models.py", line=31, content_hash=OTHER_DIGEST)
    assert first.identity != second.identity


def test_proof_identity_is_recommendation_plus_input_manifest_hash() -> None:
    assert proof_id("IDX-002", DIGEST) == f"IDX-002@{DIGEST}"
    with pytest.raises(ValueError, match="not a proof id"):
        proof_id("IDX-002", "not-a-digest")
    with pytest.raises(ValueError, match="not a proof id"):
        proof_id("lowercase-002", DIGEST)


def test_node_identity_is_kind_plus_domain_identity() -> None:
    assert node_id("table", "public.orders") == "table:public.orders"
    with pytest.raises(ValueError, match="not a node id"):
        node_id("Table", "public.orders")


def test_recommendation_identity_ignores_object_order_and_duplicates() -> None:
    rule = "schema_integrity.orm_relationship_without_physical_fk"
    first = canonical_recommendation_identity(rule, ("b.c.d", "a.b.c"))
    second = canonical_recommendation_identity(rule, ("a.b.c", "b.c.d", "a.b.c"))
    assert first == second == f"{rule}(a.b.c,b.c.d)"


def test_recommendation_identity_requires_a_rule_and_an_object() -> None:
    with pytest.raises(ValueError, match="not a rule id"):
        canonical_recommendation_identity("NotARule", ("a.b",))
    with pytest.raises(ValueError, match="at least one object"):
        canonical_recommendation_identity("a.b", ())


def _recommendation(title: str, statement: str) -> Recommendation:
    return Recommendation(
        id="TENANT-001",
        rule="schema_integrity.orm_relationship_without_physical_fk",
        rule_version=1,
        title=title,
        priority=RecommendationPriority.REQUIRED_FOR_CORRECTNESS,
        category=RecommendationCategory.TENANCY,
        statement=statement,
        affected_objects=("public.orders.tenant_id",),
        proposed_change=ProposedChange(kind=ChangeKind.ADD_CONSTRAINT, summary="Add the FK."),
    )


def test_recommendation_identity_survives_a_wording_change() -> None:
    """`docs/TECHNICAL_DESIGN.md` section 13: identity tracks rule and objects."""
    first = _recommendation("Enforce tenant ownership", "The ORM links orders to tenants.")
    second = _recommendation("Add the missing tenant foreign key", "Rewritten entirely.")
    assert first.canonical_identity == second.canonical_identity


def test_no_identity_bearing_model_carries_wall_clock_time() -> None:
    """Wall-clock time may appear in an envelope or a stage, never in an identity."""
    for model in (SourceRef, Recommendation):
        for name, field in model.model_fields.items():
            assert field.annotation not in {dt.datetime, dt.date}, f"{model.__name__}.{name}"
