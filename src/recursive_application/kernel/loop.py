"""The Loop runner: the Kernel's orchestration of the five phases (ADR 0006, ADR 0010).

One `run(mode, task, options)` call is one Loop run: Sense collects the findings, Decide picks
the Mode, Act produces a candidate, the Gate judges it, and Learn records what happened. The
runner is synchronous and owns no side effect of its own: agents go through the injected
`AgentRunner`, the four checks, the red check, the evals, the approval, the clock, and the
Trace Store through the injected `Runners`, and every Iteration is appended to the Run Record
as it ends, so a crash leaves the record behind.
"""

from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, NoReturn

import yaml
from pydantic import Field

from recursive_application.kernel.breaker import BreakerStore, CircuitOpenError
from recursive_application.kernel.bundle import LoopPosition, assemble_state_bundle, frontier_dir
from recursive_application.kernel.checks import RedResult
from recursive_application.kernel.evals import (
    EvalDelta,
    EvalReport,
    ReportStore,
    case_for,
    changed_eval_cases,
    compare,
    dataset_name,
    list_datasets,
)
from recursive_application.kernel.gate import GateInputs, evaluate
from recursive_application.kernel.git import Repo
from recursive_application.kernel.paths import EVALS_DIRNAME, RUNS_DIRNAME, TASKS_DIRNAME
from recursive_application.kernel.records import (
    CapabilityGap,
    CheckResult,
    CodeReport,
    Contract,
    EvalCase,
    GateResult,
    IterationRecord,
    Mode,
    Outcome,
    Plan,
    Review,
    RunRecord,
    RunStore,
    SensorFinding,
    TriageDecision,
    Usage,
    WorkerOutput,
)
from recursive_application.kernel.registry import (
    EVALS_DIRNAME_TRACKED,
    Phase,
    Registry,
    affected_agents,
)
from recursive_application.kernel.runtime import (
    FALLBACK_USD_PER_MILLION_TOKENS,
    AgentRunError,
    AgentRunner,
    AgentRunResult,
)
from recursive_application.kernel.sensors import (
    FINDINGS_FILENAME,
    FindingStore,
    collect,
    trace_findings,
)
from recursive_application.kernel.settings import Settings
from recursive_application.kernel.tracing import read_spans
from recursive_application.kernel.wiki_protocol import WikiMaintainer

ANSWER_RUBRIC = (
    "The answer addresses the request directly. Where it speaks about the system, it is "
    "grounded in the Capability Inventory and in the repository it was given, and it claims "
    "no capability whose dataset is not green. It states plainly what it could not do, and "
    "adds no claim it cannot support."
)
"""The generic Answer rubric: the Kernel's one Target Case for every Answer Mode run."""

LOCK_FILENAME = "lock"
"""The file under the runtime directory that keeps two Growth runs out of one checkout."""

CASES_FILENAME = "cases.yaml"
"""The Target Cases of one run, written under the run's task directory and never tracked."""

OUTPUT_FILENAME = "output.md"
"""The Answer or Task output of the latest Iteration, under the run's task directory."""

ANSWER_CASE_PREFIX = "answer-"
"""How the Kernel names the one Target Case it writes for an Answer Mode run."""

TASK_DATASET_PREFIX = "task-"
"""How the Kernel names the runtime dataset a Task Loop run's Target Cases are reported under."""

TASK_ACTOR = "worker"
"""The registry entry that fills the Act slot of a Task Iteration when the Plan names none."""

APPROVAL_REFUSED = "approval refused"
"""The stop reason when the human turned the Plan, or an escalation to Growth, down."""

UNKNOWN_ACTOR = "unknown actor"
"""The reason an Iteration is refused before Act when its Plan names no eligible Actor."""

NO_TARGET_CASES = "no Target Cases"
"""The reason an Iteration is refused before Act when its Plan proves nothing (ADR 0010)."""

RETRY_HEADING = "Previous attempt failed because:"
"""What a retrying Worker is told about the Iteration the judge turned down."""

BEST_EFFORT_FINDING_SUFFIX = "best-effort"
"""What the `reflection` finding of a best-effort Answer is called, after the run id."""

BEST_EFFORT_RULES: tuple[str, ...] = ("iteration limit", "no progress")
"""The stop rules that return the last output as best effort instead of aborting the run."""

DIRTY_TREE = "dirty working tree"
"""Why a Growth Loop refuses to start: a reset would destroy work the human has not committed."""

LOCK_HELD = "lock held"
"""Why a Growth Loop refuses to start: another run of this checkout is already changing it."""

GROWTH_ACTOR = "implementer"
"""The registry entry that fills the Act slot of a Growth Iteration when the Plan names none."""

PYTHON_SUFFIX = ".py"
"""What makes a target path code: only then do the Test Writer and the red check run (ADR 0008)."""

NO_RED = "no red"
"""The reason an Iteration is rejected: the tests the Test Writer wrote passed straight away."""

NO_DATASET = "no dataset"
"""The reason a frontier Plan is refused when no dataset under `evals/` holds its first case."""

DATASET_OUTSIDE_EVALS = "dataset outside evals/"
"""The reason a Plan is refused when the dataset it names is not a tracked eval file."""
"""The stop reason when a Plan appends nothing and no dataset under `evals/` holds its targets."""

COMMIT_MESSAGE_PREFIX = "ra: "
"""How every commit the Kernel writes begins, so an Improvement is one grep in the history."""

GUARD_DATASETS: tuple[str, ...] = ("triage", "answers")
"""The datasets every Growth Iteration guards, whatever else it changed."""

ORGANISM_TESTS_PREFIX = "tests/organism/"
"""Where the Test Writer may write, and so where the red check looks for the files it runs."""

_FIRST_COMMAND_CHECK = "ruff-format"
"""The first Gate check the Kernel has to run a subprocess for: the four checks' stage."""


class LoopOptions(Contract):
    """What the caller may set for one run; `None` means the Settings value."""

    yes: bool = False
    max_iterations: int | None = None
    budget_usd: Decimal | None = None
    max_minutes: int | None = None
    goal: str | None = None


class EvalRequest(Contract):
    """One request to the evals runner: which datasets to run, and the output to judge.

    `task_dataset` is a runtime `cases.yaml` and `dataset` the name its results are reported
    under, so the Loop's target keys and the runner's report agree by construction.
    """

    run_id: str
    datasets: list[str] = Field(default_factory=list)
    task_dataset: str | None = None
    dataset: str | None = None
    output: str | None = None
    targets: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Runners:
    """The adapters the CLI wires and a test replaces; every side effect of a run is one of them."""

    checks: Callable[[Path], list[CheckResult]]
    red_check: Callable[[Path, Sequence[str]], RedResult]
    evals: Callable[[EvalRequest], EvalReport]
    approve: Callable[[str], bool]
    clock: Callable[[], datetime]
    tracing: Callable[[str], Path]


@dataclass(frozen=True)
class LoopResult:
    """What one run produced: its record, its output, why it stopped, and the exit code."""

    record: RunRecord
    output: str | None = None
    reason: str | None = None
    questions: list[str] = field(default_factory=list)
    exit_code: int = 0


@dataclass(frozen=True)
class _TargetCases:
    """The Definition of Done as the Kernel wrote it: the dataset and its case keys.

    `cases_path` is the runtime `cases.yaml` of an Answer or Task run and `None` for a Growth
    Iteration, whose Target Cases live in the tracked dataset the Plan names.
    """

    cases_path: Path | None
    dataset: str
    targets: list[str]
    dataset_path: str = ""


@dataclass(frozen=True)
class _GrowthAct:
    """What one Growth Iteration's Act produced: the Test Writer's report and the Actor's."""

    test_report: CodeReport | None
    code_report: CodeReport


@dataclass(frozen=True)
class _Verdict:
    """The Gate's judgement of one Iteration and the evidence it was reached on."""

    gate: GateResult
    report: EvalReport | None = None
    delta: EvalDelta | None = None
    review: Review | None = None
    diff_paths: list[str] = field(default_factory=list)


@dataclass
class _RunState:
    """What one run carries from phase to phase while it is going on."""

    record: RunRecord
    trace_path: Path
    findings: list[SensorFinding]
    budget_usd: Decimal
    iteration_limit: int
    max_minutes: int
    skip_approval: bool = False
    pending_usage: Usage = field(default_factory=Usage)
    output: str | None = None
    previous_gate: Literal["passed", "failed"] | None = None
    judge_reason: str | None = None
    planner_reason: str | None = None
    plan: Plan | None = None
    output_path: Path | None = None
    questions: list[str] = field(default_factory=list)
    no_progress: int = 0
    gaps_recorded: int = 0


def estimated_cost(usage: Usage) -> Decimal:
    """What `usage` cost: the model's own price, or the token fallback when it reports none."""
    if usage.cost_usd > 0:
        return usage.cost_usd
    tokens = Decimal(usage.input_tokens + usage.output_tokens)
    return tokens / Decimal(1_000_000) * FALLBACK_USD_PER_MILLION_TOKENS


def _answer_case_name(run_id: str) -> str:
    """The name of the Target Case the Kernel writes for an Answer Mode run."""
    return f"{ANSWER_CASE_PREFIX}{run_id}"


def _worker_prompt(task: str, judge_reason: str | None) -> str:
    """The Task as the Worker sees it, carrying the judge's reason for the last attempt."""
    if judge_reason is None:
        return task
    return f"{task}\n\n{RETRY_HEADING} {judge_reason}"


def _dataset_of(path: str) -> str:
    """The dataset name of a repo-relative eval file: `evals/answers.yaml` is `answers`."""
    return dataset_name(Path(path), evals_dir=Path(EVALS_DIRNAME_TRACKED))


def _unique(names: Iterable[str]) -> list[str]:
    """The names in the order they were first named, without repeats."""
    return list(dict.fromkeys(names))


def _run_summary(
    plan: Plan, diff_paths: Sequence[str], gate: GateResult, *, run_id: str, sha: str, dataset: str
) -> str:
    """What the Librarian records: the Improvement, its breadcrumbs, its diff, and the verdict.

    The commit and the dataset are the two lines a capability page needs to be evidence (the
    Librarian's page convention), so the Kernel commits first and hands them over.
    """
    paths = "\n".join(f"- {path}" for path in diff_paths) or "(none)"
    checks = ", ".join(f"{check.name}: {check.status}" for check in gate.checks)
    return (
        f"Improvement: {plan.title}\n\n{plan.change}\n\n"
        f"Run: {run_id}\nCommit: {sha}\nDataset: {dataset}\n\n"
        f"Changed paths:\n{paths}\n\nGate: {checks}"
    )


def _judge_reason(report: EvalReport | None, targets: Sequence[str]) -> str | None:
    """Why the judge turned the Answer down, or `None` when it passed."""
    result = case_for(report, targets[0])
    if result is None or result.passed:
        return None
    return "; ".join(result.reasons) or "the judge gave no reason"


class _EscalatedError(Exception):
    """A Task Loop found a Capability Gap and, with the human's approval, becomes Growth."""


class _StopError(Exception):
    """A stop rule fired inside a phase; `reason` is what ends the run where it is caught."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _escalates(gap: CapabilityGap) -> bool:
    """Whether this gap turns the run into a Growth Loop, rather than waiting for the human."""
    return gap.kind != "clarification" and not gap.needs_human


def _gap_details(gap: CapabilityGap) -> str:
    """A gap as a `reflection` finding records it: its kind, its cure, and what it needs granted."""
    return "\n".join(
        [
            f"kind: {gap.kind}",
            f"how_to_acquire: {gap.how_to_acquire}",
            f"needs_human: {', '.join(gap.needs_human)}",
        ]
    )


def _indented_cases(specs: Sequence[dict[str, Any]]) -> str:
    """`specs` as the lines that follow `cases:` in a dataset file, in the seed files' style.

    PyYAML puts a nested sequence at its parent's indentation; the seed files indent it one
    level deeper, so every line under a key gains two more spaces than the dump gives it.
    """
    lines = []
    for spec in specs:
        dumped = yaml.safe_dump([spec], sort_keys=False, default_flow_style=False)
        for line in dumped.splitlines():
            stripped = line.lstrip(" ")
            depth = (len(line) - len(stripped)) // 2
            extra = 2 if stripped.startswith("- ") and depth > 0 else 0
            lines.append(f"  {' ' * (depth * 2 + extra)}{stripped}")
    return "".join(f"{line}\n" for line in lines)


def _plan_yaml(plan: Plan) -> str:
    """The Plan as an agent and the human read it: YAML, in the contract's own field order."""
    return yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False)


def _case_spec(case: EvalCase) -> dict[str, Any]:
    """One Target Case as pydantic-evals reads it: its texts, its expected output, its rubric."""
    spec: dict[str, Any] = {"name": case.name, "inputs": case.inputs}
    evaluators: list[Any] = [{"Contains": text} for text in case.must_contain]
    if case.expected_output is not None:
        spec["expected_output"] = case.expected_output
        evaluators.append("EqualsExpected")
    if case.rubric is not None:
        evaluators.append({"LLMJudge": {"rubric": case.rubric, "include_input": True}})
    spec["evaluators"] = evaluators
    return spec


def _planner_prompt(task: str, findings: Sequence[SensorFinding], reason: str | None) -> str:
    """The Task as the Planner sees it: the request, the findings, and the last failure."""
    prompt = f"Task: {task}\n\nOpen Sensor Findings:\n{_findings_block(findings)}"
    if reason is None:
        return prompt
    return f"{prompt}\n\n{RETRY_HEADING} {reason}"


def _actor_prompt(task: str, plan: Plan, reason: str | None) -> str:
    """The Task as the Actor sees it: the request, its Definition of Done, and the last failure."""
    prompt = f"Task: {task}\n\nPlan:\n{_plan_yaml(plan)}"
    if reason is None:
        return prompt
    return f"{prompt}\n{RETRY_HEADING} {reason}"


def _review_prompt(plan: Plan, output: str) -> str:
    """What the Reviewer judges: the Plan the Iteration followed and the output it produced."""
    return f"Plan:\n{_plan_yaml(plan)}\n\nOutput:\n{output}"


def _findings_block(findings: Sequence[SensorFinding]) -> str:
    """The open Sensor Findings as an agent reads them in a prompt."""
    lines = [f"- [{finding.severity}] {finding.id}: {finding.summary}" for finding in findings]
    return "\n".join(lines) or "(none)"


class LoopRunner:
    """Runs one Loop: the Kernel's own code, holding every agent to the Gate."""

    def __init__(
        self,
        *,
        settings: Settings,
        registry: Registry,
        agents: AgentRunner,
        repo: Repo,
        wiki: WikiMaintainer,
        root: Path,
        ra_dir: Path,
        runners: Runners,
        breakers: BreakerStore,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._agents = agents
        self._repo = repo
        self._wiki = wiki
        self._root = root
        self._ra_dir = ra_dir
        self._runners = runners
        self._breakers = breakers
        self._runs = RunStore(ra_dir / RUNS_DIRNAME)

    def run(self, mode: Mode | None, task: str | None, options: LoopOptions) -> LoopResult:
        """Run one Loop for `task` and return its record, its output, and its exit code."""
        record = RunRecord(mode=mode or Mode.ANSWER, task=task, started_at=self._runners.clock())
        state = _RunState(
            record=record,
            trace_path=self._runners.tracing(record.run_id),
            findings=[],
            budget_usd=options.budget_usd or self._settings.ra_budget_usd,
            iteration_limit=options.max_iterations or self._settings.ra_max_iterations,
            max_minutes=options.max_minutes or self._settings.ra_max_minutes,
            skip_approval=options.yes,
        )
        try:
            state.findings = self._sense(state.budget_usd)
            if mode is None:
                decision = self._triage(state)
                record.mode = decision.mode
                if any(gap.kind == "clarification" for gap in decision.reflection.gaps):
                    return self._clarification(state, decision)
                for gap in decision.reflection.gaps:
                    if gap.needs_human:
                        self._record_gap(state, gap)
            if record.mode is Mode.ANSWER:
                return self._answer(state)
            if record.mode is Mode.TASK:
                return self._task(state)
            return self._growth(state)
        except _StopError as stop:
            if stop.reason == "clarification":
                self._finish(state.record, "aborted")
                return LoopResult(
                    record=state.record, reason=stop.reason, questions=state.questions, exit_code=2
                )
            return self._stopped(state, stop.reason)
        except Exception as error:
            return self._errored(state, error)

    def _clarification(self, state: _RunState, decision: TriageDecision) -> LoopResult:
        """Decide: Triage cannot place the Task without the human, so nothing else runs."""
        self._runs.append_iteration(
            state.record,
            IterationRecord(
                number=1,
                started_at=state.record.started_at,
                finished_at=self._runners.clock(),
                outcome="aborted",
                usage=state.pending_usage,
            ),
        )
        self._finish(state.record, "aborted")
        return LoopResult(
            record=state.record,
            reason="clarification",
            questions=list(decision.clarifying_questions),
            exit_code=2,
        )

    def _errored(self, state: _RunState, error: Exception) -> LoopResult:
        """Learn: nobody planned for this, so the record says so and the run reports it."""
        self._finish(state.record, "error")
        return LoopResult(record=state.record, output=state.output, reason=str(error), exit_code=3)

    def _sense(self, budget_usd: Decimal) -> list[SensorFinding]:
        """Sense: every open Sensor Finding of this runtime directory and this Wiki."""
        return collect(
            ra_dir=self._ra_dir,
            wiki=self._wiki,
            frontier_dir=frontier_dir(self._root),
            budget_usd=budget_usd,
        )

    def _triage(self, state: _RunState) -> TriageDecision:
        """Decide: Triage reflects on the Task and the findings and picks the Mode."""
        prompt = (
            f"Task: {state.record.task}\n\nOpen Sensor Findings:\n{_findings_block(state.findings)}"
        )
        result = self._call(state, "triage", prompt, iteration=1, phase="decide")
        state.pending_usage = state.pending_usage + result.usage
        decision: TriageDecision = result.output
        return decision

    def _answer(self, state: _RunState) -> LoopResult:
        """Answer Mode: no Planner; the Worker answers and the judge is the Gate."""
        case_name = _answer_case_name(state.record.run_id)
        cases = _TargetCases(
            cases_path=self._write_answer_cases(state.record.run_id, state.record.task or ""),
            dataset=case_name,
            targets=[f"{case_name}/{case_name}"],
        )
        number = 1
        while (rule := self._stop_rule(state, number)) is None:
            if self._iteration(state, number, self._answer_act_of(state, cases)):
                self._finish(state.record, "accepted")
                return LoopResult(record=state.record, output=state.output, exit_code=0)
            number += 1
        return self._stopped(state, rule)

    def _growth(self, state: _RunState, first: int = 1) -> LoopResult:
        """Growth Loop: the Organism changes itself, on a clean tree and under the lock."""
        if not self._repo.is_clean():
            raise _StopError(DIRTY_TREE)
        with self._lock(state.record.run_id):
            number = first
            while (rule := self._stop_rule(state, number)) is None:
                if self._iteration(state, number, self._growth_act_of(state)):
                    self._finish(state.record, "accepted")
                    return LoopResult(record=state.record, output=state.output, exit_code=0)
                number += 1
            return self._stopped(state, rule)

    @contextmanager
    def _lock(self, run_id: str) -> Iterator[None]:
        """Hold the Growth lock: one Growth Loop per checkout, released however the run ends."""
        path = self._ra_dir / LOCK_FILENAME
        if path.exists():
            raise _StopError(LOCK_HELD)
        path.write_text(run_id, encoding="utf-8")
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    def _growth_act_of(self, state: _RunState) -> Callable[[int, datetime], bool]:
        """The Growth Iteration's Act as `_iteration` drives it, bound to this run's state."""
        return lambda number, started_at: self._growth_act(state, number, started_at)

    def _growth_act(self, state: _RunState, number: int, started_at: datetime) -> bool:
        """Decide, Act, and Gate of one Growth Iteration: the Plan, the coders, the judgement."""
        plan = self._plan(state, number)
        state.plan = plan
        actor = plan.actor or GROWTH_ACTOR
        refusal = self._refusal_before_act(plan, actor, GROWTH_ACTOR) or self._dataset_refusal(plan)
        if refusal is not None:
            self._reject_before_act(state, number, started_at, plan, refusal)
            return False
        self._record_growth_gaps(state, plan.gaps)
        cases = self._growth_cases(plan)
        self._append_target_cases(plan)
        try:
            self._approve(state, _plan_yaml(plan))
        except _StopError:
            # The Kernel's own append must not survive a refusal: the tree goes back to HEAD.
            self._repo.reset_hard_clean()
            raise
        test_report: CodeReport | None = None
        if any(path.endswith(PYTHON_SUFFIX) for path in plan.target_paths):
            test_report = self._write_tests(state, number, plan)
            red = self._runners.red_check(self._root, self._changed_tests())
            if not red.red:
                reason = f"{NO_RED}: {red.output}"
                self._reject_before_act(state, number, started_at, plan, reason, test_report)
                return False
        code_report = self._act(state, number, plan, actor)
        return self._gate_iteration(
            state,
            number,
            started_at,
            cases,
            plan,
            growth=_GrowthAct(test_report=test_report, code_report=code_report),
        )

    def _write_tests(self, state: _RunState, number: int, plan: Plan) -> CodeReport:
        """Act: the Test Writer turns the Plan's `tests` into tests that fail (ADR 0008)."""
        result = self._call(
            state,
            "test_writer",
            _actor_prompt(state.record.task or "", plan, None),
            iteration=number,
            phase="act",
        )
        state.pending_usage = state.pending_usage + result.usage
        report: CodeReport = result.output
        return report

    def _act(self, state: _RunState, number: int, plan: Plan, actor: str) -> CodeReport:
        """Act: the Implementer, or the Specialist the Plan names, makes those tests pass."""
        result = self._call(
            state,
            actor,
            _actor_prompt(state.record.task or "", plan, state.judge_reason),
            iteration=number,
            phase="act",
        )
        state.pending_usage = state.pending_usage + result.usage
        report: CodeReport = result.output
        return report

    def _changed_tests(self) -> list[str]:
        """The Organism test files this Iteration changed: what the red check runs."""
        return [
            path for path in self._repo.changed_paths() if path.startswith(ORGANISM_TESTS_PREFIX)
        ]

    def _dataset_refusal(self, plan: Plan) -> str | None:
        """Why the Plan's dataset cannot be used: outside `evals/`, or no file holds its cases."""
        if plan.dataset is not None:
            if (
                not plan.dataset.startswith(f"{EVALS_DIRNAME_TRACKED}/")
                or not (self._root / plan.dataset).is_file()
            ):
                return f"{DATASET_OUTSIDE_EVALS}: {plan.dataset}"
            return None
        try:
            self._dataset_holding(plan.target_cases[0].name)
        except _StopError as stop:
            return stop.reason
        return None

    def _record_growth_gaps(self, state: _RunState, gaps: Sequence[CapabilityGap]) -> None:
        """A Growth Planner's gaps: escalation is where the run already is, so what the human
        must grant is recorded and a clarification ends the run, as everywhere else."""
        questions = [gap.description for gap in gaps if gap.kind == "clarification"]
        if questions:
            state.questions = questions
            raise _StopError("clarification")
        for gap in gaps:
            if gap.needs_human:
                self._record_gap(state, gap)

    def _growth_cases(self, plan: Plan) -> _TargetCases:
        """The Definition of Done: the dataset the Target Cases live in and their keys under it."""
        dataset = (
            _dataset_of(plan.dataset)
            if plan.dataset is not None
            else self._dataset_holding(plan.target_cases[0].name)
        )
        return _TargetCases(
            cases_path=None,
            dataset=dataset,
            targets=[f"{dataset}/{case.name}" for case in plan.target_cases],
            dataset_path=plan.dataset or f"{EVALS_DIRNAME_TRACKED}/{dataset}.yaml",
        )

    def _dataset_holding(self, case_name: str) -> str:
        """The dataset an existing Target Case lives in, for a Plan that appends nothing."""
        evals_dir = self._root / EVALS_DIRNAME_TRACKED
        for path in list_datasets(evals_dir):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            if any(case.get("name") == case_name for case in document.get("cases", [])):
                return dataset_name(path, evals_dir=evals_dir)
        raise _StopError(f"{NO_DATASET}: {case_name}")

    def _append_target_cases(self, plan: Plan) -> None:
        """Add the Plan's new Target Cases to the dataset it names; datasets are append-only.

        A Target Case whose name is already in the file is one the Plan means to turn green,
        and a Plan with no dataset targets Frontier Cases that exist: neither is written.
        """
        if plan.dataset is None:
            return
        path = self._root / plan.dataset
        text = path.read_text(encoding="utf-8")
        known = {case.get("name") for case in yaml.safe_load(text).get("cases", [])}
        appended = [_case_spec(case) for case in plan.target_cases if case.name not in known]
        if not appended:
            return
        # Appended as text after the last line, so every existing byte of the file, its comment
        # header and block scalars included, stays exactly as the human wrote it.
        indented = _indented_cases(appended)
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + indented, encoding="utf-8")

    def _task(self, state: _RunState) -> LoopResult:
        """Task Loop: the Planner states the Definition of Done and the Actor works against it;
        a Capability Gap the human approves turns the rest of the run into a Growth Loop."""
        number = 1
        try:
            while (rule := self._stop_rule(state, number)) is None:
                if self._iteration(state, number, self._task_act_of(state)):
                    self._finish(state.record, "accepted")
                    return LoopResult(record=state.record, output=state.output, exit_code=0)
                number += 1
        except _EscalatedError:
            state.judge_reason = None
            return self._growth(state, first=len(state.record.iterations) + 1)
        return self._stopped(state, rule)

    def _iteration(
        self, state: _RunState, number: int, act: Callable[[int, datetime], bool]
    ) -> bool:
        """One Iteration, recorded however it ends: a stop rule or a crash still leaves it in
        the Run Record with the Plan it had and the usage it spent."""
        started_at = self._runners.clock()
        state.plan = None
        try:
            return act(number, started_at)
        except _StopError as stop:
            self._append_unfinished(state, number, started_at, "aborted", stop.reason)
            raise
        except _EscalatedError:
            self._append_unfinished(state, number, started_at, "rejected", "escalated to growth")
            raise
        except Exception as error:
            self._append_unfinished(state, number, started_at, "error", str(error))
            raise

    def _task_act_of(self, state: _RunState) -> Callable[[int, datetime], bool]:
        """The Task Iteration's Act as `_iteration` drives it, bound to this run's state."""
        return lambda number, started_at: self._task_act(state, number, started_at)

    def _answer_act_of(
        self, state: _RunState, cases: _TargetCases
    ) -> Callable[[int, datetime], bool]:
        """The Answer Iteration's Act as `_iteration` drives it, bound to this run's cases."""
        return lambda number, started_at: self._answer_act(state, number, cases, started_at)

    def _task_act(self, state: _RunState, number: int, started_at: datetime) -> bool:
        """Decide, Act, and Gate of one Task Iteration: the Plan, the Actor, and the judgement."""
        plan = self._plan(state, number)
        state.plan = plan
        self._handle_gaps(state, plan.gaps)
        actor = plan.actor or TASK_ACTOR
        refusal = self._refusal_before_act(plan, actor, TASK_ACTOR)
        if refusal is not None:
            self._reject_before_act(state, number, started_at, plan, refusal)
            return False
        cases = self._write_task_cases(state, plan)
        self._approve(state, _plan_yaml(plan))
        result = self._call(
            state,
            actor,
            _actor_prompt(state.record.task or "", plan, state.judge_reason),
            iteration=number,
            phase="act",
        )
        state.pending_usage = state.pending_usage + result.usage
        output: WorkerOutput = result.output
        state.output = output.content
        state.output_path = self._write_output(state.record.run_id, output.content)
        self._handle_gaps(state, output.gaps)
        return self._gate_iteration(state, number, started_at, cases, plan, content=output.content)

    def _refusal_before_act(self, plan: Plan, actor: str, default_actor: str) -> str | None:
        """Why the Kernel refuses this Plan before anything acts on it, or `None`."""
        if not plan.target_cases:
            return NO_TARGET_CASES
        if not self._eligible(actor, default_actor):
            return f"{UNKNOWN_ACTOR}: {actor}"
        return None

    def _gate_iteration(
        self,
        state: _RunState,
        number: int,
        started_at: datetime,
        cases: _TargetCases,
        plan: Plan | None,
        *,
        content: str | None = None,
        growth: _GrowthAct | None = None,
    ) -> bool:
        """Gate of one Iteration, and Learn when the Gate passes.

        The Iteration is recorded before the Gate so the cost anomaly rule sees its spend, then
        updated with the verdict; every gatherer runs its evidence in `CHECK_ORDER`'s order and
        stops at the first failure, so a model call is the last thing an Iteration spends.
        """
        iteration = IterationRecord(
            number=number,
            started_at=started_at,
            finished_at=self._runners.clock(),
            plan=plan,
            test_report=growth.test_report if growth is not None else None,
            code_report=growth.code_report if growth is not None else None,
            output_path=self._repo_relative(state.output_path) if state.output_path else None,
            outcome="rejected",
            usage=state.pending_usage,
        )
        self._runs.append_iteration(state.record, iteration)
        verdict = (
            self._growth_gate(state, number, cases, plan)
            if growth is not None and plan is not None
            else self._output_gate(state, number, cases, content or "", plan)
        )
        commit_sha: str | None = None
        if verdict.gate.passed and growth is not None and plan is not None:
            commit_sha = self._learn(state, number, plan, verdict, cases)
        state.record.iterations[-1] = iteration.model_copy(
            update={
                "gate": verdict.gate,
                "review": verdict.review,
                "commit_sha": commit_sha,
                "outcome": "accepted" if verdict.gate.passed else "rejected",
                "finished_at": self._runners.clock(),
                "usage": state.pending_usage,
            }
        )
        self._runs.save(state.record)
        state.pending_usage = Usage()
        passing = verdict.delta.newly_passing if verdict.delta is not None else []
        progress = [case for case in passing if case in cases.targets]
        state.no_progress = 0 if progress else state.no_progress + 1
        state.judge_reason = _judge_reason(verdict.report, cases.targets)
        state.previous_gate = "passed" if verdict.gate.passed else "failed"
        return verdict.gate.passed

    def _output_gate(
        self, state: _RunState, number: int, cases: _TargetCases, content: str, plan: Plan | None
    ) -> _Verdict:
        """Gate of an Answer or Task Iteration: the judge on the output, then the Reviewer.

        The Reviewer is the one check that costs a model call, so it runs only once the Target
        Cases and the trace anomalies have passed, and what it costs lands in this Iteration.
        """
        report = self._runners.evals(
            EvalRequest(
                run_id=state.record.run_id,
                task_dataset=str(cases.cases_path),
                dataset=cases.dataset,
                output=content,
                targets=cases.targets,
            )
        )
        delta = compare(self._latest_report(), report, cases.targets)
        inputs = GateInputs(
            mode=state.record.mode, eval_delta=delta, anomalies=self._anomalies(state)
        )
        gate = evaluate(inputs)
        review: Review | None = None
        if plan is not None and gate.failed_checks == ["review"]:
            review = self._review(state, number, plan, content)
            gate = evaluate(inputs.model_copy(update={"review": review}))
        return _Verdict(gate=gate, report=report, delta=delta, review=review)

    def _growth_gate(
        self, state: _RunState, number: int, cases: _TargetCases, plan: Plan
    ) -> _Verdict:
        """Gate of a Growth Iteration: the diff, the four checks, the Guard subset, the Reviewer.

        Each stage is gathered only when everything cheaper has passed, so a Protected Path in
        the diff costs no subprocess, and a failing check costs no eval run and no model call.
        """
        diff_paths = self._repo.changed_paths()
        inputs = GateInputs(
            mode=Mode.GROWTH,
            diff_paths=diff_paths,
            changed_eval_cases=self._changed_eval_cases(diff_paths),
        )
        if evaluate(inputs).failed_checks == [_FIRST_COMMAND_CHECK]:
            inputs = inputs.model_copy(update={"checks": self._runners.checks(self._root)})
        report: EvalReport | None = None
        delta: EvalDelta | None = None
        if evaluate(inputs).failed_checks == ["evals"]:
            report, delta, retried = self._growth_evals(state, cases, diff_paths)
            inputs = inputs.model_copy(
                update={
                    "eval_delta": delta,
                    "guard_retry_passed": retried,
                    "anomalies": self._anomalies(state),
                }
            )
        review: Review | None = None
        if evaluate(inputs).failed_checks == ["review"]:
            review = self._review(state, number, plan, self._repo.diff_text())
            inputs = inputs.model_copy(update={"review": review})
        return _Verdict(
            gate=evaluate(inputs),
            report=report,
            delta=delta,
            review=review,
            diff_paths=diff_paths,
        )

    def _changed_eval_cases(self, diff_paths: Sequence[str]) -> list[str]:
        """The eval cases this Iteration changed or deleted; appending is the only edit allowed."""
        prefix = f"{EVALS_DIRNAME_TRACKED}/"
        changed: list[str] = []
        for path in diff_paths:
            if not path.startswith(prefix):
                continue
            working = self._root / path
            after = working.read_text(encoding="utf-8") if working.exists() else None
            changed.extend(changed_eval_cases(self._repo.file_at("HEAD", path), after))
        return changed

    def _growth_evals(
        self, state: _RunState, cases: _TargetCases, diff_paths: Sequence[str]
    ) -> tuple[EvalReport, EvalDelta, list[str]]:
        """The Guard subset of one Iteration, with one retry for each Guard Case that regressed."""
        run_id = state.record.run_id
        datasets = _unique([cases.dataset, *GUARD_DATASETS, *self._affected_datasets(diff_paths)])
        report = self._runners.evals(
            EvalRequest(run_id=run_id, datasets=datasets, targets=cases.targets)
        )
        delta = compare(self._latest_report(), report, cases.targets)
        if not delta.guard_regressions:
            return report, delta, []
        retry = self._runners.evals(
            EvalRequest(
                run_id=run_id,
                datasets=_unique(key.rpartition("/")[0] for key in delta.guard_regressions),
                targets=list(delta.guard_regressions),
            )
        )
        retried = [
            key
            for key in delta.guard_regressions
            if (result := case_for(retry, key)) is not None and result.passed
        ]
        return report, delta, retried

    def _affected_datasets(self, diff_paths: Sequence[str]) -> list[str]:
        """The datasets of the agents this diff touches: the rest of the Guard subset."""
        return [
            _dataset_of(self._registry.get(name).dataset)
            for name in affected_agents(self._registry, diff_paths)
        ]

    def _learn(
        self, state: _RunState, number: int, plan: Plan, verdict: _Verdict, cases: _TargetCases
    ) -> str:
        """Learn: the Kernel commits the gated diff, then the Librarian records it with the
        commit and the dataset as its breadcrumbs, and the Wiki's own changes are committed
        after it, so nothing unchecked rides into the Improvement's commit."""
        sha = self._repo.commit_all(f"{COMMIT_MESSAGE_PREFIX}{plan.title}")
        result = self._call(
            state,
            "librarian",
            _run_summary(
                plan,
                verdict.diff_paths,
                verdict.gate,
                run_id=state.record.run_id,
                sha=sha,
                dataset=cases.dataset_path,
            ),
            iteration=number,
            phase="learn",
        )
        state.pending_usage = state.pending_usage + result.usage
        self._wiki.rebuild_index()
        self._wiki.append_log(f"Run {state.record.run_id}: accepted {plan.title}")
        if not self._repo.is_clean():
            self._repo.commit_all(f"{COMMIT_MESSAGE_PREFIX}record {plan.title}")
        return sha

    def _plan(self, state: _RunState, number: int) -> Plan:
        """Decide: the Planner turns the Task and the findings into a Definition of Done."""
        result = self._call(
            state,
            "planner",
            _planner_prompt(
                state.record.task or "",
                state.findings,
                state.planner_reason or state.judge_reason,
            ),
            iteration=number,
            phase="decide",
        )
        state.pending_usage = state.pending_usage + result.usage
        state.planner_reason = None
        plan: Plan = result.output
        return plan

    def _review(self, state: _RunState, number: int, plan: Plan, content: str) -> Review:
        """Gate: the Reviewer judges the output against the Plan it was meant to follow."""
        result = self._call(
            state,
            "reviewer",
            _review_prompt(plan, content),
            iteration=number,
            phase="gate",
        )
        state.pending_usage = state.pending_usage + result.usage
        review: Review = result.output
        return review

    def _write_task_cases(self, state: _RunState, plan: Plan) -> _TargetCases:
        """Write the Plan's Target Cases as runtime data for this run, never into `evals/`."""
        run_id = state.record.run_id
        dataset = f"{TASK_DATASET_PREFIX}{run_id}"
        path = self._task_dir(run_id) / CASES_FILENAME
        specs = [_case_spec(case) for case in plan.target_cases]
        path.write_text(yaml.safe_dump({"cases": specs}, sort_keys=False), encoding="utf-8")
        return _TargetCases(
            cases_path=path,
            dataset=dataset,
            targets=[f"{dataset}/{case.name}" for case in plan.target_cases],
        )

    def _eligible(self, actor: str, default_actor: str) -> bool:
        """Whether `actor` may fill this Mode's Act slot: the Mode's own agent, or a Specialist."""
        return actor == default_actor or actor in {
            entry.name for entry in self._registry.specialists
        }

    def _reject_before_act(
        self,
        state: _RunState,
        number: int,
        started_at: datetime,
        plan: Plan,
        reason: str,
        test_report: CodeReport | None = None,
    ) -> None:
        """An Iteration the Kernel refuses before Act: no Gate, no progress, the Planner told.

        The reason goes on the record and to the next Planner; the Actor never sees it, since
        it is not a judgement of any output.
        """
        self._runs.append_iteration(
            state.record,
            IterationRecord(
                number=number,
                started_at=started_at,
                finished_at=self._runners.clock(),
                plan=plan,
                test_report=test_report,
                outcome="rejected",
                reason=reason,
                usage=state.pending_usage,
            ),
        )
        state.pending_usage = Usage()
        state.no_progress += 1
        state.planner_reason = reason

    def _approve(self, state: _RunState, text: str) -> None:
        """Show the human what the run is about to do; a refusal ends the run where it stands."""
        if state.skip_approval:
            return
        if not self._runners.approve(text):
            raise _StopError(APPROVAL_REFUSED)

    def _handle_gaps(self, state: _RunState, gaps: Sequence[CapabilityGap]) -> None:
        """A Capability Gap escalates to Growth; one the human must grant is recorded instead;
        a clarification gap ends the run with its question, as Triage's does."""
        questions = [gap.description for gap in gaps if gap.kind == "clarification"]
        if questions:
            state.questions = questions
            raise _StopError("clarification")
        for gap in gaps:
            if not _escalates(gap):
                self._record_gap(state, gap)
        escalating = [gap for gap in gaps if _escalates(gap)]
        if escalating:
            self._escalate(state, escalating)

    def _record_gap(self, state: _RunState, gap: CapabilityGap) -> None:
        """Learn: a gap nobody acted on becomes a `reflection` finding for the next run."""
        state.gaps_recorded += 1
        FindingStore(self._ra_dir / FINDINGS_FILENAME).append(
            SensorFinding(
                id=f"reflection:{state.record.run_id}:{state.gaps_recorded}",
                source="reflection",
                summary=gap.description,
                details=_gap_details(gap),
                severity="medium",
            ),
            self._runners.clock(),
        )

    def _escalate(self, state: _RunState, gaps: Sequence[CapabilityGap]) -> NoReturn:
        """The Task needs a capability the Organism lacks, so the run becomes a Growth Loop."""
        state.record.mode = Mode.GROWTH
        self._approve(
            state,
            yaml.safe_dump(
                {
                    "mode": Mode.GROWTH.value,
                    "gaps": [gap.model_dump(mode="json") for gap in gaps],
                },
                sort_keys=False,
            ),
        )
        raise _EscalatedError()

    def _stop_rule(self, state: _RunState, number: int) -> str | None:
        """The rule that ends the run before Iteration `number`, or `None` to go on."""
        if number > state.iteration_limit:
            return "iteration limit"
        elapsed = self._runners.clock() - state.record.started_at
        if elapsed.total_seconds() > state.max_minutes * 60:
            return "wall time"
        if estimated_cost(state.record.total_usage) >= state.budget_usd:
            return "budget"
        if state.no_progress >= self._settings.ra_no_progress_iterations:
            return "no progress"
        return None

    def _stopped(self, state: _RunState, rule: str) -> LoopResult:
        """The run hit a stop rule: best effort when there is an Answer, aborted otherwise.

        Only an Answer comes back as best effort: a Task Loop's output is judged against the
        Target Cases the human approved, so an output that never passed them is not a result.
        """
        answered = state.record.mode is Mode.ANSWER and state.output is not None
        if rule in BEST_EFFORT_RULES and answered:
            return self._best_effort(state, rule)
        self._finish(state.record, "aborted")
        return LoopResult(record=state.record, output=state.output, reason=rule, exit_code=2)

    def _best_effort(self, state: _RunState, rule: str) -> LoopResult:
        """Learn: the run ran out of Iterations, so its last output comes back with a warning.

        The Answer is returned because it is the best the run produced, and the failure is
        written to the `FindingStore` so the next `ra improve` can see that the judge never
        passed it.
        """
        reason = f"best effort: stopped by the {rule}; the judge never passed the Answer"
        run_id = state.record.run_id
        FindingStore(self._ra_dir / FINDINGS_FILENAME).append(
            SensorFinding(
                id=f"reflection:{run_id}:{BEST_EFFORT_FINDING_SUFFIX}",
                source="reflection",
                summary=f"Run {run_id} returned its Answer as best effort",
                details=reason,
                severity="medium",
            ),
            self._runners.clock(),
        )
        self._finish(state.record, "rejected")
        return LoopResult(record=state.record, output=state.output, reason=reason, exit_code=1)

    def _append_unfinished(
        self,
        state: _RunState,
        number: int,
        started_at: datetime,
        outcome: Outcome,
        reason: str | None,
    ) -> None:
        """Record an Iteration that never reached the Gate: its Plan, its draft, its spend."""
        self._runs.append_iteration(
            state.record,
            IterationRecord(
                number=number,
                started_at=started_at,
                finished_at=self._runners.clock(),
                plan=state.plan,
                output_path=self._repo_relative(state.output_path) if state.output_path else None,
                outcome=outcome,
                reason=reason,
                usage=state.pending_usage,
            ),
        )
        state.pending_usage = Usage()

    def _answer_act(
        self, state: _RunState, number: int, cases: _TargetCases, started_at: datetime
    ) -> bool:
        """Act and Gate of one Answer Iteration: the Worker's output against the judge."""
        result = self._call(
            state,
            "worker",
            _worker_prompt(state.record.task or "", state.judge_reason),
            iteration=number,
            phase="act",
        )
        state.pending_usage = state.pending_usage + result.usage
        output: WorkerOutput = result.output
        state.output = output.content
        state.output_path = self._write_output(state.record.run_id, output.content)
        return self._gate_iteration(state, number, started_at, cases, None, content=output.content)

    def _call(
        self,
        state: _RunState,
        role: str,
        prompt: str,
        *,
        iteration: int,
        phase: Phase,
    ) -> AgentRunResult:
        """Run one agent at its place in the Loop, with the State Bundle that says where it is."""
        position = LoopPosition(
            run_id=state.record.run_id,
            mode=state.record.mode,
            iteration=iteration,
            iteration_limit=state.iteration_limit,
            phase=phase,
            role=role,
            previous_gate=state.previous_gate,
        )
        bundle = assemble_state_bundle(
            position,
            root=self._root,
            ra_dir=self._ra_dir,
            registry=self._registry,
            wiki=self._wiki,
            budget_usd=state.budget_usd,
        )
        remaining = state.budget_usd - estimated_cost(
            state.record.total_usage + state.pending_usage
        )
        try:
            return self._agents.run(
                self._registry.get(role),
                prompt,
                bundle=bundle,
                budget_usd=max(remaining, Decimal("0")),
            )
        except CircuitOpenError as error:
            raise _StopError(f"breaker open: {role}") from error
        except AgentRunError as error:
            # The call was stopped by its usage limits: the budget rule, with the spend kept.
            state.pending_usage = state.pending_usage + error.usage
            raise _StopError("budget") from error

    def _anomalies(self, state: _RunState) -> list[SensorFinding]:
        """The trace anomalies of this run so far, which the Gate refuses to pass."""
        return trace_findings(
            {state.record.run_id: read_spans(state.trace_path)},
            [state.record],
            state.budget_usd,
        )

    def _latest_report(self) -> EvalReport | None:
        """The persisted report the Gate compares this Iteration against."""
        return ReportStore(self._ra_dir / EVALS_DIRNAME).load_latest()

    def _task_dir(self, run_id: str) -> Path:
        """Where one run's Target Cases and output live; runtime data, never tracked."""
        directory = self._ra_dir / TASKS_DIRNAME / run_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _write_answer_cases(self, run_id: str, task: str) -> Path:
        """Write the one Target Case of an Answer run: the request, judged by the rubric."""
        path = self._task_dir(run_id) / CASES_FILENAME
        case = {
            "name": _answer_case_name(run_id),
            "inputs": task,
            "evaluators": [{"LLMJudge": {"rubric": ANSWER_RUBRIC, "include_input": True}}],
        }
        path.write_text(yaml.safe_dump({"cases": [case]}, sort_keys=False), encoding="utf-8")
        return path

    def _repo_relative(self, path: Path) -> str:
        """`path` as the Run Record stores it: POSIX, relative to the checkout."""
        return path.resolve().relative_to(self._root.resolve()).as_posix()

    def _write_output(self, run_id: str, content: str) -> Path:
        """Write this Iteration's output where the Run Record points at it."""
        path = self._task_dir(run_id) / OUTPUT_FILENAME
        path.write_text(content, encoding="utf-8")
        return path

    def _finish(self, record: RunRecord, outcome: Outcome) -> None:
        """Close the Run Record: how it ended, when, and one last save."""
        record.outcome = outcome
        record.finished_at = self._runners.clock()
        self._runs.save(record)
