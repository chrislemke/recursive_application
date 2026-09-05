"""The Gate: the deterministic quality check an Iteration must pass.

`evaluate` is a pure function over one Iteration's evidence, so the Kernel can gather the
inputs in the order the checks run and stop at the first failure, and so the whole rule is
table-testable. No clock, no filesystem, no model call.
"""

from collections.abc import Callable, Iterable, Mapping

from pydantic import Field

from recursive_application.kernel.evals import EvalDelta
from recursive_application.kernel.paths import is_protected, is_writable
from recursive_application.kernel.records import (
    CheckResult,
    Contract,
    GateCheck,
    GateResult,
    Mode,
    Review,
    SensorFinding,
)

CHECK_ORDER: tuple[str, ...] = (
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
)
"""Every check a Growth Iteration must pass, in the order the Kernel gathers the evidence."""

ANSWER_TASK_CHECKS: tuple[str, ...] = ("evals", "anomalies", "review")
"""The subset an Answer or Task Loop Iteration is judged by; there is no diff to check."""

EXCERPT_LIMIT = 500
"""How much of a failure's offending items or check output the Gate result keeps."""

_NOT_RUN = "not run"
"""The excerpt of one of the four checks whose `CheckResult` never reached the Gate."""

_NO_TARGETS = "no Target Cases"
"""The excerpt when the evals check fails because the Iteration had no Target Cases."""

_NO_DELTA = "no eval delta"
"""The excerpt of the eval check when the Iteration produced no comparison to judge."""

_NO_REVIEW = "no review"
"""The excerpt of the Review check when the Reviewer's verdict never reached the Gate."""


class GateInputs(Contract):
    """One Iteration's evidence: everything the Gate needs and nothing it has to go and fetch."""

    mode: Mode
    diff_paths: list[str] = Field(default_factory=list)
    changed_eval_cases: list[str] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    eval_delta: EvalDelta | None = None
    guard_retry_passed: list[str] = Field(default_factory=list)
    anomalies: list[SensorFinding] = Field(default_factory=list)
    review: Review | None = None


_Rule = Callable[[GateInputs], str | None]
"""A check's rule: the excerpt when the check fails, `None` when it passes."""


def _offenders(items: Iterable[str]) -> str | None:
    """The offending items joined into one excerpt, or `None` when there are none."""
    joined = ", ".join(items)
    return joined or None


def _protected_paths(inputs: GateInputs) -> str | None:
    """Fails when the diff touches a Protected Path."""
    return _offenders(path for path in inputs.diff_paths if is_protected(path))


def _write_scope(inputs: GateInputs) -> str | None:
    """Fails when the diff touches a path outside the write scope."""
    return _offenders(path for path in inputs.diff_paths if not is_writable(path))


def _eval_cases(inputs: GateInputs) -> str | None:
    """Fails when an existing eval case was changed or deleted; datasets are append-only."""
    return _offenders(inputs.changed_eval_cases)


def _command_check(name: str) -> _Rule:
    """The rule for one of the four commands that define clean: its own `CheckResult`."""

    def rule(inputs: GateInputs) -> str | None:
        result = next((entry for entry in inputs.checks if entry.name == name), None)
        if result is None:
            return _NOT_RUN
        return None if result.passed else result.output

    return rule


def _evals(inputs: GateInputs) -> str | None:
    """Fails when Target Cases did not improve or a Guard Case regressed past its one retry."""
    delta = inputs.eval_delta
    if delta is None:
        return _NO_DELTA
    regressions = [
        case for case in delta.guard_regressions if case not in inputs.guard_retry_passed
    ]
    if delta.target_improved and not regressions:
        return None
    offenders = regressions if delta.target_improved else [*delta.targets, *regressions]
    return ", ".join(offenders) or _NO_TARGETS


def _anomalies(inputs: GateInputs) -> str | None:
    """Fails when the Sensors found a new trace anomaly in the Iteration's spans."""
    return _offenders(finding.summary for finding in inputs.anomalies)


def _review(inputs: GateInputs) -> str | None:
    """Fails when the Reviewer rejected the diff or never reached the Gate."""
    review = inputs.review
    if review is None:
        return _NO_REVIEW
    return review.notes if review.verdict == "reject" else None


_RULES: Mapping[str, _Rule] = {
    "protected-paths": _protected_paths,
    "write-scope": _write_scope,
    "eval-cases": _eval_cases,
    "ruff-format": _command_check("ruff-format"),
    "ruff-check": _command_check("ruff-check"),
    "ty": _command_check("ty"),
    "pytest": _command_check("pytest"),
    "evals": _evals,
    "anomalies": _anomalies,
    "review": _review,
}


def evaluate(inputs: GateInputs) -> GateResult:
    """The Gate's verdict on one Iteration: the checks in order, the first failure stopping them."""
    checks: list[GateCheck] = []
    failed = False
    for name in CHECK_ORDER if inputs.mode is Mode.GROWTH else ANSWER_TASK_CHECKS:
        if failed or (name == "review" and inputs.mode is Mode.ANSWER):
            checks.append(GateCheck(name=name, status="skipped"))
            continue
        excerpt = _RULES[name](inputs)
        if excerpt is None:
            checks.append(GateCheck(name=name, status="passed"))
        else:
            checks.append(GateCheck(name=name, status="failed", excerpt=excerpt[:EXCERPT_LIMIT]))
            failed = True
    return GateResult(passed=not failed, checks=checks)
