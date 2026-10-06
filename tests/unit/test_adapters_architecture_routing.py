"""`adapters.architecture.routing.route_operation` against synthetic
`OperationIR`/`ContextIR` fixtures. `docs/TECHNICAL_DESIGN.md` section 25:
"every operation receives one of: primary required; replica eligible;
either; unknown/blocked... no replica-lag number is invented."
"""

from __future__ import annotations

from pgproof.adapters.architecture.routing import RoutingVerdict, route_operation, route_workload
from pgproof.domain.identifiers import operation_id
from pgproof.domain.ir.context import ConsistencyRequirement, ContextIR
from pgproof.domain.ir.workload import OperationIR, OperationPhase, WorkloadCoverage, WorkloadIR
from pgproof.domain.sources import SourceRef

_DIGEST = "sha256:" + "a" * 64
_OP = operation_id("pytest", "tests/test_orders.py::test_x", "call")


def _operation(*, tables_written: tuple[str, ...] = (), symbol: str | None = None) -> OperationIR:
    entry_point = (
        SourceRef(path="app/repo.py", line=1, content_hash=_DIGEST, symbol=symbol)
        if symbol
        else None
    )
    return OperationIR(
        id=_OP, phase=OperationPhase.CALL, tables_written=tables_written, entry_point=entry_point
    )


def test_a_write_operation_is_always_primary_required() -> None:
    operation = _operation(tables_written=("public.orders",), symbol="list_tenant_orders")
    context = ContextIR(
        consistency_requirements=(
            ConsistencyRequirement(
                operation_label="list_tenant_orders", requires_read_after_write=False
            ),
        )
    )
    routing = route_operation(operation, context)
    assert routing.verdict is RoutingVerdict.PRIMARY_REQUIRED


def test_a_read_operation_with_no_matched_requirement_is_unknown_blocked() -> None:
    operation = _operation(symbol="list_tenant_orders")
    routing = route_operation(operation, ContextIR())
    assert routing.verdict is RoutingVerdict.UNKNOWN_BLOCKED


def test_an_operation_with_no_entry_point_cannot_be_matched_and_is_unknown_blocked() -> None:
    operation = _operation()
    context = ContextIR(
        consistency_requirements=(
            ConsistencyRequirement(
                operation_label="list_tenant_orders", requires_read_after_write=False
            ),
        )
    )
    routing = route_operation(operation, context)
    assert routing.verdict is RoutingVerdict.UNKNOWN_BLOCKED


def test_a_confirmed_read_only_operation_is_replica_eligible() -> None:
    operation = _operation(symbol="list_tenant_orders")
    context = ContextIR(
        consistency_requirements=(
            ConsistencyRequirement(
                operation_label="list_tenant_orders", requires_read_after_write=False
            ),
        )
    )
    routing = route_operation(operation, context)
    assert routing.verdict is RoutingVerdict.REPLICA_ELIGIBLE


def test_a_read_after_write_operation_with_zero_lag_tolerance_is_primary_required() -> None:
    operation = _operation(symbol="list_tenant_orders")
    context = ContextIR(
        consistency_requirements=(
            ConsistencyRequirement(
                operation_label="list_tenant_orders",
                requires_read_after_write=True,
                lag_tolerance_seconds=None,
            ),
        )
    )
    routing = route_operation(operation, context)
    assert routing.verdict is RoutingVerdict.PRIMARY_REQUIRED


def test_a_read_after_write_operation_with_a_positive_lag_tolerance_is_either() -> None:
    operation = _operation(symbol="list_tenant_orders")
    context = ContextIR(
        consistency_requirements=(
            ConsistencyRequirement(
                operation_label="list_tenant_orders",
                requires_read_after_write=True,
                lag_tolerance_seconds=5,
            ),
        )
    )
    routing = route_operation(operation, context)
    assert routing.verdict is RoutingVerdict.EITHER
    assert "5s" in routing.reason


def test_route_workload_routes_every_operation() -> None:
    workload = WorkloadIR(
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
        operations=(_operation(tables_written=("public.orders",)), _operation(symbol="other")),
    )
    routings = route_workload(workload, ContextIR())
    assert len(routings) == 2
