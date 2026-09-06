"""The Loop runner in Answer and Task Modes, through `kernel.loop`.

The runner is the primary seam of the Loop: one `run(mode, task, options)` call drives Sense,
Decide, Act, Gate, and Learn over injected adapters, so every test here scripts the models,
the evals runner, the clock, and the Trace Store and then reads the Run Record, the files the
run wrote, and the exit code. Nothing reaches a model, the network, or the real checkout.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic_ai.usage import RequestUsage

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.bundle import frontier_dir
from recursive_application.kernel.checks import RedResult
from recursive_application.kernel.evals import CaseResult, EvalReport
from recursive_application.kernel.git import Repo
from recursive_application.kernel.loop import (
    ANSWER_RUBRIC,
    CASES_FILENAME,
    EvalRequest,
    LoopOptions,
    LoopRunner,
    Runners,
    estimated_cost,
)
from recursive_application.kernel.paths import (
    RA_DIRNAME,
    REPO_ROOT,
    RUNS_DIRNAME,
    TASKS_DIRNAME,
    TRACES_DIRNAME,
)
from recursive_application.kernel.records import (
    CapabilityGap,
    EvalCase,
    Mode,
    Plan,
    Reflection,
    Review,
    RunStore,
    TriageDecision,
    WorkerOutput,
)
from recursive_application.kernel.registry import load_registry
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


def _harness(
    checkout: Path,
    script: Mapping[str, Sequence[Any]],
    *,
    passes: bool | Sequence[bool] = True,
    approves: bool = True,
    settings: Settings | None = None,
    breakers: BreakerStore | None = None,
    clock: Clock | None = None,
    usage: RequestUsage | None = None,
    on_evals: Callable[[EvalRequest], None] | None = None,
) -> Harness:
    """A `LoopRunner` over the temporary checkout with every adapter replaced."""
    ra_dir = checkout / RA_DIRNAME
    settings = settings if settings is not None else _settings()
    breakers = breakers if breakers is not None else BreakerStore(ra_dir / "breakers.json")
    models = scripted_models(script, usage=usage)
    clock = clock if clock is not None else Clock()
    harness_requests: list[EvalRequest] = []
    harness_approvals: list[str] = []
    verdicts = [passes] if isinstance(passes, bool) else list(passes)

    def run_evals(request: EvalRequest) -> EvalReport:
        harness_requests.append(request)
        if on_evals is not None:
            on_evals(request)
        verdict = verdicts[min(len(harness_requests), len(verdicts)) - 1]
        return _report(request, passed=verdict)

    def approve(text: str) -> bool:
        harness_approvals.append(text)
        return approves

    def configure_tracing(run_id: str) -> Path:
        path = ra_dir / TRACES_DIRNAME / f"{run_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path

    runner = LoopRunner(
        settings=settings,
        registry=load_registry(),
        agents=AgentRunner(settings, breakers, root=REPO_ROOT, model_factory=models),
        repo=Repo(checkout),
        wiki=Wiki(checkout / "wiki"),
        root=checkout,
        ra_dir=ra_dir,
        runners=Runners(
            checks=lambda root: [],
            red_check=lambda root, files: RedResult(red=True, exit_code=1),
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


def test_a_mode_this_runner_does_not_run_yet_ends_the_run_as_an_internal_error(
    checkout: Path,
) -> None:
    harness = _harness(checkout, {"triage": [TRIAGE_GROWTH]})

    result = harness.runner.run(None, TASK, LoopOptions())

    assert result.record.mode is Mode.GROWTH
    assert result.record.outcome == "error"
    assert result.exit_code == 3
    assert result.reason is not None
    assert "growth" in result.reason
    assert harness.models.calls_for("worker") == 0


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
