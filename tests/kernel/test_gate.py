"""The Gate: the deterministic quality check an Iteration must pass.

`evaluate` is a pure function over one Iteration's evidence, so every case here is a table
row: the same clean Growth Iteration with one thing changed. Expected check names, statuses,
and excerpts are literals from the seams document, never recomputed the way the Gate
computes them. No clock, no filesystem, no model.
"""

from typing import Any

from recursive_application.kernel.evals import EvalDelta
from recursive_application.kernel.gate import GateInputs, evaluate
from recursive_application.kernel.records import (
    CheckResult,
    GateCheck,
    Mode,
    Review,
    SensorFinding,
)

ORGANISM_PATH = "src/recursive_application/organism/agents.py"

PASSING_CHECKS = [
    CheckResult(name="ruff-format", passed=True),
    CheckResult(name="ruff-check", passed=True),
    CheckResult(name="ty", passed=True),
    CheckResult(name="pytest", passed=True),
]

IMPROVED_DELTA = EvalDelta(
    targets=["triage/frontier-1"],
    targets_passed_before=0,
    targets_passed_after=1,
    newly_passing=["triage/frontier-1"],
)

ACCEPT_REVIEW = Review(
    matches_plan=True,
    gaming_suspected=False,
    notes="The diff does what the Plan says.",
    verdict="accept",
)


def growth_inputs(**changes: Any) -> GateInputs:
    """The clean Growth Iteration of the first test, with `changes` replacing single fields."""
    clean: dict[str, Any] = {
        "mode": Mode.GROWTH,
        "diff_paths": [ORGANISM_PATH],
        "checks": PASSING_CHECKS,
        "eval_delta": IMPROVED_DELTA,
        "review": ACCEPT_REVIEW,
    }
    return GateInputs(**(clean | changes))


def check(result_checks: list[GateCheck], name: str) -> GateCheck:
    """The one check called `name` in a Gate result."""
    return next(entry for entry in result_checks if entry.name == name)


def test_a_clean_growth_iteration_passes_with_every_check_of_the_rule_passed() -> None:
    result = evaluate(
        GateInputs(
            mode=Mode.GROWTH,
            diff_paths=[ORGANISM_PATH],
            checks=PASSING_CHECKS,
            eval_delta=IMPROVED_DELTA,
            review=ACCEPT_REVIEW,
        )
    )

    assert result.passed is True
    assert [entry.name for entry in result.checks] == [
        "protected-paths",
        "write-scope",
        "eval-cases",
        "ruff-format",
        "ruff-check",
        "ty",
        "pytest",
        "evals",
        "anomalies",
        "review",
    ]
    assert [entry.status for entry in result.checks] == ["passed"] * 10


def test_a_protected_path_in_the_diff_fails_first_and_leaves_every_later_check_skipped() -> None:
    result = evaluate(growth_inputs(diff_paths=["docs/coding-guide.md"]))

    assert result.passed is False
    assert result.failed_checks == ["protected-paths"]
    assert check(result.checks, "protected-paths").excerpt == "docs/coding-guide.md"
    assert [entry.status for entry in result.checks[1:]] == ["skipped"] * 9


def test_a_diff_path_outside_the_write_scope_fails_write_scope() -> None:
    result = evaluate(growth_inputs(diff_paths=[".ra/runs/x.json"]))

    assert result.passed is False
    assert result.failed_checks == ["write-scope"]
    assert check(result.checks, "write-scope").excerpt == ".ra/runs/x.json"
    assert check(result.checks, "protected-paths").status == "passed"


def test_a_changed_existing_eval_case_fails_eval_cases_and_skips_the_checks_after_it() -> None:
    result = evaluate(growth_inputs(changed_eval_cases=["triage-1"]))

    assert result.passed is False
    assert result.failed_checks == ["eval-cases"]
    assert check(result.checks, "eval-cases").excerpt == "triage-1"
    assert [entry.status for entry in result.checks[3:]] == ["skipped"] * 7


def test_a_failing_pytest_result_fails_pytest_with_its_output_cut_to_the_excerpt_limit() -> None:
    long_output = "pytest failed: " + "detail " * 1000

    result = evaluate(
        growth_inputs(
            checks=[
                CheckResult(name="ruff-format", passed=True),
                CheckResult(name="ruff-check", passed=True),
                CheckResult(name="ty", passed=True),
                CheckResult(name="pytest", passed=False, output=long_output),
            ]
        )
    )

    assert result.failed_checks == ["pytest"]
    excerpt = check(result.checks, "pytest").excerpt
    assert len(excerpt) == 500
    assert excerpt.startswith("pytest failed: detail detail")
    assert [entry.status for entry in result.checks[3:6]] == ["passed"] * 3
    assert [entry.status for entry in result.checks[7:]] == ["skipped"] * 3


def test_a_missing_check_result_fails_that_check_with_the_excerpt_not_run() -> None:
    result = evaluate(
        growth_inputs(
            checks=[
                CheckResult(name="ruff-format", passed=True),
                CheckResult(name="ruff-check", passed=True),
                CheckResult(name="pytest", passed=True),
            ]
        )
    )

    assert result.passed is False
    assert result.failed_checks == ["ty"]
    assert check(result.checks, "ty").excerpt == "not run"


def test_target_cases_that_did_not_improve_fail_evals_with_the_target_names() -> None:
    stalled = EvalDelta(
        targets=["triage/frontier-1", "answers/self-description"],
        targets_passed_before=1,
        targets_passed_after=1,
    )

    result = evaluate(growth_inputs(eval_delta=stalled))

    assert result.passed is False
    assert result.failed_checks == ["evals"]
    assert check(result.checks, "evals").excerpt == "triage/frontier-1, answers/self-description"
    assert [entry.status for entry in result.checks[8:]] == ["skipped"] * 2


def test_a_guard_case_regression_fails_evals_with_the_case_name() -> None:
    regressed = EvalDelta(
        targets=["triage/frontier-1"],
        targets_passed_before=0,
        targets_passed_after=1,
        newly_failing=["answers/b"],
        guard_regressions=["answers/b"],
    )

    result = evaluate(growth_inputs(eval_delta=regressed))

    assert result.passed is False
    assert result.failed_checks == ["evals"]
    assert check(result.checks, "evals").excerpt == "answers/b"


def test_a_guard_regression_whose_one_retry_passed_is_not_counted_and_evals_passes() -> None:
    regressed = EvalDelta(
        targets=["triage/frontier-1"],
        targets_passed_before=0,
        targets_passed_after=1,
        newly_failing=["answers/b"],
        guard_regressions=["answers/b"],
    )

    result = evaluate(growth_inputs(eval_delta=regressed, guard_retry_passed=["answers/b"]))

    assert result.passed is True
    assert check(result.checks, "evals").status == "passed"


def test_an_iteration_without_an_eval_delta_fails_evals() -> None:
    result = evaluate(growth_inputs(eval_delta=None))

    assert result.passed is False
    assert result.failed_checks == ["evals"]
    assert check(result.checks, "evals").excerpt == "no eval delta"


def test_one_trace_anomaly_fails_anomalies_with_the_finding_summary() -> None:
    anomaly = SensorFinding(
        id="traces:r1:error-span",
        source="traces",
        summary="An error span in the Implementer's run",
        severity="high",
    )

    result = evaluate(growth_inputs(anomalies=[anomaly]))

    assert result.passed is False
    assert result.failed_checks == ["anomalies"]
    assert check(result.checks, "anomalies").excerpt == "An error span in the Implementer's run"
    assert check(result.checks, "review").status == "skipped"


def test_a_reject_verdict_fails_review_with_the_reviewer_notes() -> None:
    rejection = Review(
        matches_plan=False,
        gaming_suspected=True,
        notes="The new test asserts a constant against itself.",
        verdict="reject",
    )

    result = evaluate(growth_inputs(review=rejection))

    assert result.passed is False
    assert result.failed_checks == ["review"]
    assert (
        check(result.checks, "review").excerpt == "The new test asserts a constant against itself."
    )


def test_a_growth_iteration_without_a_review_fails_review() -> None:
    result = evaluate(growth_inputs(review=None))

    assert result.passed is False
    assert result.failed_checks == ["review"]
    assert check(result.checks, "review").excerpt == "no review"


def test_an_answer_iteration_applies_only_three_checks_and_skips_the_reviewer() -> None:
    result = evaluate(GateInputs(mode=Mode.ANSWER, eval_delta=IMPROVED_DELTA))

    assert result.passed is True
    assert [entry.name for entry in result.checks] == ["evals", "anomalies", "review"]
    assert [entry.status for entry in result.checks] == ["passed", "passed", "skipped"]


def test_a_task_loop_iteration_still_requires_the_review() -> None:
    without_review = evaluate(GateInputs(mode=Mode.TASK, eval_delta=IMPROVED_DELTA))
    with_review = evaluate(
        GateInputs(mode=Mode.TASK, eval_delta=IMPROVED_DELTA, review=ACCEPT_REVIEW)
    )

    assert without_review.passed is False
    assert without_review.failed_checks == ["review"]
    assert check(without_review.checks, "review").excerpt == "no review"
    assert with_review.passed is True
    assert [entry.status for entry in with_review.checks] == ["passed"] * 3


def test_evaluating_the_same_iteration_twice_gives_equal_results() -> None:
    inputs = growth_inputs(
        diff_paths=["docs/coding-guide.md", ORGANISM_PATH],
        changed_eval_cases=["triage-1"],
        anomalies=[SensorFinding(id="traces:r1:error-span", source="traces", summary="An error")],
    )

    assert evaluate(inputs) == evaluate(inputs)
    assert evaluate(inputs).failed_checks == ["protected-paths"]


def test_every_failed_excerpt_is_cut_to_the_limit_however_many_offenders_there_are() -> None:
    many_protected = [f"docs/adr/{n:04d}-decision-number-{n}.md" for n in range(60)]
    result = evaluate(
        GateInputs(
            mode=Mode.GROWTH,
            diff_paths=many_protected,
            checks=PASSING_CHECKS,
            eval_delta=IMPROVED_DELTA,
            review=ACCEPT_REVIEW,
        )
    )
    protected = next(check for check in result.checks if check.name == "protected-paths")

    assert protected.status == "failed"
    assert len(protected.excerpt) == 500
    assert protected.excerpt.startswith("docs/adr/0000-decision-number-0.md")


def test_an_evals_failure_without_target_cases_says_so_instead_of_staying_silent() -> None:
    result = evaluate(GateInputs(mode=Mode.ANSWER, eval_delta=EvalDelta()))
    evals = next(check for check in result.checks if check.name == "evals")

    assert evals.status == "failed"
    assert evals.excerpt == "no Target Cases"
