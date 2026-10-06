"""Comparing a baseline capture against a treatment capture of the same
operation. `docs/PR_ROADMAP.md`'s BE-29 accept criterion: "demo treatment
preserves declared results and reduces amplification while a deliberately
wrong treatment is rejected."

"Declared results" means the treatment's own test suite still passes: this
module never inspects application data directly (it has no database
connection and no knowledge of what a test asserts), so "preserves declared
results" is operationalized as "the treatment run selected the same tests and
none of them failed" — the test suite's own assertions *are* the declared
equivalence contract, the same way `fixtures/demo-broken`'s and
`fixtures/demo-clean`'s shared `test_order_totals_by_item_matches_stored_total`
already asserts the recomputed total is unchanged regardless of loading
strategy. A treatment that breaks correctness fails its own tests and is
rejected here without this module ever executing or understanding a single
assertion itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgproof.domain.identifiers import OperationId
from pgproof.domain.ir.workload import OperationIR, WorkloadIR


@dataclass(frozen=True)
class TreatmentComparison:
    operation_id: OperationId
    baseline_query_count: int
    treatment_query_count: int
    baseline_duration_us: int | None
    treatment_duration_us: int | None
    # None when the operation (or either run) was not found at all —
    # distinct from a 0 count, which is a real fact about an empty run.
    amplification_reduced: bool | None
    results_equivalent: bool
    unsupported_reason: str | None
    verified: bool


def _find_operation(workload: WorkloadIR, operation_id: OperationId) -> OperationIR | None:
    for operation in workload.operations:
        if operation.id == operation_id:
            return operation
    return None


def _query_count(operation: OperationIR) -> int:
    return sum(operation.query_counts.values())


def compare_treatment(
    baseline: WorkloadIR, treatment: WorkloadIR, *, operation_id: OperationId
) -> TreatmentComparison:
    baseline_operation = _find_operation(baseline, operation_id)
    treatment_operation = _find_operation(treatment, operation_id)

    unsupported_reason: str | None = None
    if baseline_operation is None:
        unsupported_reason = "operation absent from the baseline capture"
    elif treatment_operation is None:
        unsupported_reason = "operation absent from the treatment capture"
    elif baseline.failed_tests > 0:
        unsupported_reason = "baseline itself had failing tests; nothing to preserve"
    elif baseline.selected_tests != treatment.selected_tests:
        unsupported_reason = "baseline and treatment selected a different test set"

    baseline_count = _query_count(baseline_operation) if baseline_operation is not None else 0
    treatment_count = _query_count(treatment_operation) if treatment_operation is not None else 0
    amplification_reduced = (
        None
        if baseline_operation is None or treatment_operation is None
        else treatment_count < baseline_count
    )
    results_equivalent = unsupported_reason is None and treatment.failed_tests == 0

    return TreatmentComparison(
        operation_id=operation_id,
        baseline_query_count=baseline_count,
        treatment_query_count=treatment_count,
        baseline_duration_us=(
            baseline_operation.observed_duration_us if baseline_operation is not None else None
        ),
        treatment_duration_us=(
            treatment_operation.observed_duration_us if treatment_operation is not None else None
        ),
        amplification_reduced=amplification_reduced,
        results_equivalent=results_equivalent,
        unsupported_reason=unsupported_reason,
        verified=bool(amplification_reduced) and results_equivalent,
    )
