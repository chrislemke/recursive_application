"""The Loop runner: the Kernel's orchestration of the five phases (ADR 0006, ADR 0010).

One `run(mode, task, options)` call is one Loop run: Sense collects the findings, Decide picks
the Mode, Act produces a candidate, the Gate judges it, and Learn records what happened. The
runner is synchronous and owns no side effect of its own: agents go through the injected
`AgentRunner`, the four checks, the red check, the evals, the approval, the clock, and the
Trace Store through the injected `Runners`, and every Iteration is appended to the Run Record
as it ends, so a crash leaves the record behind.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from recursive_application.kernel.breaker import BreakerStore, CircuitOpenError
from recursive_application.kernel.bundle import LoopPosition, assemble_state_bundle, frontier_dir
from recursive_application.kernel.checks import RedResult
from recursive_application.kernel.evals import EvalReport, ReportStore, case_for, compare
from recursive_application.kernel.gate import GateInputs, evaluate
from recursive_application.kernel.git import Repo
from recursive_application.kernel.paths import EVALS_DIRNAME, RUNS_DIRNAME, TASKS_DIRNAME
from recursive_application.kernel.records import (
    CheckResult,
    Contract,
    IterationRecord,
    Mode,
    Outcome,
    RunRecord,
    RunStore,
    SensorFinding,
    TriageDecision,
    Usage,
    WorkerOutput,
)
from recursive_application.kernel.registry import Phase, Registry
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

RETRY_HEADING = "Previous attempt failed because:"
"""What a retrying Worker is told about the Iteration the judge turned down."""

BEST_EFFORT_FINDING_SUFFIX = "best-effort"
"""What the `reflection` finding of a best-effort Answer is called, after the run id."""

BEST_EFFORT_RULES: tuple[str, ...] = ("iteration limit", "no progress")
"""The stop rules that return the last output as best effort instead of aborting the run."""


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
class _AnswerTask:
    """What every Iteration of one Answer run shares: the Task and its one Target Case."""

    task: str
    cases_path: Path
    dataset: str
    targets: list[str]


@dataclass
class _RunState:
    """What one run carries from phase to phase while it is going on."""

    record: RunRecord
    trace_path: Path
    findings: list[SensorFinding]
    budget_usd: Decimal
    iteration_limit: int
    max_minutes: int
    pending_usage: Usage = field(default_factory=Usage)
    output: str | None = None
    previous_gate: Literal["passed", "failed"] | None = None
    judge_reason: str | None = None
    no_progress: int = 0


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


def _judge_reason(report: EvalReport, targets: Sequence[str]) -> str | None:
    """Why the judge turned the Answer down, or `None` when it passed."""
    result = case_for(report, targets[0])
    if result is None or result.passed:
        return None
    return "; ".join(result.reasons) or "the judge gave no reason"


class _StopError(Exception):
    """A stop rule fired inside a phase; `reason` is what ends the run where it is caught."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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
        )
        try:
            state.findings = self._sense(state.budget_usd)
            if mode is None:
                decision = self._triage(state)
                record.mode = decision.mode
                if any(gap.kind == "clarification" for gap in decision.reflection.gaps):
                    return self._clarification(state, decision)
            if record.mode is not Mode.ANSWER:
                raise NotImplementedError(f"the Loop runner does not run Mode {record.mode} yet")
            return self._answer(state)
        except _StopError as stop:
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
        answer = _AnswerTask(
            task=state.record.task or "",
            cases_path=self._write_answer_cases(state.record.run_id, state.record.task or ""),
            dataset=case_name,
            targets=[f"{case_name}/{case_name}"],
        )
        number = 1
        while (rule := self._stop_rule(state, number)) is None:
            if self._answer_iteration(state, number, answer):
                self._finish(state.record, "accepted")
                return LoopResult(record=state.record, output=state.output, exit_code=0)
            number += 1
        return self._stopped(state, rule)

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
        """The run hit a stop rule: best effort when there is an Answer, aborted otherwise."""
        if rule in BEST_EFFORT_RULES and state.output is not None:
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

    def _answer_iteration(self, state: _RunState, number: int, answer: _AnswerTask) -> bool:
        """One Answer Iteration: the Worker acts, the judge and the Sensors gate it.

        Whatever ends the Iteration early, a stop rule or a crash, it is still appended to the
        Run Record with the usage it spent, so nothing the run paid for goes unrecorded.
        """
        started_at = self._runners.clock()
        try:
            return self._act_and_gate(state, number, answer, started_at)
        except _StopError:
            self._append_unfinished(state, number, started_at, "aborted")
            raise
        except Exception:
            self._append_unfinished(state, number, started_at, "error")
            raise

    def _append_unfinished(
        self, state: _RunState, number: int, started_at: datetime, outcome: Outcome
    ) -> None:
        """Record an Iteration that never reached the Gate, with what it spent so far."""
        self._runs.append_iteration(
            state.record,
            IterationRecord(
                number=number,
                started_at=started_at,
                finished_at=self._runners.clock(),
                outcome=outcome,
                usage=state.pending_usage,
            ),
        )
        state.pending_usage = Usage()

    def _act_and_gate(
        self, state: _RunState, number: int, answer: _AnswerTask, started_at: datetime
    ) -> bool:
        """Act and Gate of one Answer Iteration: the Worker's output against the judge."""
        result = self._call(
            state,
            "worker",
            _worker_prompt(answer.task, state.judge_reason),
            iteration=number,
            phase="act",
        )
        state.pending_usage = state.pending_usage + result.usage
        output: WorkerOutput = result.output
        state.output = output.content
        output_path = self._write_output(state.record.run_id, output.content)
        report = self._runners.evals(
            EvalRequest(
                run_id=state.record.run_id,
                task_dataset=str(answer.cases_path),
                dataset=answer.dataset,
                output=output.content,
                targets=answer.targets,
            )
        )
        delta = compare(self._latest_report(), report, answer.targets)
        iteration = IterationRecord(
            number=number,
            started_at=started_at,
            finished_at=self._runners.clock(),
            output_path=self._repo_relative(output_path),
            outcome="rejected",
            usage=state.pending_usage,
        )
        # The Iteration is recorded before the Gate, so the cost anomaly rule sees its spend.
        self._runs.append_iteration(state.record, iteration)
        state.pending_usage = Usage()
        gate = evaluate(
            GateInputs(mode=Mode.ANSWER, eval_delta=delta, anomalies=self._anomalies(state))
        )
        state.record.iterations[-1] = iteration.model_copy(
            update={"gate": gate, "outcome": "accepted" if gate.passed else "rejected"}
        )
        self._runs.save(state.record)
        progress = [case for case in delta.newly_passing if case in answer.targets]
        state.no_progress = 0 if progress else state.no_progress + 1
        state.judge_reason = _judge_reason(report, answer.targets)
        state.previous_gate = "passed" if gate.passed else "failed"
        return gate.passed

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
