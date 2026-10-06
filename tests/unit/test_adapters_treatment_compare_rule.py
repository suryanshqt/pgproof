"""`adapters.treatment.compare.compare_treatment` against synthetic
`WorkloadIR` fixtures. `docs/PR_ROADMAP.md`'s BE-29 accept criterion: "demo
treatment preserves declared results and reduces amplification while a
deliberately wrong treatment is rejected."
"""

from __future__ import annotations

from pgproof.adapters.treatment.compare import compare_treatment
from pgproof.domain.identifiers import operation_id
from pgproof.domain.ir.workload import OperationIR, OperationPhase, WorkloadCoverage, WorkloadIR

_OP = operation_id("pytest", "tests/test_orders.py::test_totals", "call")


def _workload(
    *,
    query_counts: dict[str, int],
    selected_tests: int = 1,
    passed_tests: int = 1,
    failed_tests: int = 0,
    include_operation: bool = True,
    duration_us: int | None = None,
) -> WorkloadIR:
    operations = (
        (
            OperationIR(
                id=_OP,
                phase=OperationPhase.CALL,
                query_counts=query_counts,
                observed_duration_us=duration_us,
            ),
        )
        if include_operation
        else ()
    )
    return WorkloadIR(
        coverage=WorkloadCoverage.COMPLETE_FOR_SELECTION,
        boundary_note="capture completed for the selected test command",
        operations=operations,
        selected_tests=selected_tests,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
    )


def test_a_treatment_with_fewer_queries_and_passing_tests_is_verified() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "b" * 64: 5})
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "c" * 64: 1})
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.baseline_query_count == 6
    assert comparison.treatment_query_count == 2
    assert comparison.amplification_reduced is True
    assert comparison.results_equivalent is True
    assert comparison.verified is True
    assert comparison.unsupported_reason is None


def test_a_treatment_with_failing_tests_is_rejected_even_with_fewer_queries() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "b" * 64: 5})
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1}, passed_tests=0, failed_tests=1)
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.amplification_reduced is True
    assert comparison.results_equivalent is False
    assert comparison.verified is False


def test_a_treatment_with_the_same_or_more_queries_is_not_an_improvement() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "b" * 64: 5})
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "b" * 64: 5})
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.amplification_reduced is False
    assert comparison.verified is False


def test_a_baseline_with_its_own_failing_tests_cannot_claim_equivalence() -> None:
    baseline = _workload(
        query_counts={"sha256:" + "a" * 64: 1, "sha256:" + "b" * 64: 5},
        passed_tests=0,
        failed_tests=1,
    )
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1})
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.unsupported_reason == "baseline itself had failing tests; nothing to preserve"
    assert comparison.results_equivalent is False
    assert comparison.verified is False


def test_a_different_selected_test_count_is_unsupported() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 1}, selected_tests=4)
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1}, selected_tests=5)
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.unsupported_reason == "baseline and treatment selected a different test set"
    assert comparison.verified is False


def test_an_operation_absent_from_the_treatment_is_unsupported() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 1})
    treatment = _workload(query_counts={}, include_operation=False)
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.unsupported_reason == "operation absent from the treatment capture"
    assert comparison.amplification_reduced is None
    assert comparison.verified is False


def test_an_operation_absent_from_the_baseline_is_unsupported() -> None:
    baseline = _workload(query_counts={}, include_operation=False)
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1})
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.unsupported_reason == "operation absent from the baseline capture"
    assert comparison.verified is False


def test_duration_is_carried_through_when_present() -> None:
    baseline = _workload(query_counts={"sha256:" + "a" * 64: 6}, duration_us=5000)
    treatment = _workload(query_counts={"sha256:" + "a" * 64: 1}, duration_us=200)
    comparison = compare_treatment(baseline, treatment, operation_id=_OP)
    assert comparison.baseline_duration_us == 5000
    assert comparison.treatment_duration_us == 200
