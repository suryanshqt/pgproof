"""Schema/code reconciliation: canonical matching between two `SchemaIR`s plus `CodeIR`.

`docs/TECHNICAL_DESIGN.md` section 9 lists the disagreement kinds a reconciler
must be able to report. Objects are matched by the canonical `TableId`/`ColumnId`
identity `docs/ARCHITECTURE.md` section 6 already fixes (never by name or OID),
so a rename that both sources agree on is not mistaken for a drift.

Only checks this module can answer without guessing are implemented; the rest are
explicit non-scope, named below rather than approximated:

- `mismatched_type`/`mismatched_default`: BE-08 and BE-09 each record a column's
  type/default as independently `ast.unparse`d source text (e.g. `sa.Integer()`
  versus `Integer()` for the same type), so literal comparison would flag nearly
  every column. Real type-equivalence needs a normalization table this module
  does not have.
- `mismatched_uniqueness`/`cascade_mismatch`: BE-09 does not parse `__table_args__`
  (a composite `UniqueConstraint`/`CheckConstraint` there is invisible to the ORM
  side), so a constraint-set diff would report every such constraint as
  physical-only, which is a BE-09 blind spot, not a real disagreement.
- `optionality_nullability_inconsistent`: `RelationshipIR` carries no optionality
  field distinct from cardinality; adding one is a BE-09 parser change, out of
  this roadmap item's scope.
- A one-to-one relationship (`uselist=False`) does not say which side holds the
  physical foreign key, so relationship/foreign-key matching below only covers
  the unambiguous many-to-one side.

A primary key column's `nullable` text is excluded from the nullability check on
both sides: a migration author who writes `primary_key=True` without also writing
`nullable=False` still gets a NOT NULL column from PostgreSQL, but BE-08's parser
(matching plain `sa.Column` semantics) defaults an unstated `nullable` to `True`
regardless, while BE-09 infers it from the Python annotation instead. Comparing
those two textual defaults would flag every primary key in every fixture.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from pgproof.domain.evidence import EvidenceGraph, EvidenceKind, EvidenceRef
from pgproof.domain.identifiers import frame_components, table_names
from pgproof.domain.ir.code import Cardinality, CodeIR, RelationshipIR
from pgproof.domain.ir.schema import ColumnIR, ConstraintIR, ConstraintKind, SchemaIR, TableIR
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum
from pgproof.domain.sources import SourceRef

_FK_HOLDING_CARDINALITIES = (Cardinality.MANY_TO_ONE,)


class ObservationKind(SnakeCaseEnum):
    """A disagreement, or a notable one-sided declaration, between two sources."""

    ORM_ONLY_RELATIONSHIP = "orm_only_relationship"
    PHYSICAL_FK_WITHOUT_ORM_RELATIONSHIP = "physical_fk_without_orm_relationship"
    MISMATCHED_NULLABILITY = "mismatched_nullability"
    MODEL_REFERENCES_MISSING_PHYSICAL_OBJECT = "model_references_missing_physical_object"
    PHYSICAL_OBJECT_ABSENT_FROM_MODELS = "physical_object_absent_from_models"


class Observation(Contract):
    """One reconciled finding, citing the evidence that backs it.

    `docs/PRODUCT_SPEC.md` section 7: a fact found by static analysis alone is
    `observed`, never `inferred` — inference is reserved for risk/recommendation
    reasoning layered on top of this, in a later rule engine.
    """

    kind: ObservationKind
    affected_objects: tuple[NonEmptyText, ...]
    summary: NonEmptyText
    evidence_refs: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def _validate_contract(self) -> Self:
        if not self.affected_objects:
            raise ValueError("an observation must name at least one affected object")
        return self


class ReconciliationReport(Contract):
    """Every observation from one reconciliation pass, plus the evidence it cites."""

    observations: tuple[Observation, ...] = ()
    evidence: EvidenceGraph = EvidenceGraph()


def _evidence_id(kind: ObservationKind, affected_objects: tuple[str, ...]) -> str:
    return frame_components("reconciliation", kind.value, list(affected_objects))


class _Builder:
    def __init__(self) -> None:
        self._observations: list[Observation] = []
        self._evidence: list[EvidenceRef] = []

    def emit(
        self,
        kind: ObservationKind,
        affected_objects: tuple[str, ...],
        summary: str,
        source: SourceRef | None = None,
    ) -> None:
        ref_id = _evidence_id(kind, affected_objects)
        self._evidence.append(
            EvidenceRef(
                id=ref_id,
                kind=EvidenceKind.OBSERVED,
                summary=summary,
                source=source,
                content_hash=source.content_hash if source is not None else None,
            )
        )
        self._observations.append(
            Observation(
                kind=kind,
                affected_objects=affected_objects,
                summary=summary,
                evidence_refs=(ref_id,),
            )
        )

    def build(self) -> ReconciliationReport:
        return ReconciliationReport(
            observations=tuple(self._observations),
            evidence=EvidenceGraph(refs=tuple(self._evidence)),
        )


def _table_name(table_id: str) -> str:
    return table_names(table_id)[1]


def _primary_key_columns(schema: SchemaIR) -> frozenset[str]:
    return frozenset(
        column
        for constraint in schema.constraints
        if constraint.kind is ConstraintKind.PRIMARY_KEY
        for column in constraint.columns
    )


def _reconcile_columns(
    builder: _Builder,
    orm_table: TableIR,
    physical_table: TableIR,
    physical_key_columns: frozenset[str],
    orm_key_columns: frozenset[str],
) -> None:
    orm_columns: dict[str, ColumnIR] = {column.id: column for column in orm_table.columns}
    physical_columns: dict[str, ColumnIR] = {column.id: column for column in physical_table.columns}
    for column_id, orm_column in orm_columns.items():
        physical_column = physical_columns.get(column_id)
        if physical_column is None:
            builder.emit(
                ObservationKind.MODEL_REFERENCES_MISSING_PHYSICAL_OBJECT,
                (column_id,),
                f"{orm_table.name}.{orm_column.name}: declared by the ORM but not created by "
                "any migration",
                orm_column.source,
            )
            continue
        is_primary_key = column_id in physical_key_columns or column_id in orm_key_columns
        if not is_primary_key and orm_column.nullable != physical_column.nullable:
            builder.emit(
                ObservationKind.MISMATCHED_NULLABILITY,
                (column_id,),
                f"{orm_table.name}.{orm_column.name}: the ORM declares nullable="
                f"{orm_column.nullable}, the migration creates nullable={physical_column.nullable}",
                orm_column.source,
            )
    for column_id, physical_column in physical_columns.items():
        if column_id not in orm_columns:
            builder.emit(
                ObservationKind.PHYSICAL_OBJECT_ABSENT_FROM_MODELS,
                (column_id,),
                f"{physical_table.name}.{physical_column.name}: created by a migration but not "
                "declared by any ORM model",
                physical_column.source,
            )


def _reconcile_tables(builder: _Builder, physical: SchemaIR, orm_schema: SchemaIR) -> None:
    physical_tables = {table.id: table for table in physical.tables}
    orm_tables = {table.id: table for table in orm_schema.tables}
    physical_key_columns = _primary_key_columns(physical)
    orm_key_columns = _primary_key_columns(orm_schema)
    for table_id, orm_table in orm_tables.items():
        physical_table = physical_tables.get(table_id)
        if physical_table is None:
            builder.emit(
                ObservationKind.MODEL_REFERENCES_MISSING_PHYSICAL_OBJECT,
                (table_id,),
                f"{orm_table.name}: declared by the ORM but not created by any migration",
                orm_table.source,
            )
            continue
        _reconcile_columns(
            builder, orm_table, physical_table, physical_key_columns, orm_key_columns
        )
    for table_id, physical_table in physical_tables.items():
        if table_id not in orm_tables:
            builder.emit(
                ObservationKind.PHYSICAL_OBJECT_ABSENT_FROM_MODELS,
                (table_id,),
                f"{physical_table.name}: created by a migration but not declared by any ORM model",
                physical_table.source,
            )


def _foreign_key_pairs(schema: SchemaIR) -> dict[tuple[str, str], ConstraintIR]:
    pairs: dict[tuple[str, str], ConstraintIR] = {}
    for constraint in schema.constraints:
        if (
            constraint.kind is ConstraintKind.FOREIGN_KEY
            and constraint.referenced_table is not None
        ):
            pairs.setdefault((constraint.table, constraint.referenced_table), constraint)
    return pairs


def _fk_holding_relationships(code: CodeIR) -> dict[tuple[str, str], RelationshipIR]:
    relationships: dict[tuple[str, str], RelationshipIR] = {}
    for relationship in code.relationships:
        if relationship.cardinality in _FK_HOLDING_CARDINALITIES:
            relationships.setdefault(
                (relationship.source_table, relationship.target_table), relationship
            )
    return relationships


def _reconcile_relationships(builder: _Builder, physical: SchemaIR, code: CodeIR) -> None:
    foreign_keys = _foreign_key_pairs(physical)
    relationships = _fk_holding_relationships(code)
    for pair, relationship in relationships.items():
        if pair not in foreign_keys:
            source_table, target_table = pair
            builder.emit(
                ObservationKind.ORM_ONLY_RELATIONSHIP,
                (source_table, target_table),
                f"{relationship.name}: the ORM declares a relationship from "
                f"{_table_name(source_table)} to {_table_name(target_table)}, but no physical "
                "foreign key backs it",
                relationship.source,
            )
    for pair, constraint in foreign_keys.items():
        if pair not in relationships:
            source_table, target_table = pair
            builder.emit(
                ObservationKind.PHYSICAL_FK_WITHOUT_ORM_RELATIONSHIP,
                (source_table, target_table),
                f"{constraint.name}: a physical foreign key exists from "
                f"{_table_name(source_table)} to {_table_name(target_table)}, but no ORM "
                "relationship declares it",
            )


def reconcile(physical: SchemaIR, orm_schema: SchemaIR, code: CodeIR) -> ReconciliationReport:
    """Reconcile a statically-replayed migration schema against ORM-declared design.

    Matching is provenance-generic: it joins on `TableId`/`ColumnId` alone, so a
    later physical-catalog source (BE-18) can be fed through the same function
    without changes.
    """
    builder = _Builder()
    _reconcile_tables(builder, physical, orm_schema)
    _reconcile_relationships(builder, physical, code)
    return builder.build()


def evidence_for_object(observations: tuple[Observation, ...], object_id: str) -> tuple[str, ...]:
    """Evidence ids attached to every observation naming `object_id`, for traversal."""
    return tuple(
        sorted(
            {
                ref
                for observation in observations
                if object_id in observation.affected_objects
                for ref in observation.evidence_refs
            }
        )
    )


def is_stale(ref: EvidenceRef, current_content_hash: str) -> bool:
    """Whether a citation's recorded content hash no longer matches the source it cites.

    An evidence ref with no hash at all (a `user_confirmed` or fixture-scale claim
    with no file location) is never stale by this check.
    """
    return ref.content_hash is not None and ref.content_hash != current_content_hash
