"""The Loop runner in Answer, Task, and Growth Modes, through `kernel.loop`.

The runner is the primary seam of the Loop: one `run(mode, task, options)` call drives Sense,
Decide, Act, Gate, and Learn over injected adapters, so every test here scripts the models,
the evals runner, the checks, the clock, and the Trace Store and then reads the Run Record, the
files the run wrote, the temporary checkout's git history, and the exit code. A Growth test's
scripted coders write real files through `on_call`, so the diff, the red check, and the commit
have something to see. Nothing reaches a model, the network, or the real checkout.
"""

import itertools
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_ai import Agent
from pydantic_ai.usage import RequestUsage

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.bundle import frontier_dir
from recursive_application.kernel.checks import RedResult
from recursive_application.kernel.evals import (
    CaseResult,
    EvalReport,
    ReportStore,
    validate_frontier,
)
from recursive_application.kernel.git import Repo
from recursive_application.kernel.loop import (
    ANSWER_RUBRIC,
    CASES_FILENAME,
    LOCK_FILENAME,
    EvalRequest,
    LoopOptions,
    LoopRunner,
    Runners,
    estimated_cost,
)
from recursive_application.kernel.paths import (
    EVALS_DIRNAME,
    RA_DIRNAME,
    REPO_ROOT,
    RUNS_DIRNAME,
    TASKS_DIRNAME,
    TRACES_DIRNAME,
)
from recursive_application.kernel.policy import ToolConfig
from recursive_application.kernel.records import (
    CapabilityGap,
    CheckResult,
    CodeReport,
    EvalCase,
    Mode,
    Plan,
    Reflection,
    Review,
    RunStore,
    SensorFinding,
    TriageDecision,
    WorkerOutput,
)
from recursive_application.kernel.registry import (
    CODING_GUIDE,
    Registry,
    RegistryEntry,
    load_registry,
    validate_registry,
)
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.sensors import (
    FINDINGS_FILENAME,
    FindingStore,
    collect,
    stored_findings,
)
from recursive_application.kernel.settings import Settings
from recursive_application.organism.wiki import Wiki
from tests.kernel.loop_support import ScriptedModels, scripted_models

TASK = "What is a Protected Path?"
ANSWER = "A Protected Path is a path the Organism may never modify, the Kernel first of all."
SECOND_ANSWER = (
    "A Protected Path is a path the Organism may never modify: the Kernel, docs, uv.lock."
)
JUDGE_REASON = "LLMJudge: the answer never names the Kernel"
START = datetime(2026, 9, 5, 14, 15, tzinfo=UTC)

TRIAGE_ANSWER = TriageDecision(
    mode=Mode.ANSWER,
    reasoning="The Capability Inventory already covers this question.",
    reflection=Reflection(
        required_capabilities=["explain the path rule"], available=["explain the path rule"]
    ),
)
TRIAGE_CLARIFICATION = TriageDecision(
    mode=Mode.ANSWER,
    reasoning="The request does not say which of the two repositories it means.",
    reflection=Reflection(
        required_capabilities=["answer about a repository"],
        gaps=[
            CapabilityGap(
                kind="clarification",
                description="The request names no repository",
                how_to_acquire="Ask the human which repository and which branch",
            )
        ],
    ),
    clarifying_questions=["Which repository do you mean?", "Which branch?"],
)
TRIAGE_GROWTH = TriageDecision(
    mode=Mode.GROWTH,
    reasoning="The Task needs a capability the Organism does not have yet.",
    reflection=Reflection(required_capabilities=["analyse a text"]),
)
WORKER_ANSWER = WorkerOutput(content=ANSWER)
WORKER_SECOND_TRY = WorkerOutput(content=SECOND_ANSWER)

TASK_REQUEST = "Write the release note for the Loop runner."
DRAFT_NOTE = "The Loop runner runs one Iteration and stops."
RELEASE_NOTE = "The Loop runs Sense, Decide, Act, Gate, and Learn. The Gate judges every Iteration."
RUBRIC = "The note names the five phases of the Loop."
TRIAGE_TASK = TriageDecision(
    mode=Mode.TASK,
    reasoning="The request needs Target Cases and more than one attempt.",
    reflection=Reflection(
        required_capabilities=["write a release note"], available=["write a release note"]
    ),
)
TASK_PLAN = Plan(
    title="Write the release note",
    evidence="The request asks for a note that meets a stated Definition of Done.",
    cause="The Loop runner has no release note yet.",
    change="Draft the note against two Target Cases.",
    target_cases=[
        EvalCase(name="release-note-names-the-phases", inputs=TASK_REQUEST, rubric=RUBRIC),
        EvalCase(
            name="release-note-names-the-gate",
            inputs=TASK_REQUEST,
            expected_output="The Gate judges every Iteration.",
            must_contain=["Gate", "Iteration"],
        ),
    ],
    predicted_impact="Both Target Cases pass and no Guard Case regresses.",
)
TASK_CASES_YAML = {
    "cases": [
        {
            "name": "release-note-names-the-phases",
            "inputs": TASK_REQUEST,
            "evaluators": [{"LLMJudge": {"rubric": RUBRIC, "include_input": True}}],
        },
        {
            "name": "release-note-names-the-gate",
            "inputs": TASK_REQUEST,
            "expected_output": "The Gate judges every Iteration.",
            "evaluators": [{"Contains": "Gate"}, {"Contains": "Iteration"}, "EqualsExpected"],
        },
    ]
}
PLAN_UNKNOWN_ACTOR = TASK_PLAN.model_copy(update={"actor": "specialist_x"})
TOOL_GAP = CapabilityGap(
    kind="tool",
    description="The note cannot cite the repository's git history",
    how_to_acquire="Expose the read-only git tools to an Act-phase agent",
)
PLAN_WITH_GAP = TASK_PLAN.model_copy(update={"gaps": [TOOL_GAP]})
HUMAN_GAP = CapabilityGap(
    kind="connection",
    description="The note needs the release dates from the project's issue tracker",
    how_to_acquire="Grant network access to a Specialist",
    needs_human=["network access"],
)
PLAN_WITH_HUMAN_GAP = TASK_PLAN.model_copy(update={"gaps": [HUMAN_GAP]})
WORKER_DRAFT = WorkerOutput(content=DRAFT_NOTE)
WORKER_NOTE = WorkerOutput(content=RELEASE_NOTE)
WORKER_OUTPUT_WITH_GAP = WorkerOutput(content=DRAFT_NOTE, gaps=[TOOL_GAP])
REVIEW_ACCEPT = Review(
    matches_plan=True,
    gaming_suspected=False,
    notes="The note does what the Plan says.",
    verdict="accept",
)
RED = RedResult(red=True, exit_code=1)


class Clock:
    """The injected clock: it stands still until a test moves it."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        """Move the clock forward, as a test does between Iterations."""
        self.now += timedelta(**delta)


@dataclass
class Harness:
    """One wired `LoopRunner` and everything the test asserts on afterwards."""

    runner: LoopRunner
    models: ScriptedModels
    clock: Clock
    ra_dir: Path
    eval_requests: list[EvalRequest] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    red_files: list[list[str]] = field(default_factory=list)


def _settings(**overrides: Any) -> Settings:
    """Settings with no `.env` behind them, so a run's limits are exactly the test's."""
    return Settings(_env_file=None, **overrides)


def _report(request: EvalRequest, *, passed: bool) -> EvalReport:
    """The report the evals runner returns for one Iteration's Target Cases."""
    cases = []
    for key in request.targets:
        dataset, _, name = key.rpartition("/")
        cases.append(
            CaseResult(
                dataset=dataset,
                name=name,
                passed=passed,
                reasons=[] if passed else [JUDGE_REASON],
            )
        )
    return EvalReport(
        created_at=START,
        run_id=request.run_id,
        datasets=sorted({case.dataset for case in cases}),
        cases=cases,
    )


def _recorded(
    script: Mapping[str, Sequence[Any]],
    effects: Mapping[str, Callable[[], None]] | None,
    events: list[str],
) -> dict[str, Callable[[], None]]:
    """Every scripted role's side effect, preceded by a note in the run's event log."""

    def recorded(role: str) -> Callable[[], None]:
        effect = (effects or {}).get(role)

        def call() -> None:
            events.append(role)
            if effect is not None:
                effect()

        return call

    return {role: recorded(role) for role in script}


def _harness(
    checkout: Path,
    script: Mapping[str, Sequence[Any]],
    *,
    passes: bool | Sequence[bool] = True,
    approves: bool | Sequence[bool] = True,
    settings: Settings | None = None,
    breakers: BreakerStore | None = None,
    clock: Clock | None = None,
    usage: RequestUsage | None = None,
    on_evals: Callable[[EvalRequest], None] | None = None,
    on_call: Mapping[str, Callable[[], None]] | None = None,
    checks: Sequence[CheckResult] = (),
    red: RedResult = RED,
    registry: Registry | None = None,
    evals: Callable[[EvalRequest], EvalReport] | None = None,
) -> Harness:
    """A `LoopRunner` over the temporary checkout with every adapter replaced."""
    ra_dir = checkout / RA_DIRNAME
    settings = settings if settings is not None else _settings()
    breakers = breakers if breakers is not None else BreakerStore(ra_dir / "breakers.json")
    harness_events: list[str] = []
    models = scripted_models(
        script, usage=usage, on_call=_recorded(script, on_call, harness_events)
    )
    clock = clock if clock is not None else Clock()
    harness_requests: list[EvalRequest] = []
    harness_approvals: list[str] = []
    harness_red_files: list[list[str]] = []
    verdicts = [passes] if isinstance(passes, bool) else list(passes)
    decisions = [approves] if isinstance(approves, bool) else list(approves)

    def run_evals(request: EvalRequest) -> EvalReport:
        harness_events.append("evals")
        harness_requests.append(request)
        if on_evals is not None:
            on_evals(request)
        if evals is not None:
            return evals(request)
        verdict = verdicts[min(len(harness_requests), len(verdicts)) - 1]
        return _report(request, passed=verdict)

    def run_checks(root: Path) -> list[CheckResult]:
        harness_events.append("checks")
        return list(checks)

    def run_red_check(root: Path, files: Sequence[str]) -> RedResult:
        harness_events.append("red check")
        harness_red_files.append(list(files))
        return red

    def approve(text: str) -> bool:
        harness_events.append("approve")
        harness_approvals.append(text)
        return decisions[min(len(harness_approvals), len(decisions)) - 1]

    def configure_tracing(run_id: str) -> Path:
        path = ra_dir / TRACES_DIRNAME / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    runner = LoopRunner(
        settings=settings,
        registry=registry if registry is not None else load_registry(),
        agents=AgentRunner(settings, breakers, root=REPO_ROOT, model_factory=models),
        repo=Repo(checkout),
        wiki=Wiki(checkout / "wiki"),
        root=checkout,
        ra_dir=ra_dir,
        runners=Runners(
            checks=run_checks,
            red_check=run_red_check,
            evals=run_evals,
            approve=approve,
            clock=clock,
            tracing=configure_tracing,
        ),
        breakers=breakers,
    )
    return Harness(
        runner=runner,
        models=models,
        clock=clock,
        ra_dir=ra_dir,
        eval_requests=harness_requests,
        approvals=harness_approvals,
        events=harness_events,
        red_files=harness_red_files,
    )


def test_an_answer_the_judge_accepts_ends_the_run_after_one_iteration(checkout: Path) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]})

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.exit_code == 0
    assert result.record.outcome == "accepted"
    assert result.record.mode is Mode.ANSWER
    assert len(result.record.iterations) == 1
    iteration = result.record.iterations[0]
    assert iteration.outcome == "accepted"
    assert iteration.output_path == f".ra/tasks/{result.record.run_id}/output.md"
    assert (checkout / iteration.output_path).read_text(encoding="utf-8") == ANSWER
    assert result.output == ANSWER
    assert (harness.ra_dir / TRACES_DIRNAME / f"{result.record.run_id}.jsonl").exists()


def test_the_kernel_writes_one_target_case_for_the_request_and_hands_it_to_the_evals_runner(
    checkout: Path,
) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]})

    result = harness.runner.run(None, TASK, LoopOptions())

    run_id = result.record.run_id
    cases_path = harness.ra_dir / TASKS_DIRNAME / run_id / CASES_FILENAME
    request = harness.eval_requests[0]
    assert request.run_id == run_id
    assert request.task_dataset == str(cases_path)
    assert request.output == ANSWER
    assert request.targets == [f"answer-{run_id}/answer-{run_id}"]
    assert yaml.safe_load(cases_path.read_text(encoding="utf-8")) == {
        "cases": [
            {
                "name": f"answer-{run_id}",
                "inputs": TASK,
                "evaluators": [{"LLMJudge": {"rubric": ANSWER_RUBRIC, "include_input": True}}],
            }
        ]
    }


def test_an_answer_the_judge_never_passes_comes_back_as_best_effort_at_the_iteration_limit(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER, WORKER_SECOND_TRY]},
        passes=False,
        settings=_settings(ra_max_iterations=2, ra_no_progress_iterations=5),
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert len(result.record.iterations) == 2
    assert result.record.outcome == "rejected"
    assert result.exit_code == 1
    assert result.reason is not None
    assert result.reason.startswith("best effort")
    assert "iteration limit" in result.reason
    assert "judge" in result.reason
    assert result.output == SECOND_ANSWER
    findings = stored_findings(FindingStore(harness.ra_dir / FINDINGS_FILENAME))
    assert [finding.source for finding in findings] == ["reflection"]
    assert findings[0].id == f"reflection:{result.record.run_id}:best-effort"


def test_the_second_worker_prompt_carries_the_task_and_the_judges_reason(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER, WORKER_SECOND_TRY]},
        passes=False,
        settings=_settings(ra_max_iterations=2, ra_no_progress_iterations=5),
    )

    harness.runner.run(None, TASK, LoopOptions())

    prompts = harness.models.prompts_for("worker")
    assert prompts[0] == TASK
    assert prompts[1].startswith(TASK)
    assert "Previous attempt failed because:" in prompts[1]
    assert JUDGE_REASON in prompts[1]


def test_a_run_past_the_wall_time_limit_is_aborted_before_the_next_iteration(
    checkout: Path,
) -> None:
    clock = Clock()
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        passes=False,
        clock=clock,
        on_evals=lambda request: clock.advance(minutes=31),
    )

    result = harness.runner.run(None, TASK, LoopOptions(max_minutes=30))

    assert len(result.record.iterations) == 1
    assert result.record.outcome == "aborted"
    assert result.reason == "wall time"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 1


def test_a_run_that_has_spent_its_budget_is_aborted_before_the_next_iteration(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        passes=False,
        usage=RequestUsage(cost=Decimal("3")),
    )

    result = harness.runner.run(None, TASK, LoopOptions(budget_usd=Decimal("5")))

    assert len(result.record.iterations) == 1
    assert result.record.total_usage.cost_usd == Decimal("6")
    assert result.record.outcome == "aborted"
    assert result.reason == "budget"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 1


def test_a_run_whose_model_reports_no_price_is_budgeted_by_the_token_fallback(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        passes=False,
        usage=RequestUsage(input_tokens=400_000, output_tokens=600_000),
    )

    result = harness.runner.run(None, TASK, LoopOptions(budget_usd=Decimal("5")))

    assert result.record.total_usage.cost_usd == Decimal("0")
    assert result.record.total_usage.input_tokens + result.record.total_usage.output_tokens == (
        2_000_000
    )
    assert estimated_cost(result.record.total_usage) == Decimal("6")
    assert result.reason == "budget"
    assert result.exit_code == 2


def test_two_iterations_without_a_newly_passing_target_case_stop_the_run_as_no_progress(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER, WORKER_SECOND_TRY]},
        passes=False,
        settings=_settings(ra_max_iterations=5, ra_no_progress_iterations=2),
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert len(result.record.iterations) == 2
    assert result.record.outcome == "rejected"
    assert result.exit_code == 1
    assert result.reason is not None
    assert result.reason.startswith("best effort")
    assert "no progress" in result.reason


def _explode() -> None:
    """A call that always fails, so a test can open a breaker before the run starts."""
    raise RuntimeError("the worker is down")


def test_an_open_breaker_aborts_the_run_and_names_the_agent_it_belongs_to(
    checkout: Path,
) -> None:
    breakers = BreakerStore(checkout / RA_DIRNAME / "breakers.json", failure_threshold=3)
    for _ in range(3):
        with pytest.raises(RuntimeError, match="the worker is down"):
            breakers.call("worker", _explode)
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        breakers=breakers,
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.record.outcome == "aborted"
    assert result.reason == "breaker open: worker"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 0
    assert [iteration.outcome for iteration in result.record.iterations] == ["aborted"]


def test_an_unexpected_failure_ends_the_run_as_an_internal_error(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [RuntimeError("the model is down")]},
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.record.outcome == "error"
    assert result.reason is not None
    assert "the model is down" in result.reason
    assert result.exit_code == 3


def test_a_clarification_gap_ends_the_run_with_triages_questions_and_runs_nothing_else(
    checkout: Path,
) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_CLARIFICATION], "worker": [WORKER_ANSWER]})

    result = harness.runner.run(None, "What changed?", LoopOptions())

    assert result.questions == ["Which repository do you mean?", "Which branch?"]
    assert result.reason == "clarification"
    assert result.exit_code == 2
    assert result.output is None
    assert result.record.outcome == "aborted"
    assert harness.models.calls_for("worker") == 0
    assert harness.eval_requests == []
    assert RunStore(harness.ra_dir / RUNS_DIRNAME).load(result.record.run_id).outcome == "aborted"


def test_every_agent_is_told_where_in_the_loop_it_stands(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER, WORKER_SECOND_TRY]},
        passes=False,
    )

    harness.runner.run(None, TASK, LoopOptions())

    triage = harness.models.requests["triage"][0].instructions
    first, second = (request.instructions for request in harness.models.requests["worker"])
    assert "Mode: answer" in triage
    assert "Phase: decide" in triage
    assert "Role: triage" in triage
    assert "Mode: answer" in first
    assert "Iteration: 1 of 5" in first
    assert "Phase: act" in first
    assert "Role: worker" in first
    assert "Previous Gate: none" in first
    assert "Iteration: 2 of 5" in second
    assert "Previous Gate: failed" in second


def test_a_crash_inside_an_iteration_still_leaves_that_iteration_in_the_record(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [RuntimeError("the model is down")]},
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.exit_code == 3
    assert [iteration.outcome for iteration in result.record.iterations] == ["error"]
    assert result.record.iterations[0].usage.requests == 1


def test_the_option_budget_binds_every_agent_call_so_triage_alone_can_exhaust_it(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        usage=RequestUsage(input_tokens=700, output_tokens=700),
    )

    result = harness.runner.run(None, TASK, LoopOptions(budget_usd=Decimal("0.003")))

    assert result.record.outcome == "aborted"
    assert result.reason == "budget"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 0


def test_the_evals_request_names_the_dataset_its_runtime_cases_are_reported_under(
    checkout: Path,
) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]})

    result = harness.runner.run(None, TASK, LoopOptions())

    request = harness.eval_requests[0]
    assert request.dataset == f"answer-{result.record.run_id}"
    assert request.targets == [f"answer-{result.record.run_id}/answer-{result.record.run_id}"]


def test_sense_hands_triage_the_open_findings_of_the_runtime_directory(checkout: Path) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]})

    harness.runner.run(None, TASK, LoopOptions())

    assert "evals:frontier/text-analysis" in harness.models.prompts_for("triage")[0]


def test_a_task_loop_iterates_until_its_target_cases_pass_and_keeps_its_cases_out_of_the_tree(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN, TASK_PLAN],
            "worker": [WORKER_DRAFT, WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT, REVIEW_ACCEPT],
        },
        passes=[False, True],
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert result.exit_code == 0
    assert result.record.mode is Mode.TASK
    assert result.record.outcome == "accepted"
    assert [iteration.outcome for iteration in result.record.iterations] == ["rejected", "accepted"]
    assert result.output == RELEASE_NOTE
    run_id = result.record.run_id
    cases_path = harness.ra_dir / TASKS_DIRNAME / run_id / CASES_FILENAME
    assert yaml.safe_load(cases_path.read_text(encoding="utf-8")) == TASK_CASES_YAML
    request = harness.eval_requests[0]
    assert request.task_dataset == str(cases_path)
    assert request.dataset == f"task-{run_id}"
    assert request.targets == [
        f"task-{run_id}/release-note-names-the-phases",
        f"task-{run_id}/release-note-names-the-gate",
    ]
    assert Repo(checkout).is_clean()


def test_the_reviewer_judges_the_task_iteration_whose_target_cases_passed_and_reaches_the_gate(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN, TASK_PLAN],
            "worker": [WORKER_DRAFT, WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT],
        },
        passes=[False, True],
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert harness.models.calls_for("reviewer") == 1
    prompt = harness.models.prompts_for("reviewer")[0]
    assert "title: Write the release note" in prompt
    assert RELEASE_NOTE in prompt
    accepted = result.record.iterations[1]
    assert accepted.review == REVIEW_ACCEPT
    assert accepted.gate is not None
    assert [(check.name, check.status) for check in accepted.gate.checks] == [
        ("evals", "passed"),
        ("anomalies", "passed"),
        ("review", "passed"),
    ]
    rejected = result.record.iterations[0]
    assert rejected.gate is not None
    assert [check.status for check in rejected.gate.checks] == ["failed", "skipped", "skipped"]


def test_a_task_loop_whose_target_cases_never_pass_is_aborted_at_the_iteration_limit(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN, TASK_PLAN],
            "worker": [WORKER_DRAFT, WORKER_DRAFT],
        },
        passes=False,
        settings=_settings(ra_max_iterations=2, ra_no_progress_iterations=5),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert len(result.record.iterations) == 2
    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"
    assert result.exit_code == 2
    assert harness.models.calls_for("reviewer") == 0


def test_the_approval_shows_the_plan_and_its_target_cases_and_a_refusal_ends_the_run(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_TASK], "planner": [TASK_PLAN], "worker": [WORKER_NOTE]},
        approves=False,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert len(harness.approvals) == 1
    shown = harness.approvals[0]
    assert "title: Write the release note" in shown
    assert "release-note-names-the-phases" in shown
    assert "release-note-names-the-gate" in shown
    assert RUBRIC in shown
    assert result.record.outcome == "aborted"
    assert result.reason == "approval refused"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 0
    assert [iteration.outcome for iteration in result.record.iterations] == ["aborted"]


def test_the_yes_option_runs_the_task_loop_without_asking_the_human(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT],
        },
        approves=False,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert harness.approvals == []
    assert result.record.outcome == "accepted"
    assert result.exit_code == 0


def test_the_actors_output_lands_in_the_runs_task_directory_and_the_iteration_points_at_it(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    run_id = result.record.run_id
    iteration = result.record.iterations[0]
    assert iteration.output_path == f".ra/{TASKS_DIRNAME}/{run_id}/output.md"
    assert (checkout / iteration.output_path).read_text(encoding="utf-8") == RELEASE_NOTE
    assert iteration.plan == TASK_PLAN
    assert result.output == RELEASE_NOTE


def test_a_plan_naming_an_actor_the_registry_does_not_know_is_rejected_before_the_act_phase(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [PLAN_UNKNOWN_ACTOR, TASK_PLAN],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert [iteration.outcome for iteration in result.record.iterations] == ["rejected", "accepted"]
    rejected = result.record.iterations[0]
    assert rejected.plan == PLAN_UNKNOWN_ACTOR
    assert rejected.gate is None
    assert rejected.output_path is None
    assert harness.models.calls_for("worker") == 1
    assert len(harness.eval_requests) == 1
    assert "unknown actor: specialist_x" in harness.models.prompts_for("planner")[1]


def test_a_plan_that_names_a_capability_gap_turns_the_run_into_a_growth_loop(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_TASK], "planner": [PLAN_WITH_GAP], "worker": [WORKER_NOTE]},
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert result.record.mode is Mode.GROWTH
    assert len(harness.approvals) == 1
    assert "mode: growth" in harness.approvals[0]
    assert TOOL_GAP.description in harness.approvals[0]
    assert harness.models.calls_for("worker") == 0
    assert result.record.outcome == "error"
    assert result.exit_code == 3


def test_a_gap_the_actor_reports_turns_the_run_into_a_growth_loop_with_a_second_approval(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN],
            "worker": [WorkerOutput(content=DRAFT_NOTE, gaps=[TOOL_GAP])],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert result.record.mode is Mode.GROWTH
    assert len(harness.approvals) == 2
    assert "title: Write the release note" in harness.approvals[0]
    assert TOOL_GAP.description in harness.approvals[1]
    assert harness.eval_requests == []
    assert result.record.outcome == "error"
    assert result.exit_code == 3


def test_a_gap_only_the_human_can_close_becomes_a_reflection_finding_the_next_sense_sees(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [PLAN_WITH_HUMAN_GAP],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.record.mode is Mode.TASK
    assert result.record.outcome == "accepted"
    findings = stored_findings(FindingStore(harness.ra_dir / FINDINGS_FILENAME))
    assert len(findings) == 1
    assert findings[0].id == f"reflection:{result.record.run_id}:1"
    assert findings[0].source == "reflection"
    assert findings[0].severity == "medium"
    assert findings[0].summary == HUMAN_GAP.description
    assert findings[0].details == (
        "kind: connection\n"
        "how_to_acquire: Grant network access to a Specialist\n"
        "needs_human: network access"
    )
    sensed = collect(
        ra_dir=harness.ra_dir,
        wiki=Wiki(checkout / "wiki"),
        frontier_dir=frontier_dir(checkout),
        budget_usd=Decimal("5"),
    )
    assert findings[0].id in [finding.id for finding in sensed]


def test_two_iterations_the_kernel_refuses_before_act_stop_the_run_as_no_progress(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [PLAN_UNKNOWN_ACTOR, PLAN_UNKNOWN_ACTOR],
            "worker": [WORKER_NOTE],
        },
        settings=_settings(ra_max_iterations=5, ra_no_progress_iterations=2),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert [iteration.outcome for iteration in result.record.iterations] == ["rejected", "rejected"]
    assert result.record.outcome == "aborted"
    assert result.reason == "no progress"
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 0


PLAN_WITHOUT_TARGETS = TASK_PLAN.model_copy(update={"target_cases": []})


def test_a_plan_without_target_cases_is_refused_before_act_and_named_in_the_record(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [PLAN_WITHOUT_TARGETS, TASK_PLAN],
            "worker": [WORKER_ANSWER],
            "reviewer": [REVIEW_ACCEPT],
        },
        settings=_settings(ra_no_progress_iterations=5),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert [iteration.number for iteration in result.record.iterations] == [1, 2]
    assert result.record.iterations[0].outcome == "rejected"
    assert result.record.iterations[0].reason == "no Target Cases"
    assert result.record.outcome == "accepted"
    assert harness.models.calls_for("worker") == 1


def test_the_kernel_refuses_a_plan_before_asking_the_human_to_approve_it(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN.model_copy(update={"actor": "specialist_x"}), TASK_PLAN],
            "worker": [WORKER_ANSWER],
            "reviewer": [REVIEW_ACCEPT],
        },
        settings=_settings(ra_no_progress_iterations=5),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert result.record.iterations[0].reason == "unknown actor: specialist_x"
    assert len(harness.approvals) == 1
    assert "specialist_x" not in harness.approvals[0]
    worker_prompt = harness.models.prompts_for("worker")[0]
    assert "unknown actor" not in worker_prompt
    planner_prompt = harness.models.prompts_for("planner")[1]
    assert "unknown actor: specialist_x" in planner_prompt


def test_the_reviewers_usage_lands_in_the_iteration_that_paid_for_it(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN],
            "worker": [WORKER_ANSWER],
            "reviewer": [REVIEW_ACCEPT],
        },
        usage=RequestUsage(input_tokens=10, output_tokens=1),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert harness.models.calls_for("reviewer") == 1
    assert result.record.iterations[0].usage.requests == 4
    assert result.record.total_usage.requests == 4


def test_an_escalating_iteration_keeps_its_plan_and_its_draft_in_the_record(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN],
            "worker": [WORKER_OUTPUT_WITH_GAP],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert result.record.mode is Mode.GROWTH
    assert iteration.plan == TASK_PLAN
    assert iteration.output_path == f".ra/tasks/{result.record.run_id}/output.md"
    assert (checkout / iteration.output_path).read_text(encoding="utf-8") == (
        WORKER_OUTPUT_WITH_GAP.content
    )


def test_a_gap_triage_recognised_but_did_not_act_on_becomes_a_reflection_finding(
    checkout: Path,
) -> None:
    triage_with_human_gap = TRIAGE_TASK.model_copy(
        update={
            "reflection": TRIAGE_TASK.reflection.model_copy(update={"gaps": [HUMAN_GAP]}),
        }
    )
    harness = _harness(
        checkout,
        {
            "triage": [triage_with_human_gap],
            "planner": [TASK_PLAN],
            "worker": [WORKER_ANSWER],
            "reviewer": [REVIEW_ACCEPT],
        },
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    findings = collect(
        ra_dir=harness.ra_dir,
        wiki=Wiki(checkout / "wiki"),
        frontier_dir=checkout / "evals" / "frontier",
        budget_usd=Decimal("5"),
    )
    assert f"reflection:{result.record.run_id}:1" in [finding.id for finding in findings]


def test_a_planner_clarification_gap_ends_the_run_with_its_question_like_triages(
    checkout: Path,
) -> None:
    unclear = TASK_PLAN.model_copy(
        update={
            "gaps": [
                CapabilityGap(
                    kind="clarification",
                    description="Which release?",
                    how_to_acquire="Ask the Operator which release the note is for.",
                )
            ]
        }
    )
    harness = _harness(
        checkout, {"triage": [TRIAGE_TASK], "planner": [unclear], "worker": [WORKER_ANSWER]}
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.reason == "clarification"
    assert result.questions == ["Which release?"]
    assert result.exit_code == 2
    assert harness.models.calls_for("worker") == 0


GROWTH_REQUEST = "Teach the Worker to answer what the Gate is."
GLOSSARY_PATH = "src/recursive_application/organism/glossary.py"
GLOSSARY_TEST_PATH = "tests/organism/test_glossary.py"
TARGET_KEY = "answers/answers-4-what-is-the-gate"
GROWTH_CASE = EvalCase(
    name="answers-4-what-is-the-gate",
    inputs="What is the Gate?",
    must_contain=["Gate"],
)
GROWTH_PLAN = Plan(
    title="Teach the Worker what the Gate is",
    evidence="The answers dataset holds no case about the Gate.",
    cause="Nothing in the Organism states what the Gate is.",
    change="Add a glossary module and the answers case that proves it.",
    target_paths=[GLOSSARY_PATH],
    tests=['`glossary_entry("Gate")` returns the Gate\'s one-sentence definition'],
    target_cases=[GROWTH_CASE],
    predicted_impact="The new answers case passes and no Guard Case regresses.",
    dataset="evals/answers.yaml",
)


def test_a_growth_run_on_a_dirty_tree_is_refused_before_any_agent_runs(checkout: Path) -> None:
    (checkout / "README.md").write_text("# changed\n", encoding="utf-8")
    harness = _harness(checkout, {"planner": [GROWTH_PLAN]})

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "dirty working tree"
    assert result.exit_code == 2
    assert harness.models.calls_for("planner") == 0
    assert not (harness.ra_dir / LOCK_FILENAME).exists()


def test_a_growth_run_refuses_to_start_while_another_run_holds_the_lock(checkout: Path) -> None:
    harness = _harness(checkout, {"planner": [GROWTH_PLAN]})
    lock = harness.ra_dir / LOCK_FILENAME
    lock.write_text("20260101-000000-abcdef", encoding="utf-8")

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "lock held"
    assert result.exit_code == 2
    assert harness.models.calls_for("planner") == 0
    assert lock.read_text(encoding="utf-8") == "20260101-000000-abcdef"


def test_the_growth_lock_holds_the_run_id_while_the_run_lasts_and_is_released_afterwards(
    checkout: Path,
) -> None:
    lock = checkout / RA_DIRNAME / LOCK_FILENAME
    held: list[str] = []
    harness = _harness(
        checkout,
        {"planner": [GROWTH_PLAN]},
        approves=False,
        on_call={"planner": lambda: held.append(lock.read_text(encoding="utf-8"))},
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions())

    assert held == [result.record.run_id]
    assert not lock.exists()
    assert result.reason == "approval refused"
    assert result.exit_code == 2


def test_the_kernel_appends_the_plans_new_target_cases_to_the_dataset_it_names(
    checkout: Path,
) -> None:
    dataset = checkout / "evals" / "answers.yaml"
    before = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    after = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    assert len(before["cases"]) == 3
    assert len(after["cases"]) == 4
    assert after["cases"][:3] == before["cases"]
    assert after["cases"][3] == {
        "name": "answers-4-what-is-the-gate",
        "inputs": "What is the Gate?",
        "evaluators": [{"Contains": "Gate"}],
    }
    assert after["evaluators"] == before["evaluators"]


FRONTIER_PLAN = GROWTH_PLAN.model_copy(
    update={
        "dataset": None,
        "target_cases": [
            EvalCase(
                name="text-analysis-1-summarise",
                inputs="Summarise the argument of this text.",
                rubric="The summary names the argument's conclusion.",
            )
        ],
    }
)


def test_a_plan_whose_targets_are_existing_frontier_cases_appends_nothing(
    checkout: Path,
) -> None:
    harness = _harness(checkout, {"planner": [FRONTIER_PLAN]}, approves=False)

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions())

    assert result.reason == "approval refused"
    assert harness.models.calls_for("planner") == 1
    assert Repo(checkout).is_clean()


GLOSSARY_SOURCE = '''"""The Organism's glossary of the terms the Worker is asked about."""


def glossary_entry(name: str) -> str:
    """The one-sentence definition of `name`."""
    return "The Gate is the deterministic quality check an Iteration must pass."
'''
GLOSSARY_TEST_SOURCE = '''"""The glossary, through its public entry point."""

from recursive_application.organism.glossary import glossary_entry


def test_the_glossary_defines_the_gate_as_the_check_an_iteration_must_pass() -> None:
    assert glossary_entry("Gate") == (
        "The Gate is the deterministic quality check an Iteration must pass."
    )
'''
TEST_REPORT = CodeReport(
    summary="One failing test for the Gate's glossary entry.",
    changed_files=[GLOSSARY_TEST_PATH],
)
CODE_REPORT = CodeReport(
    summary="The glossary now answers what the Gate is.",
    changed_files=[GLOSSARY_PATH],
    checks=[CheckResult(name="pytest", passed=True)],
)
LIBRARIAN_SUMMARY = "Recorded the Improvement on the Wiki's capability page."
LESSON_SUMMARY = "Recorded the lesson on the Wiki's lessons page."
CHECKS_PASSED = [
    CheckResult(name="ruff-format", passed=True),
    CheckResult(name="ruff-check", passed=True),
    CheckResult(name="ty", passed=True),
    CheckResult(name="pytest", passed=True),
]
GROWTH_SCRIPT: Mapping[str, Sequence[Any]] = {
    "planner": [GROWTH_PLAN],
    "test_writer": [TEST_REPORT],
    "implementer": [CODE_REPORT],
    "reviewer": [REVIEW_ACCEPT],
    "librarian": [LIBRARIAN_SUMMARY],
}

REJECTED_SCRIPT: Mapping[str, Sequence[Any]] = {
    "planner": [GROWTH_PLAN],
    "test_writer": [TEST_REPORT],
    "implementer": [CODE_REPORT],
    "librarian": [LESSON_SUMMARY],
}


def _write_file(path: Path, text: str) -> None:
    """Write one file inside the temporary checkout, creating its directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _coder_effects(checkout: Path) -> dict[str, Callable[[], None]]:
    """What the scripted coders leave behind, where the real ones would use their file tools."""
    return {
        "test_writer": lambda: _write_file(checkout / GLOSSARY_TEST_PATH, GLOSSARY_TEST_SOURCE),
        "implementer": lambda: _write_file(checkout / GLOSSARY_PATH, GLOSSARY_SOURCE),
    }


def _git_output(root: Path, *args: str) -> str:
    """Test-side git, for the facts about a commit the Kernel's own wrapper does not report."""
    done = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def test_a_growth_iteration_the_gate_accepts_is_recorded_and_committed_by_the_kernel(
    checkout: Path,
) -> None:
    repo = Repo(checkout)
    previous = repo.head_sha()
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.exit_code == 0
    assert result.record.outcome == "accepted"
    assert [iteration.outcome for iteration in result.record.iterations] == ["accepted"]
    iteration = result.record.iterations[0]
    assert iteration.plan == GROWTH_PLAN
    assert iteration.test_report == TEST_REPORT
    assert iteration.code_report == CODE_REPORT
    assert iteration.review == REVIEW_ACCEPT
    assert iteration.commit_sha != previous
    assert repo.head_sha() != previous
    assert repo.is_clean()
    assert "ra: Teach the Worker what the Gate is" in repo.log(n=2)
    assert iteration.commit_sha in {repo.head_sha(), _git_output(checkout, "rev-parse", "HEAD~1")}
    assert "ra Kernel" in repo.show("HEAD")
    assert _git_output(checkout, "log", "-1", "--format=%G?") == "N"


def test_the_growth_iteration_runs_its_steps_in_the_order_the_loop_prescribes(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions())

    assert result.record.outcome == "accepted"
    assert harness.events == [
        "planner",
        "approve",
        "test_writer",
        "red check",
        "implementer",
        "checks",
        "evals",
        "reviewer",
        "librarian",
    ]
    assert harness.red_files == [[GLOSSARY_TEST_PATH]]


def test_the_gate_runs_the_guard_subset_and_the_librarian_records_the_improvement(
    checkout: Path,
) -> None:
    log = checkout / "wiki" / "log.md"
    before = log.read_text(encoding="utf-8").splitlines()
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    request = harness.eval_requests[0]
    assert request.datasets == ["answers", "triage"]
    assert request.targets == [TARGET_KEY]
    assert request.task_dataset is None
    assert len(harness.eval_requests) == 1
    prompt = harness.models.prompts_for("librarian")[0]
    assert "Teach the Worker what the Gate is" in prompt
    assert GLOSSARY_PATH in prompt
    assert "Phase: learn" in harness.models.requests["librarian"][0].instructions
    after = log.read_text(encoding="utf-8").splitlines()
    assert len(after) == len(before) + 1
    assert after[-1].endswith(
        f"Run {result.record.run_id}: accepted Teach the Worker what the Gate is"
    )


TY_OUTPUT = "error[invalid-argument-type] glossary.py:6: expected `str`, found `int`"
CHECKS_TY_FAILED = [
    CheckResult(name="ruff-format", passed=True),
    CheckResult(name="ruff-check", passed=True),
    CheckResult(name="ty", passed=False, output=TY_OUTPUT),
    CheckResult(name="pytest", passed=True),
]


def test_a_failing_check_reaches_the_gate_with_its_output_and_stops_the_costlier_evidence(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        REJECTED_SCRIPT,
        checks=CHECKS_TY_FAILED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.commit_sha is None
    assert iteration.gate is not None
    assert [(check.name, check.status) for check in iteration.gate.checks] == [
        ("protected-paths", "passed"),
        ("write-scope", "passed"),
        ("eval-cases", "passed"),
        ("ruff-format", "passed"),
        ("ruff-check", "passed"),
        ("ty", "failed"),
        ("pytest", "skipped"),
        ("evals", "skipped"),
        ("anomalies", "skipped"),
        ("review", "skipped"),
    ]
    assert [check.excerpt for check in iteration.gate.checks if check.name == "ty"] == [TY_OUTPUT]
    assert harness.eval_requests == []
    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"


REVIEW_REJECT = Review(
    matches_plan=False,
    gaming_suspected=True,
    notes="The test asserts the string the module returns, not a behaviour.",
    verdict="reject",
)


def test_a_reviewer_that_rejects_the_diff_fails_the_gate_and_the_improvement_is_not_committed(
    checkout: Path,
) -> None:
    repo = Repo(checkout)
    previous = repo.head_sha()
    harness = _harness(
        checkout,
        {
            "planner": [GROWTH_PLAN],
            "test_writer": [TEST_REPORT],
            "implementer": [CODE_REPORT],
            "reviewer": [REVIEW_REJECT],
            "librarian": [LESSON_SUMMARY],
        },
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    prompt = harness.models.prompts_for("reviewer")[0]
    assert "title: Teach the Worker what the Gate is" in prompt
    assert "diff --git" in prompt
    iteration = result.record.iterations[0]
    assert iteration.review == REVIEW_REJECT
    assert iteration.outcome == "rejected"
    assert iteration.commit_sha is None
    assert iteration.gate is not None
    assert [
        (check.name, check.status, check.excerpt)
        for check in iteration.gate.checks
        if check.name in {"evals", "anomalies", "review"}
    ] == [
        ("evals", "passed", ""),
        ("anomalies", "passed", ""),
        ("review", "failed", REVIEW_REJECT.notes),
    ]
    assert repo.file_at("HEAD", GLOSSARY_PATH) is None
    assert _git_output(checkout, "rev-parse", "HEAD~1") == previous
    assert _git_output(checkout, "log", "-1", "--format=%s") == (
        f"ra: lesson from {result.record.run_id}"
    )
    prompts = harness.models.prompts_for("librarian")
    assert len(prompts) == 1
    assert prompts[0].startswith("Rejected:")
    assert f"review: {REVIEW_REJECT.notes}" in prompts[0]
    assert "Improvement:" not in prompts[0]


def test_a_refused_approval_leaves_the_tree_at_the_commit_it_started_from(checkout: Path) -> None:
    dataset = checkout / "evals" / "answers.yaml"
    before = dataset.read_text(encoding="utf-8")
    harness = _harness(checkout, {"planner": [GROWTH_PLAN]}, approves=False)

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions())

    assert result.reason == "approval refused"
    assert harness.approvals[0].count("answers-4-what-is-the-gate") == 1
    assert Repo(checkout).is_clean()
    assert dataset.read_text(encoding="utf-8") == before


def test_appending_a_target_case_keeps_the_dataset_file_byte_identical_above_it(
    checkout: Path,
) -> None:
    dataset = checkout / "evals" / "answers.yaml"
    before = dataset.read_text(encoding="utf-8")
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    after = Repo(checkout).file_at("HEAD", "evals/answers.yaml")
    assert after is not None
    assert after.startswith(before)
    assert after[len(before) :] == (
        "  - name: answers-4-what-is-the-gate\n"
        "    inputs: What is the Gate?\n"
        "    evaluators:\n"
        "      - Contains: Gate\n"
    )


def test_a_plan_naming_a_dataset_outside_evals_is_refused_before_anything_is_written(
    checkout: Path,
) -> None:
    rogue = GROWTH_PLAN.model_copy(update={"dataset": "README.md"})
    before = (checkout / "README.md").read_text(encoding="utf-8")
    harness = _harness(checkout, {"planner": [rogue, GROWTH_PLAN]}, approves=False)

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions())

    assert result.record.iterations[0].reason == "dataset outside evals/: README.md"
    assert (checkout / "README.md").read_text(encoding="utf-8") == before
    assert Repo(checkout).is_clean()


def test_the_librarian_learns_after_the_commit_and_is_told_its_sha_and_dataset(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    sha = result.record.iterations[0].commit_sha
    assert sha is not None
    prompt = harness.models.prompts_for("librarian")[0]
    assert f"Commit: {sha}" in prompt
    assert "Dataset: evals/answers.yaml" in prompt
    assert f"Run: {result.record.run_id}" in prompt
    assert harness.events.index("librarian") > harness.events.index("reviewer")
    assert Repo(checkout).is_clean()


def test_a_growth_planners_gap_the_human_must_grant_becomes_a_reflection_finding(
    checkout: Path,
) -> None:
    plan_with_human_gap = GROWTH_PLAN.model_copy(update={"gaps": [HUMAN_GAP]})
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [plan_with_human_gap]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    findings = collect(
        ra_dir=harness.ra_dir,
        wiki=Wiki(checkout / "wiki"),
        frontier_dir=checkout / "evals" / "frontier",
        budget_usd=Decimal("5"),
    )
    assert f"reflection:{result.record.run_id}:1" in [finding.id for finding in findings]


def test_a_frontier_plan_naming_no_known_case_is_refused_before_any_coder_runs(
    checkout: Path,
) -> None:
    unknown = FRONTIER_PLAN.model_copy(
        update={
            "target_cases": [EvalCase(name="nowhere-1-nothing", inputs="?", rubric="It answers.")]
        }
    )
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [unknown]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.iterations[0].reason == "no dataset: nowhere-1-nothing"
    assert harness.models.calls_for("test_writer") == 0
    assert harness.models.calls_for("implementer") == 0


def test_a_task_loop_that_escalates_runs_the_growth_loop_it_asked_for(checkout: Path) -> None:
    harness = _harness(
        checkout,
        {
            **GROWTH_SCRIPT,
            "triage": [TRIAGE_TASK, TRIAGE_TASK],
            "planner": [PLAN_WITH_GAP, GROWTH_PLAN, TASK_PLAN],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT, REVIEW_ACCEPT],
        },
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert [iteration.outcome for iteration in result.record.iterations] == [
        "rejected",
        "accepted",
        "accepted",
    ]
    assert result.record.iterations[1].commit_sha is not None
    assert harness.models.calls_for("planner") == 3
    assert harness.models.calls_for("triage") == 2
    assert result.record.mode is Mode.TASK
    assert result.record.outcome == "accepted"


NOT_RED = RedResult(red=False, exit_code=0, output="1 passed")


def test_a_red_check_that_is_not_red_rejects_the_iteration_and_resets_the_tree(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "librarian": [LESSON_SUMMARY]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        red=NOT_RED,
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == "no red: 1 passed"
    assert iteration.test_report == TEST_REPORT
    assert harness.models.calls_for("implementer") == 0
    assert not (checkout / GLOSSARY_TEST_PATH).exists()
    assert Repo(checkout).is_clean()


@pytest.mark.parametrize(
    "red",
    [
        RedResult(red=False, exit_code=5, output="no tests ran"),
        RedResult(red=False, exit_code=2, output="SyntaxError: invalid syntax"),
    ],
    ids=["nothing-collected", "syntax-error"],
)
def test_a_red_check_the_checks_module_classified_as_not_red_is_trusted_whatever_its_exit_code(
    checkout: Path, red: RedResult
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "librarian": [LESSON_SUMMARY]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        red=red,
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == f"no red: {red.output}"
    assert harness.models.calls_for("implementer") == 0
    assert Repo(checkout).is_clean()


def test_a_plan_with_a_python_target_and_no_tests_is_refused_before_the_test_writer_runs(
    checkout: Path,
) -> None:
    dataset = checkout / "evals" / "answers.yaml"
    before = dataset.read_text(encoding="utf-8")
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [GROWTH_PLAN.model_copy(update={"tests": []})]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == "no tests"
    assert harness.models.calls_for("test_writer") == 0
    assert harness.models.calls_for("implementer") == 0
    assert dataset.read_text(encoding="utf-8") == before
    assert Repo(checkout).is_clean()


WORKER_PROMPT_PATH = "src/recursive_application/organism/prompts/worker.md"
PROMPT_SOURCE = (
    "Phase: Act. You produce the Task's output as a `WorkerOutput`.\n\n"
    "The Gate is the deterministic quality check an Iteration must pass.\n"
)
PROMPT_PLAN = GROWTH_PLAN.model_copy(update={"target_paths": [WORKER_PROMPT_PATH], "tests": []})
PROMPT_REPORT = CodeReport(
    summary="The Worker's prompt now says what the Gate is.", changed_files=[WORKER_PROMPT_PATH]
)
PROMPT_SCRIPT: Mapping[str, Sequence[Any]] = {
    "planner": [PROMPT_PLAN],
    "implementer": [PROMPT_REPORT],
    "reviewer": [REVIEW_ACCEPT],
    "librarian": [LIBRARIAN_SUMMARY],
}


def _prompt_effects(
    checkout: Path, path: str = WORKER_PROMPT_PATH
) -> dict[str, Callable[[], None]]:
    """What a scripted Implementer that edits a prompt leaves behind in the checkout."""
    return {"implementer": lambda: _write_file(checkout / path, PROMPT_SOURCE)}


def test_a_plan_without_python_targets_skips_the_test_writer_and_the_red_check(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout, PROMPT_SCRIPT, checks=CHECKS_PASSED, on_call=_prompt_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert harness.models.calls_for("test_writer") == 0
    assert harness.events == ["planner", "implementer", "checks", "evals", "reviewer", "librarian"]
    assert harness.red_files == []


def _seed_latest_report(checkout: Path, *cases: CaseResult) -> None:
    """Persist a report as the latest one, so the Gate and the red have a baseline to read."""
    ReportStore(checkout / RA_DIRNAME / EVALS_DIRNAME).save(
        EvalReport(
            created_at=START,
            run_id="20260901-000000-abcdef",
            datasets=sorted({case.dataset for case in cases}),
            cases=list(cases),
        )
    )


def test_a_non_python_plan_whose_target_case_already_passes_has_no_red_and_is_rejected_before_act(
    checkout: Path,
) -> None:
    _seed_latest_report(
        checkout, CaseResult(dataset="answers", name="answers-4-what-is-the-gate", passed=True)
    )
    harness = _harness(
        checkout,
        {**PROMPT_SCRIPT, "librarian": [LESSON_SUMMARY]},
        checks=CHECKS_PASSED,
        on_call=_prompt_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == f"no red: {TARGET_KEY}"
    assert harness.models.calls_for("implementer") == 0
    assert harness.eval_requests == []
    assert Repo(checkout).is_clean()


def _committed_paths(root: Path) -> list[str]:
    """The paths HEAD's commit touches, read from git's own stat of it."""
    stat = _git_output(root, "show", "--stat", "--format=", "HEAD")
    return [line.split("|")[0].strip() for line in stat.splitlines() if "|" in line]


def test_a_growth_iteration_the_gate_rejects_is_undone_and_recorded_as_a_lesson(
    checkout: Path,
) -> None:
    repo = Repo(checkout)
    previous = repo.head_sha()
    log = checkout / "wiki" / "log.md"
    harness = _harness(
        checkout,
        REJECTED_SCRIPT,
        checks=CHECKS_TY_FAILED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    run_id = result.record.run_id
    reason = f"ty: {TY_OUTPUT}"
    assert result.record.iterations[0].outcome == "rejected"
    assert _git_output(checkout, "rev-parse", "HEAD~1") == previous
    assert _git_output(checkout, "log", "-1", "--format=%s") == f"ra: lesson from {run_id}"
    touched = _committed_paths(checkout)
    assert touched and all(path.startswith("wiki/") for path in touched)
    assert not (checkout / GLOSSARY_PATH).exists()
    assert not (checkout / GLOSSARY_TEST_PATH).exists()
    assert repo.is_clean()
    assert (harness.ra_dir / RUNS_DIRNAME / f"{run_id}.json").exists()
    prompts = harness.models.prompts_for("librarian")
    assert len(prompts) == 1
    assert prompts[0].startswith("Rejected: Teach the Worker what the Gate is")
    assert reason in prompts[0]
    assert run_id in prompts[0]
    assert GROWTH_PLAN.change in prompts[0]
    assert "Phase: learn" in harness.models.requests["librarian"][0].instructions
    assert (
        log.read_text(encoding="utf-8")
        .splitlines()[-1]
        .endswith(f"rejected Teach the Worker what the Gate is: {reason}")
    )


def test_the_iteration_after_a_rejection_starts_on_a_clean_tree_and_its_planner_is_told_why(
    checkout: Path,
) -> None:
    trees_at_planning: list[list[str]] = []
    harness = _harness(
        checkout,
        {
            "planner": [GROWTH_PLAN] * 2,
            "test_writer": [TEST_REPORT] * 2,
            "implementer": [CODE_REPORT] * 2,
            "librarian": [LESSON_SUMMARY] * 2,
        },
        checks=CHECKS_TY_FAILED,
        on_call={
            **_coder_effects(checkout),
            "planner": lambda: trees_at_planning.append(Repo(checkout).changed_paths()),
        },
        settings=_settings(ra_max_iterations=2, ra_no_progress_iterations=5),
        usage=RequestUsage(input_tokens=10, output_tokens=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert [iteration.outcome for iteration in result.record.iterations] == ["rejected", "rejected"]
    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"
    assert trees_at_planning == [[], []]
    second_prompt = harness.models.prompts_for("planner")[1]
    assert f"Previous attempt failed because: ty: {TY_OUTPUT}" in second_prompt
    assert harness.models.calls_for("librarian") == 2
    assert result.record.iterations[0].usage.requests == 4
    assert _git_output(checkout, "log", "--format=%s", "-3").splitlines() == [
        f"ra: lesson from {result.record.run_id}",
        f"ra: lesson from {result.record.run_id}",
        "lay the checkout out",
    ]


def test_a_no_red_rejection_is_recorded_as_a_lesson_like_a_gate_rejection(checkout: Path) -> None:
    repo = Repo(checkout)
    previous = repo.head_sha()
    harness = _harness(
        checkout,
        REJECTED_SCRIPT,
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        red=NOT_RED,
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    run_id = result.record.run_id
    assert result.record.iterations[0].reason == "no red: 1 passed"
    prompts = harness.models.prompts_for("librarian")
    assert len(prompts) == 1
    assert prompts[0].startswith("Rejected: Teach the Worker what the Gate is")
    assert "no red: 1 passed" in prompts[0]
    assert _git_output(checkout, "rev-parse", "HEAD~1") == previous
    assert _git_output(checkout, "log", "-1", "--format=%s") == f"ra: lesson from {run_id}"
    assert (
        (checkout / "wiki" / "log.md")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
        .endswith("rejected Teach the Worker what the Gate is: no red: 1 passed")
    )
    assert result.record.iterations[0].usage.requests == 3


SPECIALIST = RegistryEntry(
    name="glossarist",
    agent=Agent[None, Any](name="glossarist", output_type=CodeReport, retries=2),
    tier="primary",
    phases=("act",),
    tools=ToolConfig(
        write_globs=["src/recursive_application/organism/**"], shell_commands=["pytest"]
    ),
    guides=(CODING_GUIDE,),
    # The harness reads prompts from the real checkout, where a test may add no file, so the
    # Specialist borrows the Implementer's prompt; its own name is what the Loop dispatches on.
    prompt_path="src/recursive_application/organism/prompts/implementer.md",
    dataset="evals/answers.yaml",
)
SPECIALIST_PLAN = GROWTH_PLAN.model_copy(update={"actor": "glossarist"})


def _specialist_registry() -> Registry:
    """The real Organism registry plus the glossarist, held to the Kernel's contract."""
    return validate_registry((*load_registry().entries, SPECIALIST), REPO_ROOT)


def test_a_plan_naming_a_registered_specialist_invokes_it_in_the_act_slot_and_nowhere_else(
    checkout: Path,
) -> None:
    effects = _coder_effects(checkout)
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [SPECIALIST_PLAN], "glossarist": [CODE_REPORT]},
        checks=CHECKS_PASSED,
        on_call={"test_writer": effects["test_writer"], "glossarist": effects["implementer"]},
        registry=_specialist_registry(),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert harness.models.calls_for("glossarist") == 1
    assert harness.models.calls_for("implementer") == 0
    instructions = harness.models.requests["glossarist"][0].instructions
    assert "Phase: act" in instructions
    assert "Role: glossarist" in instructions
    assert harness.events == [
        "planner",
        "test_writer",
        "red check",
        "glossarist",
        "checks",
        "evals",
        "reviewer",
        "librarian",
    ]
    assert result.record.iterations[0].code_report == CODE_REPORT


def test_a_specialist_of_the_other_slots_contract_is_refused_as_ineligible_before_act(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN.model_copy(update={"actor": "glossarist"})],
            "glossarist": [CODE_REPORT],
            "worker": [WORKER_NOTE],
        },
        settings=_settings(ra_max_iterations=1),
        registry=_specialist_registry(),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == "ineligible actor: glossarist"
    assert harness.models.calls_for("glossarist") == 0
    assert harness.models.calls_for("worker") == 0
    assert harness.eval_requests == []


def test_a_required_role_that_is_not_the_modes_default_actor_is_refused_as_ineligible(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [GROWTH_PLAN.model_copy(update={"actor": "planner"})]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == "ineligible actor: planner"
    assert harness.models.calls_for("planner") == 1
    assert harness.models.calls_for("test_writer") == 0
    assert harness.models.calls_for("implementer") == 0
    assert Repo(checkout).is_clean()


PLANNER_PROMPT_PATH = "src/recursive_application/organism/prompts/planner.md"


@pytest.mark.parametrize(
    ("prompt_path", "datasets"),
    [
        (WORKER_PROMPT_PATH, ["answers", "triage"]),
        (PLANNER_PROMPT_PATH, ["answers", "triage", "planner"]),
    ],
    ids=["worker-prompt", "planner-prompt"],
)
def test_the_guard_subset_is_the_target_dataset_triage_answers_and_the_affected_agents_datasets(
    checkout: Path, prompt_path: str, datasets: list[str]
) -> None:
    plan = PROMPT_PLAN.model_copy(update={"target_paths": [prompt_path]})
    report = CodeReport(
        summary="The prompt now says what the Gate is.", changed_files=[prompt_path]
    )
    harness = _harness(
        checkout,
        {**PROMPT_SCRIPT, "planner": [plan], "implementer": [report]},
        checks=CHECKS_PASSED,
        on_call=_prompt_effects(checkout, prompt_path),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert len(harness.eval_requests) == 1
    assert harness.eval_requests[0].datasets == datasets
    assert harness.eval_requests[0].targets == [TARGET_KEY]


TRIAGE_CASE = "triage-1-answer-from-current-capabilities"


def _scripted_reports(*verdicts: Mapping[str, bool]) -> Callable[[EvalRequest], EvalReport]:
    """An evals adapter answering each request in turn with a report over the given case keys."""
    remaining = list(verdicts)

    def run(request: EvalRequest) -> EvalReport:
        cases = [
            CaseResult(
                dataset=key.rpartition("/")[0],
                name=key.rpartition("/")[2],
                passed=passed,
                reasons=[] if passed else [JUDGE_REASON],
            )
            for key, passed in remaining.pop(0).items()
        ]
        return EvalReport(
            created_at=START,
            run_id=request.run_id,
            datasets=sorted({case.dataset for case in cases}),
            cases=cases,
        )

    return run


def test_a_guard_case_that_regresses_is_retried_once_and_a_passing_retry_keeps_the_gate_green(
    checkout: Path,
) -> None:
    _seed_latest_report(checkout, CaseResult(dataset="triage", name=TRIAGE_CASE, passed=True))
    harness = _harness(
        checkout,
        PROMPT_SCRIPT,
        checks=CHECKS_PASSED,
        on_call=_prompt_effects(checkout),
        evals=_scripted_reports(
            {TARGET_KEY: True, f"triage/{TRIAGE_CASE}": False},
            {f"triage/{TRIAGE_CASE}": True},
        ),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert len(harness.eval_requests) == 2
    assert harness.eval_requests[0].datasets == ["answers", "triage"]
    assert harness.eval_requests[1].datasets == ["triage"]
    assert harness.eval_requests[1].targets == [f"triage/{TRIAGE_CASE}"]
    gate = result.record.iterations[0].gate
    assert gate is not None
    assert [check.status for check in gate.checks if check.name == "evals"] == ["passed"]


def test_a_guard_case_whose_retry_fails_too_fails_the_gate_and_the_iteration_is_a_lesson(
    checkout: Path,
) -> None:
    _seed_latest_report(checkout, CaseResult(dataset="triage", name=TRIAGE_CASE, passed=True))
    harness = _harness(
        checkout,
        {**PROMPT_SCRIPT, "librarian": [LESSON_SUMMARY]},
        checks=CHECKS_PASSED,
        on_call=_prompt_effects(checkout),
        evals=_scripted_reports(
            {TARGET_KEY: True, f"triage/{TRIAGE_CASE}": False},
            {f"triage/{TRIAGE_CASE}": False},
        ),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert len(harness.eval_requests) == 2
    assert iteration.gate is not None
    assert [
        (check.status, check.excerpt) for check in iteration.gate.checks if check.name == "evals"
    ] == [("failed", f"triage/{TRIAGE_CASE}")]
    assert harness.models.calls_for("reviewer") == 0
    prompt = harness.models.prompts_for("librarian")[0]
    assert prompt.startswith("Rejected:")
    assert f"evals: triage/{TRIAGE_CASE}" in prompt
    assert _git_output(checkout, "log", "-1", "--format=%s") == (
        f"ra: lesson from {result.record.run_id}"
    )
    assert not (checkout / WORKER_PROMPT_PATH).exists()
    assert Repo(checkout).is_clean()


@pytest.mark.parametrize(
    "path",
    [
        "docs/coding-guide.md",
        "evals/frontier/text-analysis.yaml",
        "src/recursive_application/kernel/policy.py",
    ],
    ids=["coding-guide", "frontier-file", "policy-ceiling"],
)
def test_a_plan_targeting_a_path_the_organism_may_not_change_becomes_a_policy_finding(
    checkout: Path, path: str
) -> None:
    plan = GROWTH_PLAN.model_copy(update={"target_paths": [path]})
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [plan]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    run_id = result.record.run_id
    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == f"policy: {path}"
    assert harness.models.calls_for("test_writer") == 0
    assert harness.models.calls_for("implementer") == 0
    assert harness.approvals == []
    assert Repo(checkout).is_clean()
    findings = stored_findings(FindingStore(harness.ra_dir / FINDINGS_FILENAME))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.id == f"policy:{run_id}:1"
    assert finding.source == "policy"
    assert finding.severity == "low"
    assert finding.summary == (
        f"Plan 'Teach the Worker what the Gate is' targets {path}, "
        "which the Organism may not change"
    )
    assert finding.details == (
        f"For the human: only you may change {path}. The Plan wanted:\n"
        "Add a glossary module and the answers case that proves it."
    )
    sensed = collect(
        ra_dir=harness.ra_dir,
        wiki=Wiki(checkout / "wiki"),
        frontier_dir=frontier_dir(checkout),
        budget_usd=Decimal("5"),
    )
    assert finding.id in [sensed_finding.id for sensed_finding in sensed]


FRONTIER_LADDER = "evals/frontier/text-analysis.yaml"


def test_a_plan_whose_dataset_is_a_frontier_ladder_is_refused_as_policy_and_the_ladder_is_unchanged(
    checkout: Path,
) -> None:
    ladder = checkout / FRONTIER_LADDER
    before = ladder.read_text(encoding="utf-8")
    plan = GROWTH_PLAN.model_copy(update={"dataset": FRONTIER_LADDER})
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [plan]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == f"policy: {FRONTIER_LADDER}"
    assert ladder.read_text(encoding="utf-8") == before
    assert harness.models.calls_for("test_writer") == 0
    findings = stored_findings(FindingStore(harness.ra_dir / FINDINGS_FILENAME))
    assert [finding.source for finding in findings] == ["policy"]
    assert Repo(checkout).is_clean()


@pytest.mark.parametrize(
    "spell",
    [lambda root: f"./{FRONTIER_LADDER}", lambda root: str(root / FRONTIER_LADDER)],
    ids=["dot-relative", "absolute"],
)
def test_a_frontier_target_is_refused_however_its_path_is_spelled(
    checkout: Path, spell: Callable[[Path], str]
) -> None:
    path = spell(checkout)
    plan = GROWTH_PLAN.model_copy(update={"target_paths": [path]})
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "planner": [plan]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    iteration = result.record.iterations[0]
    assert iteration.outcome == "rejected"
    assert iteration.reason == f"policy: {path}"
    assert harness.models.calls_for("test_writer") == 0


def test_a_growth_run_that_crashes_after_the_append_leaves_the_tree_at_the_commit_it_started_from(
    checkout: Path,
) -> None:
    repo = Repo(checkout)
    previous = repo.head_sha()
    dataset = checkout / "evals" / "answers.yaml"
    before = dataset.read_text(encoding="utf-8")
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "implementer": [RuntimeError("the model is down")]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "error"
    assert result.exit_code == 3
    assert repo.head_sha() == previous
    assert repo.is_clean()
    assert dataset.read_text(encoding="utf-8") == before
    assert not (checkout / GLOSSARY_TEST_PATH).exists()
    assert not (harness.ra_dir / "lock").exists()


def test_a_librarian_that_crashes_while_recording_an_improvement_leaves_one_iteration_behind(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "librarian": [RuntimeError("the model is down")]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "error"
    assert [iteration.number for iteration in result.record.iterations] == [1]
    iteration = result.record.iterations[0]
    assert iteration.outcome == "error"
    assert iteration.reason == "the model is down"
    assert iteration.plan == GROWTH_PLAN
    assert iteration.usage.requests == 4
    assert _git_output(checkout, "log", "-1", "--format=%s") == f"ra: {GROWTH_PLAN.title}"
    assert Repo(checkout).is_clean()


def _persisting_evals(checkout: Path) -> Callable[[EvalRequest], EvalReport]:
    """An evals adapter that, like the real runner, saves its report as the latest one."""
    store = ReportStore(checkout / RA_DIRNAME / EVALS_DIRNAME)

    def run(request: EvalRequest) -> EvalReport:
        report = _report(request, passed=True)
        store.save(report)
        return report

    return run


def test_a_growth_gate_compares_against_the_report_that_was_latest_before_its_own_eval_run(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        GROWTH_SCRIPT,
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        evals=_persisting_evals(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, GROWTH_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert result.record.iterations[0].commit_sha is not None


def test_an_answer_gate_compares_against_the_report_that_was_latest_before_its_own_eval_run(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {"triage": [TRIAGE_ANSWER], "worker": [WORKER_ANSWER]},
        evals=_persisting_evals(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.record.outcome == "accepted"
    assert result.exit_code == 0


def _added_and_missing(sha: str | None) -> str:
    """What an `ra ask` run that needs Growth twice prints: the Improvement, then the gap."""
    return (
        f"Added: Teach the Worker what the Gate is (commit {sha})\n\n"
        f"Still missing:\n- {TOOL_GAP.description}"
    )


def _recorded_gaps(harness: Harness) -> list[tuple[str, str]]:
    """The findings the run wrote for the next one, as (id, summary) pairs."""
    findings = stored_findings(FindingStore(harness.ra_dir / FINDINGS_FILENAME))
    return [(finding.id, finding.summary) for finding in findings]


TRIAGE_GROWTH_FOR_GAP = TriageDecision(
    mode=Mode.GROWTH,
    reasoning="The note needs the git history, which no agent can read yet.",
    reflection=Reflection(required_capabilities=["cite the git history"], gaps=[TOOL_GAP]),
)
ONE_REQUEST = RequestUsage(input_tokens=10, output_tokens=1)


def test_after_an_improvement_in_ask_triage_runs_again_and_the_task_loop_it_picks_ends_the_run(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            **GROWTH_SCRIPT,
            "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_TASK],
            "planner": [GROWTH_PLAN.model_copy(update={"gaps": [HUMAN_GAP]}), TASK_PLAN],
            "worker": [WORKER_NOTE],
            "reviewer": [REVIEW_ACCEPT, REVIEW_ACCEPT],
        },
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        usage=ONE_REQUEST,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert result.exit_code == 0
    assert result.record.mode is Mode.TASK
    assert harness.models.calls_for("triage") == 2
    first_triage, second_triage = harness.models.prompts_for("triage")
    assert second_triage.startswith(f"Task: {TASK_REQUEST}\n\nOpen Sensor Findings:\n")
    recorded_gap = f"reflection:{result.record.run_id}:1"
    assert recorded_gap not in first_triage
    assert recorded_gap in second_triage
    first, second = result.record.iterations
    assert first.commit_sha is not None
    assert second.number == 2
    assert second.outcome == "accepted"
    assert second.output_path == f".ra/{TASKS_DIRNAME}/{result.record.run_id}/output.md"
    assert result.output == RELEASE_NOTE
    assert [first.usage.requests, second.usage.requests] == [6, 4]
    assert "Iteration: 2 of 5" in harness.models.requests["worker"][0].instructions
    assert not (harness.ra_dir / LOCK_FILENAME).exists()
    assert Repo(checkout).is_clean()


def test_a_second_growth_need_after_the_improvement_stops_the_run_naming_the_added_and_the_missing(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_GROWTH_FOR_GAP]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        usage=ONE_REQUEST,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "rejected"
    assert result.exit_code == 1
    assert result.reason == "growth needed twice"
    first, second = result.record.iterations
    assert result.output == _added_and_missing(first.commit_sha)
    assert second.number == 2
    assert second.outcome == "rejected"
    assert second.reason == "growth needed twice"
    assert second.plan is None
    assert second.usage.requests == 1
    assert harness.models.calls_for("planner") == 1
    assert result.record.mode is Mode.GROWTH
    assert not (harness.ra_dir / LOCK_FILENAME).exists()
    assert RunStore(harness.ra_dir / RUNS_DIRNAME).load(result.record.run_id).outcome == "rejected"
    assert _recorded_gaps(harness) == [
        (f"reflection:{result.record.run_id}:1", TOOL_GAP.description)
    ]


def test_an_escalation_inside_the_continued_task_loop_is_growth_needed_twice_as_well(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            **GROWTH_SCRIPT,
            "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_TASK],
            "planner": [GROWTH_PLAN, PLAN_WITH_GAP],
            "worker": [WORKER_NOTE],
        },
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        usage=ONE_REQUEST,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions())

    assert result.record.outcome == "rejected"
    assert result.exit_code == 1
    assert result.reason == "growth needed twice"
    first, second = result.record.iterations
    assert result.output == _added_and_missing(first.commit_sha)
    assert second.outcome == "rejected"
    assert second.reason == "growth needed twice"
    assert second.plan == PLAN_WITH_GAP
    assert second.usage.requests == 2
    assert harness.models.calls_for("worker") == 0
    assert len(harness.approvals) == 1
    assert harness.approvals[0].startswith("title: Teach the Worker what the Gate is")
    assert result.record.mode is Mode.GROWTH
    assert Repo(checkout).is_clean()
    assert _recorded_gaps(harness) == [
        (f"reflection:{result.record.run_id}:1", TOOL_GAP.description)
    ]


def test_a_clarification_gap_from_the_second_triage_ends_the_run_with_its_questions(
    checkout: Path,
) -> None:
    clock = Clock()
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_CLARIFICATION]},
        checks=CHECKS_PASSED,
        on_call={**_coder_effects(checkout), "librarian": lambda: clock.advance(minutes=1)},
        usage=ONE_REQUEST,
        clock=clock,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.questions == ["Which repository do you mean?", "Which branch?"]
    assert result.reason == "clarification"
    assert result.exit_code == 2
    assert result.record.outcome == "aborted"
    first, second = result.record.iterations
    assert first.commit_sha is not None
    assert second.number == 2
    assert second.outcome == "aborted"
    assert second.plan is None
    assert second.usage.requests == 1
    assert (first.started_at, second.started_at) == (START, START + timedelta(minutes=1))
    assert harness.models.calls_for("planner") == 1


FIRST_FINDING = SensorFinding(
    id="reflection:20260904-090000-aaaaaa:1",
    source="reflection",
    summary="The Worker cannot say what the Gate is",
    details="kind: knowledge\nhow_to_acquire: Add a glossary entry for the Gate",
    severity="high",
)
SECOND_FINDING = SensorFinding(
    id="reflection:20260904-100000-bbbbbb:1",
    source="reflection",
    summary="The Worker cannot say what a Sensor is",
    details="kind: knowledge\nhow_to_acquire: Add a glossary entry for the Sensor",
    severity="high",
)
SECOND_GROWTH_PLAN = GROWTH_PLAN.model_copy(update={"title": "Teach the Worker what a Sensor is"})
IMPROVE_SCRIPT: Mapping[str, Sequence[Any]] = {
    "planner": [GROWTH_PLAN, SECOND_GROWTH_PLAN],
    "test_writer": [TEST_REPORT, TEST_REPORT],
    "implementer": [CODE_REPORT, CODE_REPORT],
    "reviewer": [REVIEW_ACCEPT, REVIEW_ACCEPT],
    "librarian": [LIBRARIAN_SUMMARY, LIBRARIAN_SUMMARY],
}


def _seed_findings(checkout: Path, *findings: SensorFinding) -> None:
    """Store findings dated before the run, the first the oldest, so `high` ones outrank the
    checkout's frontier findings and drop out once a run names them as addressed."""
    store = FindingStore(checkout / RA_DIRNAME / FINDINGS_FILENAME)
    for position, finding in enumerate(findings):
        store.append(finding, START - timedelta(days=len(findings) - position))


def _improving_effects(checkout: Path) -> dict[str, Callable[[], None]]:
    """Scripted coders whose every Improvement changes the glossary, so each has a diff."""
    improvements = itertools.count(1)

    def implement() -> None:
        _write_file(
            checkout / GLOSSARY_PATH, f"{GLOSSARY_SOURCE}\n\nIMPROVEMENTS = {next(improvements)}\n"
        )

    return {**_coder_effects(checkout), "implementer": implement}


def test_improve_takes_the_top_finding_then_the_next_and_ends_accepted_at_the_iteration_limit(
    checkout: Path,
) -> None:
    _seed_findings(checkout, FIRST_FINDING, SECOND_FINDING)
    harness = _harness(
        checkout, IMPROVE_SCRIPT, checks=CHECKS_PASSED, on_call=_improving_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, None, LoopOptions(yes=True, max_iterations=2))

    assert result.record.outcome == "accepted"
    assert result.reason == "iteration limit"
    assert result.exit_code == 0
    assert [iteration.outcome for iteration in result.record.iterations] == [
        "accepted",
        "accepted",
    ]
    assert all(iteration.commit_sha is not None for iteration in result.record.iterations)
    addressed = [FIRST_FINDING.id, SECOND_FINDING.id]
    assert result.record.findings_addressed == addressed
    stored = RunStore(harness.ra_dir / RUNS_DIRNAME).load(result.record.run_id)
    assert stored.findings_addressed == addressed
    first, second = harness.models.prompts_for("planner")
    assert first.startswith(
        f"Finding: {FIRST_FINDING.id}\n{FIRST_FINDING.summary}\n{FIRST_FINDING.details}\n\n"
        f"Open Sensor Findings:\n"
        f"- [high] {FIRST_FINDING.id}: {FIRST_FINDING.summary}\n"
        f"- [high] {SECOND_FINDING.id}: {SECOND_FINDING.summary}\n"
        f"- [medium] evals:frontier/"
    )
    assert second.startswith(
        f"Finding: {SECOND_FINDING.id}\n{SECOND_FINDING.summary}\n{SECOND_FINDING.details}\n\n"
        f"Open Sensor Findings:\n"
        f"- [high] {SECOND_FINDING.id}: {SECOND_FINDING.summary}\n"
        f"- [medium] evals:frontier/"
    )
    assert FIRST_FINDING.id not in second
    assert harness.models.calls_for("triage") == 0
    log = Repo(checkout).log(n=5)
    assert "ra: Teach the Worker what the Gate is" in log
    assert "ra: Teach the Worker what a Sensor is" in log
    assert Repo(checkout).is_clean()


def test_improve_with_a_goal_hands_the_planner_the_goal_and_the_findings_and_singles_out_none(
    checkout: Path,
) -> None:
    _seed_findings(checkout, FIRST_FINDING)
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(
        Mode.GROWTH, None, LoopOptions(yes=True, max_iterations=1, goal="reduce cost")
    )

    prompt = harness.models.prompts_for("planner")[0]
    assert prompt.startswith(
        "Goal: reduce cost\n\nOpen Sensor Findings:\n"
        f"- [high] {FIRST_FINDING.id}: {FIRST_FINDING.summary}\n"
        "- [medium] evals:frontier/"
    )
    assert "Finding:" not in prompt
    assert result.record.findings_addressed == []
    assert result.record.outcome == "accepted"
    assert result.reason == "iteration limit"
    assert result.exit_code == 0
    assert [iteration.commit_sha is not None for iteration in result.record.iterations] == [True]


def _seed_green_frontier(checkout: Path) -> None:
    """Persist a latest report in which every Frontier Case passes, so Sense has no eval finding."""
    _seed_latest_report(
        checkout,
        *(
            CaseResult(dataset=f"frontier/{path.stem}", name=case.name, passed=True)
            for path in sorted(frontier_dir(checkout).glob("*.yaml"))
            for case in validate_frontier(path)
        ),
    )


def test_improve_ends_accepted_with_no_open_findings_once_the_last_finding_is_addressed(
    checkout: Path,
) -> None:
    _seed_green_frontier(checkout)
    _seed_findings(checkout, FIRST_FINDING)
    harness = _harness(
        checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED, on_call=_coder_effects(checkout)
    )

    result = harness.runner.run(Mode.GROWTH, None, LoopOptions(yes=True))

    assert result.record.outcome == "accepted"
    assert result.reason == "no open findings"
    assert result.exit_code == 0
    assert [iteration.outcome for iteration in result.record.iterations] == ["accepted"]
    assert result.record.findings_addressed == [FIRST_FINDING.id]
    assert harness.models.calls_for("planner") == 1
    assert not (harness.ra_dir / LOCK_FILENAME).exists()


def test_improve_with_nothing_open_before_its_first_iteration_is_aborted_as_no_open_findings(
    checkout: Path,
) -> None:
    _seed_green_frontier(checkout)
    harness = _harness(checkout, GROWTH_SCRIPT, checks=CHECKS_PASSED)

    result = harness.runner.run(Mode.GROWTH, None, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "no open findings"
    assert result.exit_code == 2
    assert result.record.iterations == []
    assert harness.models.calls_for("planner") == 0
    assert not (harness.ra_dir / LOCK_FILENAME).exists()


def test_an_improve_run_that_accepted_no_improvement_is_aborted_at_the_iteration_limit(
    checkout: Path,
) -> None:
    _seed_findings(checkout, FIRST_FINDING)
    harness = _harness(
        checkout,
        REJECTED_SCRIPT,
        checks=CHECKS_TY_FAILED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(Mode.GROWTH, None, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"
    assert result.exit_code == 2
    assert [iteration.outcome for iteration in result.record.iterations] == ["rejected"]
    assert result.record.findings_addressed == []
    assert harness.models.prompts_for("planner")[0].startswith(f"Finding: {FIRST_FINDING.id}\n")


def test_an_improvement_at_the_iteration_limit_ends_the_ask_run_before_a_second_triage(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_TASK]},
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=1),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"
    assert result.exit_code == 2
    assert harness.models.calls_for("triage") == 1
    assert [iteration.outcome for iteration in result.record.iterations] == ["accepted"]
    assert result.record.iterations[0].commit_sha is not None
    assert result.output is None


def test_an_improvement_that_spends_the_wall_time_ends_the_ask_run_before_a_second_triage(
    checkout: Path,
) -> None:
    clock = Clock()
    harness = _harness(
        checkout,
        {**GROWTH_SCRIPT, "triage": [TRIAGE_GROWTH_FOR_GAP, TRIAGE_TASK]},
        checks=CHECKS_PASSED,
        on_call={**_coder_effects(checkout), "librarian": lambda: clock.advance(minutes=31)},
        clock=clock,
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert result.record.outcome == "aborted"
    assert result.reason == "wall time"
    assert harness.models.calls_for("triage") == 1
    assert result.record.iterations[0].commit_sha is not None


def test_a_task_draft_from_before_the_improvement_is_not_the_output_of_a_stopped_ask_run(
    checkout: Path,
) -> None:
    harness = _harness(
        checkout,
        {
            **GROWTH_SCRIPT,
            "triage": [TRIAGE_TASK],
            "planner": [TASK_PLAN, GROWTH_PLAN],
            "worker": [WORKER_OUTPUT_WITH_GAP],
        },
        checks=CHECKS_PASSED,
        on_call=_coder_effects(checkout),
        settings=_settings(ra_max_iterations=2),
    )

    result = harness.runner.run(None, TASK_REQUEST, LoopOptions(yes=True))

    assert [iteration.outcome for iteration in result.record.iterations] == [
        "rejected",
        "accepted",
    ]
    assert result.record.outcome == "aborted"
    assert result.reason == "iteration limit"
    assert result.output is None
    assert harness.models.calls_for("triage") == 1


def test_an_improve_run_whose_second_plan_is_refused_is_aborted_with_its_improvement_standing(
    checkout: Path,
) -> None:
    _seed_findings(checkout, FIRST_FINDING, SECOND_FINDING)
    harness = _harness(
        checkout,
        {
            "planner": [
                GROWTH_PLAN,
                GROWTH_PLAN.model_copy(update={"title": "Teach the Worker what a Sensor is"}),
            ],
            "test_writer": [TEST_REPORT] * 2,
            "implementer": [CODE_REPORT] * 2,
            "reviewer": [REVIEW_ACCEPT] * 2,
            "librarian": [LIBRARIAN_SUMMARY] * 2,
        },
        checks=CHECKS_PASSED,
        on_call=_improving_effects(checkout),
        approves=[True, False],
        settings=_settings(ra_max_iterations=3),
    )

    result = harness.runner.run(Mode.GROWTH, None, LoopOptions())

    assert result.record.outcome == "aborted"
    assert result.reason == "approval refused"
    assert result.exit_code == 2
    assert [iteration.outcome for iteration in result.record.iterations] == [
        "accepted",
        "aborted",
    ]
    assert result.record.iterations[0].commit_sha is not None
    assert result.record.findings_addressed == [FIRST_FINDING.id]
    assert Repo(checkout).is_clean()
