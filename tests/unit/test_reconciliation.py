"""Schema/code reconciliation: canonical matching, disagreement observations, evidence."""

from pathlib import Path

import pytest

from pgproof.adapters.repository.alembic_static import parse_migrations
from pgproof.adapters.repository.sqlalchemy_static import parse_models
from pgproof.domain.evidence import EvidenceKind, EvidenceRef
from pgproof.domain.identifiers import column_id, table_id
from pgproof.domain.ir.code import Cardinality, CodeIR, RelationshipIR
from pgproof.domain.ir.schema import (
    ColumnIR,
    ConstraintIR,
    ConstraintKind,
    SchemaIR,
    SchemaProvenance,
    TableIR,
)
from pgproof.domain.reconciliation import (
    Observation,
    ObservationKind,
    ReconciliationReport,
    evidence_for_object,
    is_stale,
    reconcile,
)
from pgproof.domain.sources import SourceRef

FIXTURES = Path(__file__).parents[2] / "fixtures"
_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64


def _source(hash_value: str = _HASH_A) -> SourceRef:
    return SourceRef(path="app/models.py", line=1, content_hash=hash_value)


def _table(name: str, provenance: SchemaProvenance, columns: tuple[ColumnIR, ...] = ()) -> TableIR:
    return TableIR(
        id=table_id("public", name),
        schema_name="public",
        name=name,
        columns=columns,
        provenance=provenance,
        source=_source(),
    )


def _column(
    table: str,
    name: str,
    *,
    nullable: bool,
    provenance: SchemaProvenance,
    source: SourceRef | None = None,
) -> ColumnIR:
    return ColumnIR(
        id=column_id(table_id("public", table), name),
        name=name,
        data_type="int",
        nullable=nullable,
        provenance=provenance,
        source=source if source is not None else _source(),
    )


def _pk(table: str, column: str, provenance: SchemaProvenance) -> ConstraintIR:
    return ConstraintIR(
        name=f"pk_{table}",
        kind=ConstraintKind.PRIMARY_KEY,
        table=table_id("public", table),
        columns=(column_id(table_id("public", table), column),),
        provenance=provenance,
    )


def _fk(
    source_table: str, column: str, target_table: str, provenance: SchemaProvenance
) -> ConstraintIR:
    return ConstraintIR(
        name=f"fk_{source_table}_{column}",
        kind=ConstraintKind.FOREIGN_KEY,
        table=table_id("public", source_table),
        columns=(column_id(table_id("public", source_table), column),),
        referenced_table=table_id("public", target_table),
        referenced_columns=(column_id(table_id("public", target_table), "id"),),
        provenance=provenance,
    )


def _relationship(
    name: str, source_table: str, target_table: str, cardinality: Cardinality
) -> RelationshipIR:
    return RelationshipIR(
        name=name,
        source_table=table_id("public", source_table),
        target_table=table_id("public", target_table),
        cardinality=cardinality,
        source=_source(),
    )


# --------------------------------------------------------------------------- #
# Golden: the real demo-broken/demo-clean fixtures, not built for this PR
# --------------------------------------------------------------------------- #
def _reconcile_fixture(name: str) -> ReconciliationReport:
    root = FIXTURES / name
    versions = sorted((root / "migrations" / "versions").glob("*.py"))
    physical = parse_migrations(versions, root=root).schema
    orm = parse_models([root / "app" / "models.py"], root=root)
    return reconcile(physical, orm.schema, orm.code)


def test_demo_broken_surfaces_exactly_the_planted_tenant_fk_gap() -> None:
    report = _reconcile_fixture("demo-broken")
    assert len(report.observations) == 1
    observation = report.observations[0]
    assert observation.kind is ObservationKind.ORM_ONLY_RELATIONSHIP
    assert observation.affected_objects == (
        table_id("public", "orders"),
        table_id("public", "tenants"),
    )
    assert observation.evidence_refs
    assert set(observation.evidence_refs) <= report.evidence.ids


def test_demo_clean_has_no_disagreements() -> None:
    report = _reconcile_fixture("demo-clean")
    assert report.observations == ()
    assert report.evidence.refs == ()


# --------------------------------------------------------------------------- #
# Table/column matching
# --------------------------------------------------------------------------- #
def test_a_table_the_orm_declares_but_no_migration_creates_is_reported() -> None:
    orm_schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=(_table("widgets", SchemaProvenance.ORM_DECLARATION),),
    )
    physical = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.MODEL_REFERENCES_MISSING_PHYSICAL_OBJECT
    assert report.observations[0].affected_objects == (table_id("public", "widgets"),)


def test_a_table_a_migration_creates_but_no_model_declares_is_reported_not_assumed_wrong() -> None:
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(_table("audit_log", SchemaProvenance.STATIC_MIGRATION),),
    )
    orm_schema = SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION)
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.PHYSICAL_OBJECT_ABSENT_FROM_MODELS


def test_a_column_the_orm_declares_but_the_migration_does_not_create_is_reported() -> None:
    orm_schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.ORM_DECLARATION,
                (
                    _column(
                        "widgets",
                        "label",
                        nullable=True,
                        provenance=SchemaProvenance.ORM_DECLARATION,
                    ),
                ),
            ),
        ),
    )
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(_table("widgets", SchemaProvenance.STATIC_MIGRATION),),
    )
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert len(report.observations) == 1
    kind = ObservationKind.MODEL_REFERENCES_MISSING_PHYSICAL_OBJECT
    assert report.observations[0].kind is kind
    assert report.observations[0].affected_objects == (
        column_id(table_id("public", "widgets"), "label"),
    )


def test_a_column_a_migration_creates_but_the_orm_does_not_declare_is_reported() -> None:
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.STATIC_MIGRATION,
                (
                    _column(
                        "widgets",
                        "legacy_flag",
                        nullable=True,
                        provenance=SchemaProvenance.STATIC_MIGRATION,
                    ),
                ),
            ),
        ),
    )
    orm_schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=(_table("widgets", SchemaProvenance.ORM_DECLARATION),),
    )
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.PHYSICAL_OBJECT_ABSENT_FROM_MODELS


def test_a_nullability_disagreement_on_a_matched_non_key_column_is_reported() -> None:
    orm_schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.ORM_DECLARATION,
                (
                    _column(
                        "widgets",
                        "label",
                        nullable=False,
                        provenance=SchemaProvenance.ORM_DECLARATION,
                    ),
                ),
            ),
        ),
    )
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.STATIC_MIGRATION,
                (
                    _column(
                        "widgets",
                        "label",
                        nullable=True,
                        provenance=SchemaProvenance.STATIC_MIGRATION,
                    ),
                ),
            ),
        ),
    )
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.MISMATCHED_NULLABILITY


def test_a_primary_key_columns_nullable_text_is_never_compared() -> None:
    """BE-08 defaults an unstated `nullable` to True; BE-09 infers it from the
    annotation. Both are right about the same PostgreSQL NOT NULL column."""
    orm_schema = SchemaIR(
        provenance=SchemaProvenance.ORM_DECLARATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.ORM_DECLARATION,
                (
                    _column(
                        "widgets", "id", nullable=False, provenance=SchemaProvenance.ORM_DECLARATION
                    ),
                ),
            ),
        ),
        constraints=(_pk("widgets", "id", SchemaProvenance.ORM_DECLARATION),),
    )
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        tables=(
            _table(
                "widgets",
                SchemaProvenance.STATIC_MIGRATION,
                (
                    _column(
                        "widgets", "id", nullable=True, provenance=SchemaProvenance.STATIC_MIGRATION
                    ),
                ),
            ),
        ),
        constraints=(_pk("widgets", "id", SchemaProvenance.STATIC_MIGRATION),),
    )
    report = reconcile(physical, orm_schema, CodeIR(orm="sqlalchemy"))
    assert report.observations == ()


# --------------------------------------------------------------------------- #
# Relationship/foreign-key matching
# --------------------------------------------------------------------------- #
def test_an_orm_relationship_with_no_backing_physical_fk_is_reported() -> None:
    physical = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    code = CodeIR(
        orm="sqlalchemy",
        relationships=(_relationship("tenant", "orders", "tenants", Cardinality.MANY_TO_ONE),),
    )
    report = reconcile(physical, SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION), code)
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.ORM_ONLY_RELATIONSHIP
    ref = report.evidence.refs[0]
    assert ref.source is not None
    assert ref.content_hash == _HASH_A


def test_a_physical_fk_with_no_orm_relationship_is_reported() -> None:
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        constraints=(_fk("orders", "tenant_id", "tenants", SchemaProvenance.STATIC_MIGRATION),),
    )
    report = reconcile(
        physical, SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION), CodeIR(orm="sqlalchemy")
    )
    assert len(report.observations) == 1
    assert report.observations[0].kind is ObservationKind.PHYSICAL_FK_WITHOUT_ORM_RELATIONSHIP
    ref = report.evidence.refs[0]
    assert ref.source is None
    assert ref.content_hash is None


def test_a_matched_relationship_and_foreign_key_produce_no_observation() -> None:
    physical = SchemaIR(
        provenance=SchemaProvenance.STATIC_MIGRATION,
        constraints=(_fk("orders", "tenant_id", "tenants", SchemaProvenance.STATIC_MIGRATION),),
    )
    code = CodeIR(
        orm="sqlalchemy",
        relationships=(_relationship("tenant", "orders", "tenants", Cardinality.MANY_TO_ONE),),
    )
    report = reconcile(physical, SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION), code)
    assert report.observations == ()


def test_a_one_to_one_relationship_is_not_matched_against_a_foreign_key() -> None:
    """`uselist=False` does not say which side holds the physical FK; out of scope."""
    physical = SchemaIR(provenance=SchemaProvenance.STATIC_MIGRATION)
    code = CodeIR(
        orm="sqlalchemy",
        relationships=(_relationship("profile", "authors", "profiles", Cardinality.ONE_TO_ONE),),
    )
    report = reconcile(physical, SchemaIR(provenance=SchemaProvenance.ORM_DECLARATION), code)
    assert report.observations == ()


# --------------------------------------------------------------------------- #
# Evidence traversal and staleness
# --------------------------------------------------------------------------- #
def test_evidence_for_object_finds_every_observation_naming_it() -> None:
    matched = Observation(
        kind=ObservationKind.MISMATCHED_NULLABILITY,
        affected_objects=("public.widgets.label",),
        summary="x",
        evidence_refs=("ev-1", "ev-2"),
    )
    unrelated = Observation(
        kind=ObservationKind.MISMATCHED_NULLABILITY,
        affected_objects=("public.widgets.other",),
        summary="y",
        evidence_refs=("ev-3",),
    )
    assert evidence_for_object((matched, unrelated), "public.widgets.label") == ("ev-1", "ev-2")
    assert evidence_for_object((matched, unrelated), "public.widgets.missing") == ()


def test_is_stale_compares_the_recorded_hash_against_the_current_one() -> None:
    ref = EvidenceRef(
        id="x",
        kind=EvidenceKind.OBSERVED,
        summary="s",
        source=_source(_HASH_A),
        content_hash=_HASH_A,
    )
    assert is_stale(ref, _HASH_B) is True
    assert is_stale(ref, _HASH_A) is False


def test_is_stale_is_false_for_a_source_less_evidence_ref() -> None:
    ref = EvidenceRef(id="x", kind=EvidenceKind.USER_CONFIRMED, summary="s")
    assert is_stale(ref, _HASH_A) is False


# --------------------------------------------------------------------------- #
# Observation itself
# --------------------------------------------------------------------------- #
def test_an_observation_must_name_at_least_one_affected_object() -> None:
    with pytest.raises(ValueError, match="at least one affected object"):
        Observation(kind=ObservationKind.MISMATCHED_NULLABILITY, affected_objects=(), summary="x")
