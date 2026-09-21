"""WorkloadIR: database activity observed while running selected tests.

Two rules from `docs/PRODUCT_SPEC.md` section 7 are structural here. Observed
counts are never production frequency, so `OperationIR` carries
`observed_executions` and no rate. And captured parameters are described by shape
and hash, never by value, so a private bind cannot reach a shareable artifact.
"""

from __future__ import annotations

from pydantic import Field

from pgproof.domain.identifiers import OperationId, QueryId, TableId
from pgproof.domain.primitives import (
    Contract,
    Microseconds,
    NonEmptyText,
    Sha256,
    SnakeCaseEnum,
)
from pgproof.domain.sources import SourceRef


class StatementClass(SnakeCaseEnum):
    READ = "read"
    WRITE = "write"
    SCHEMA = "schema"
    TRANSACTION = "transaction"
    CONTROL = "control"
    UNSUPPORTED = "unsupported"


class OperationPhase(SnakeCaseEnum):
    SETUP = "setup"
    CALL = "call"
    TEARDOWN = "teardown"


class AmplificationClass(SnakeCaseEnum):
    """Classifications from `docs/TECHNICAL_DESIGN.md` section 23."""

    REPEATED_QUERY = "repeated_query"
    POSSIBLE_AMPLIFICATION = "possible_amplification"
    OBSERVED_N_PLUS_ONE = "observed_n_plus_one"
    VERIFIED_TREATMENT = "verified_treatment"


class WorkloadCoverage(SnakeCaseEnum):
    """Whether the captured workload may be treated as complete."""

    COMPLETE_FOR_SELECTION = "complete_for_selection"
    PARTIAL = "partial"
    NOT_CAPTURED = "not_captured"


class ParameterDescriptor(Contract):
    """Parameter shape without its value."""

    position: int
    data_type: NonEmptyText
    value_hash: Sha256 | None = None
    is_redacted: bool = True


class QueryIR(Contract):
    """A normalised statement, identified by its parse-tree fingerprint."""

    id: QueryId
    statement_class: StatementClass
    normalized_sql: NonEmptyText
    relations: tuple[TableId, ...] = ()
    parameters: tuple[ParameterDescriptor, ...] = ()
    call_sites: tuple[SourceRef, ...] = ()
    # BE-19: set only when `statement_class` is `UNSUPPORTED` because parsing
    # itself failed. `docs/TECHNICAL_DESIGN.md:290`: "Unsupported statements
    # remain visible with parser errors and source occurrences" — `call_sites`
    # already carries the occurrences; this is the error text.
    parse_error: NonEmptyText | None = None


class TransactionIR(Contract):
    """One transaction boundary inside an operation."""

    correlation_id: NonEmptyText
    queries: tuple[QueryId, ...] = ()
    committed: bool


class AmplificationIR(Contract):
    """Repeated child work inside one operation."""

    classification: AmplificationClass
    parent_query: QueryId
    child_query: QueryId
    repetitions: int
    relationship_name: NonEmptyText | None = None
    call_site: SourceRef | None = None


class OperationIR(Contract):
    """An application operation, identified by adapter kind plus test identity."""

    id: OperationId
    phase: OperationPhase
    transactions: tuple[TransactionIR, ...] = ()
    query_counts: dict[QueryId, int] = Field(default_factory=dict)
    tables_read: tuple[TableId, ...] = ()
    tables_written: tuple[TableId, ...] = ()
    amplifications: tuple[AmplificationIR, ...] = ()
    # Executions observed during capture. This is never production frequency.
    observed_executions: int = 1
    observed_duration_us: Microseconds | None = None
    entry_point: SourceRef | None = None


class WorkloadIR(Contract):
    """Captured database activity and its honest boundary."""

    coverage: WorkloadCoverage
    boundary_note: NonEmptyText
    queries: tuple[QueryIR, ...] = ()
    operations: tuple[OperationIR, ...] = ()
    selected_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
