"""Stable identity rules from `docs/ARCHITECTURE.md` section 6.

Database OIDs, absolute paths, transient container ids and wall-clock time MUST
NOT define a stable identity. Each test below is one of those prohibitions.
"""

import datetime as dt

import pytest
from pydantic import ValidationError

from pgproof.domain.identifiers import (
    canonical_recommendation_identity,
    column_id,
    node_id,
    proof_id,
    table_id,
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


def test_table_identity_is_schema_qualified() -> None:
    assert table_id("public", "orders") == "public.orders"
    assert column_id("public.orders", "tenant_id") == "public.orders.tenant_id"


@pytest.mark.parametrize("value", ["orders", "a.b.c", "", ".orders", "public."])
def test_unqualified_or_overqualified_table_ids_are_rejected(value: str) -> None:
    from pgproof.domain.identifiers import _validate_table_id

    with pytest.raises(ValueError, match="table id"):
        _validate_table_id(value)


@pytest.mark.parametrize("value", ["16384.16385", "public.16384", "16384.orders"])
def test_database_oids_cannot_be_a_table_identity(value: str) -> None:
    """A bare OID must not be parseable as a logical name."""
    from pgproof.domain.identifiers import _validate_table_id

    with pytest.raises(ValueError, match=r"numeric|identifier"):
        _validate_table_id(value)


@pytest.mark.parametrize(
    "value",
    [
        "d9f1c2b3a4e5",
        "d9f1c2b3a4e5f6071829304152637485960718293041526374859607182930415",
    ],
)
def test_container_ids_cannot_be_a_table_identity(value: str) -> None:
    from pgproof.domain.identifiers import _validate_table_id

    with pytest.raises(ValueError, match="table id"):
        _validate_table_id(value)


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
