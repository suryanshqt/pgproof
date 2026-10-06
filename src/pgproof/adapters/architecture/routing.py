"""Primary/replica operation routing. `docs/TECHNICAL_DESIGN.md` section 25:
"every operation receives one of: primary required; replica eligible;
either; unknown/blocked... No throughput, failover duration, data-loss
guarantee, or replica-lag number is invented."

Pure: a per-operation verdict from already-captured facts (BE-21's
`OperationIR.tables_written`) and already-confirmed context
(`ContextIR.consistency_requirements`) — no connection, no new measurement.
An operation whose confirmed consistency requirement cannot be found at all
is `unknown_blocked`, never defaulted to either extreme.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgproof.domain.identifiers import OperationId
from pgproof.domain.ir.context import ConsistencyRequirement, ContextIR
from pgproof.domain.ir.workload import OperationIR, WorkloadIR
from pgproof.domain.primitives import SnakeCaseEnum


class RoutingVerdict(SnakeCaseEnum):
    PRIMARY_REQUIRED = "primary_required"
    REPLICA_ELIGIBLE = "replica_eligible"
    EITHER = "either"
    UNKNOWN_BLOCKED = "unknown_blocked"


@dataclass(frozen=True)
class OperationRouting:
    operation: OperationId
    verdict: RoutingVerdict
    reason: str


def _consistency_requirement(
    operation: OperationIR, context: ContextIR
) -> ConsistencyRequirement | None:
    """Matched by `entry_point.symbol` — the one field that names which
    application function this operation actually is, the same label a
    `ConsistencyRequirement` is confirmed against during the context
    interview (`docs/TECHNICAL_DESIGN.md` section 15). An operation with no
    `entry_point` (nothing captured called into application code at all)
    cannot be matched to anything.
    """
    if operation.entry_point is None or operation.entry_point.symbol is None:
        return None
    symbol = operation.entry_point.symbol
    return next(
        (
            requirement
            for requirement in context.consistency_requirements
            if requirement.operation_label == symbol
        ),
        None,
    )


def route_operation(operation: OperationIR, context: ContextIR) -> OperationRouting:
    if operation.tables_written:
        return OperationRouting(
            operation=operation.id,
            verdict=RoutingVerdict.PRIMARY_REQUIRED,
            reason="writes at least one table; a write must reach the primary",
        )

    requirement = _consistency_requirement(operation, context)
    if requirement is None:
        return OperationRouting(
            operation=operation.id,
            verdict=RoutingVerdict.UNKNOWN_BLOCKED,
            reason="no confirmed read-after-write requirement for this operation",
        )
    if not requirement.requires_read_after_write:
        return OperationRouting(
            operation=operation.id,
            verdict=RoutingVerdict.REPLICA_ELIGIBLE,
            reason="confirmed read-only with no read-after-write requirement",
        )
    if not requirement.lag_tolerance_seconds:
        return OperationRouting(
            operation=operation.id,
            verdict=RoutingVerdict.PRIMARY_REQUIRED,
            reason="confirmed to require immediate read-after-write consistency",
        )
    return OperationRouting(
        operation=operation.id,
        verdict=RoutingVerdict.EITHER,
        reason=f"confirmed to tolerate {requirement.lag_tolerance_seconds}s of replica lag",
    )


def route_workload(workload: WorkloadIR, context: ContextIR) -> tuple[OperationRouting, ...]:
    return tuple(route_operation(operation, context) for operation in workload.operations)
