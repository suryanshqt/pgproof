"""CodeIR: the design the application code declares.

An ORM relationship and a physical foreign key are different kinds of edge.
`docs/ARCHITECTURE.md` section 17 requires that they cannot be serialised as the
same relation kind, which is why `RelationshipIR.physical_constraint` is optional
and `is_physically_enforced` is derived from it rather than being settable.
"""

from __future__ import annotations

from pgproof.domain.identifiers import ColumnId, TableId
from pgproof.domain.ir.schema import UnsupportedConstruct
from pgproof.domain.primitives import Contract, NonEmptyText, SnakeCaseEnum
from pgproof.domain.sources import SourceRef


class LoadingStrategy(SnakeCaseEnum):
    SELECT = "select"
    JOINED = "joined"
    SUBQUERY = "subquery"
    SELECTIN = "selectin"
    IMMEDIATE = "immediate"
    NOLOAD = "noload"
    RAISELOAD = "raiseload"
    DYNAMIC = "dynamic"
    UNRESOLVED = "unresolved"


class Cardinality(SnakeCaseEnum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"
    UNRESOLVED = "unresolved"


class ModelIR(Contract):
    """A mapped class."""

    class_name: NonEmptyText
    table: TableId
    module_path: NonEmptyText
    source: SourceRef
    mapped_columns: tuple[ColumnId, ...] = ()


class RelationshipIR(Contract):
    """A relationship declared by the ORM."""

    name: NonEmptyText
    source_table: TableId
    target_table: TableId
    cardinality: Cardinality
    loading_strategy: LoadingStrategy = LoadingStrategy.SELECT
    back_populates: NonEmptyText | None = None
    secondary_table: TableId | None = None
    cascade: tuple[NonEmptyText, ...] = ()
    passive_deletes: bool = False
    # Present only when a physical constraint backs this relationship. An
    # ORM-only relationship leaves it None and can never be read as enforced.
    physical_constraint: NonEmptyText | None = None
    source: SourceRef

    @property
    def is_physically_enforced(self) -> bool:
        return self.physical_constraint is not None


class RepositoryOperation(Contract):
    """A callable in the application that issues database work."""

    name: NonEmptyText
    qualified_name: NonEmptyText
    source: SourceRef


class CodeIR(Contract):
    """The design the application declares, independent of any catalog."""

    orm: NonEmptyText
    models: tuple[ModelIR, ...] = ()
    relationships: tuple[RelationshipIR, ...] = ()
    operations: tuple[RepositoryOperation, ...] = ()
    unsupported: tuple[UnsupportedConstruct, ...] = ()
