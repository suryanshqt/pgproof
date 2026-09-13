"""SchemaIR: the physical or provisional database design.

`provenance` distinguishes a fact read from a migrated PostgreSQL catalog from
one reconstructed statically, which `docs/TECHNICAL_DESIGN.md` section 6 requires:
static reconstruction MUST NOT masquerade as final physical truth.
"""

from __future__ import annotations

from pgproof.domain.identifiers import ColumnId, MigrationId, TableId
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum
from pgproof.domain.sources import SourceRef


class SchemaProvenance(SnakeCaseEnum):
    """Where a schema fact came from."""

    PHYSICAL_CATALOG = "physical_catalog"
    STATIC_MIGRATION = "static_migration"
    ORM_DECLARATION = "orm_declaration"
    UNRESOLVED = "unresolved"


class ConstraintKind(SnakeCaseEnum):
    PRIMARY_KEY = "primary_key"
    FOREIGN_KEY = "foreign_key"
    UNIQUE = "unique"
    CHECK = "check"
    NOT_NULL = "not_null"
    EXCLUSION = "exclusion"


class ReferentialAction(SnakeCaseEnum):
    NO_ACTION = "no_action"
    RESTRICT = "restrict"
    CASCADE = "cascade"
    SET_NULL = "set_null"
    SET_DEFAULT = "set_default"


class IndexMethod(SnakeCaseEnum):
    BTREE = "btree"
    HASH = "hash"
    GIST = "gist"
    GIN = "gin"
    SPGIST = "spgist"
    BRIN = "brin"


class SortDirection(SnakeCaseEnum):
    ASC = "asc"
    DESC = "desc"


class ColumnIR(Contract):
    id: ColumnId
    name: NonEmptyText
    data_type: NonEmptyText
    nullable: bool
    default_expression: NonEmptyText | None = None
    is_generated: bool = False
    is_identity: bool = False
    provenance: SchemaProvenance
    source: SourceRef | None = None


class ConstraintIR(Contract):
    name: NonEmptyText
    kind: ConstraintKind
    table: TableId
    columns: tuple[ColumnId, ...] = ()
    referenced_table: TableId | None = None
    referenced_columns: tuple[ColumnId, ...] = ()
    on_delete: ReferentialAction | None = None
    on_update: ReferentialAction | None = None
    expression: NonEmptyText | None = None
    provenance: SchemaProvenance
    introduced_by: MigrationId | None = None


class IndexKeyIR(Contract):
    column: ColumnId | None = None
    expression: NonEmptyText | None = None
    direction: SortDirection = SortDirection.ASC


class IndexIR(Contract):
    name: NonEmptyText
    table: TableId
    method: IndexMethod = IndexMethod.BTREE
    keys: tuple[IndexKeyIR, ...]
    included_columns: tuple[ColumnId, ...] = ()
    is_unique: bool = False
    predicate: NonEmptyText | None = None
    provenance: SchemaProvenance
    introduced_by: MigrationId | None = None


class TableIR(Contract):
    id: TableId
    schema_name: NonEmptyText
    name: NonEmptyText
    columns: tuple[ColumnIR, ...] = ()
    provenance: SchemaProvenance
    source: SourceRef | None = None
    comment: NonEmptyText | None = None


class UnsupportedConstruct(Contract):
    """A construct the parser saw but declined to interpret.

    `docs/PRODUCT_SPEC.md` section 7 forbids hiding unsupported inputs, so these
    are first-class contract data rather than log output.
    """

    kind: NonEmptyText
    reason: NonEmptyText
    source: SourceRef | None = None


class SchemaIR(Contract):
    """The reconstructed database design."""

    provenance: SchemaProvenance
    tables: tuple[TableIR, ...] = ()
    constraints: tuple[ConstraintIR, ...] = ()
    indexes: tuple[IndexIR, ...] = ()
    extensions: tuple[NonEmptyText, ...] = ()
    migration_head: MigrationId | None = None
    migration_revisions: tuple[MigrationId, ...] = ()
    unsupported: tuple[UnsupportedConstruct, ...] = ()
