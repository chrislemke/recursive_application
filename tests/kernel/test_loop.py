"""The Loop runner in Answer Mode, through `kernel.loop`.

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
    Mode,
    Reflection,
    RunStore,
    TriageDecision,
    WorkerOutput,
)
from recursive_application.kernel.registry import load_registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.sensors import FINDINGS_FILENAME, FindingStore, stored_findings
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


def _settings(**overrides: Any) -> Settings:
    """Settings with no `.env` behind them, so a run's limits are exactly the test's."""
    return Settings(_env_file=None, **overrides)


def _report(request: EvalRequest, *, passed: bool) -> EvalReport:
    """The report the evals runner returns for one Answer Iteration's Target Case."""
    dataset, _, name = request.targets[0].rpartition("/")
    return EvalReport(
        created_at=START,
        run_id=request.run_id,
        datasets=[dataset],
        cases=[
            CaseResult(
                dataset=dataset,
                name=name,
                passed=passed,
                reasons=[] if passed else [JUDGE_REASON],
            )
        ],
    )


def _harness(
    checkout: Path,
    script: Mapping[str, Sequence[Any]],
    *,
    passes: bool = True,
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

    def run_evals(request: EvalRequest) -> EvalReport:
        harness_requests.append(request)
        if on_evals is not None:
            on_evals(request)
        return _report(request, passed=passes)

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
            approve=lambda text: True,
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
