"""The agent runtime, through `kernel.runtime`.

One entry point runs any registry entry, so this is where the instruction order, the model
injection by tier, the usage limits, the breaker, and the `kernel.agent_run` span are held to
the seams document. Every run uses a `FunctionModel` or a `TestModel` handed to the runner
through `model_factory`; nothing reaches the network.
"""

from collections.abc import Callable, Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage

from recursive_application.kernel.breaker import BreakerState, BreakerStore, CircuitOpenError
from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.records import Plan, TriageDecision, WorkerOutput
from recursive_application.kernel.registry import RegistryError, load_registry
from recursive_application.kernel.runtime import AgentRunError, AgentRunner, instruction_parts
from recursive_application.kernel.settings import Settings
from recursive_application.kernel.tracing import configure_tracing, read_spans

CONSTITUTION_HEADING = "# Constitution"
CODING_GUIDE_HEADING = "# Coding Guide"
PLANNER_PROMPT_OPENING = "Phase: Decide. You produce a Plan"
WORKER_PROMPT_OPENING = "Phase: Act. You produce a WorkerOutput"
BUNDLE_HEADING = "## Loop position"
PRIMARY_MODEL = "openrouter:primary/model"
JUDGE_MODEL = "openrouter:judge/model"


def _settings(
    *,
    request_limit: int = 2,
    coder_request_limit: int = 4,
    budget_usd: Decimal = Decimal("5"),
) -> Settings:
    """Settings with no `.env` behind them, so a run's limits are exactly the test's."""
    return Settings(
        _env_file=None,
        ra_model=PRIMARY_MODEL,
        ra_judge_model=JUDGE_MODEL,
        ra_request_limit=request_limit,
        ra_coder_request_limit=coder_request_limit,
        ra_budget_usd=budget_usd,
    )


PLAN_ARGS: dict[str, Any] = {
    "title": "Add the thing",
    "evidence": "a red case",
    "cause": "the thing is missing",
    "change": "add the thing",
    "target_cases": [{"name": "case-1", "inputs": "do it"}],
    "predicted_impact": "the case turns green",
}
WORKER_ARGS: dict[str, Any] = {"content": "the answer"}
TRIAGE_ARGS: dict[str, Any] = {
    "mode": "answer",
    "reasoning": "a question about the system",
    "reflection": {"required_capabilities": ["reading"]},
}
REVIEW_ARGS: dict[str, Any] = {
    "matches_plan": True,
    "gaming_suspected": False,
    "notes": "honest",
    "verdict": "accept",
}


@pytest.fixture(scope="module")
def trace_path(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Configure tracing once for the module with no token within Logfire's reach.

    Logfire's configuration is process-global, so this follows `tests/kernel/test_tracing.py`:
    the token variable is removed here, because the conftest cleanup is function-scoped and
    runs later, and the credentials directory points at an empty temporary one so a file a
    developer left under `.logfire/` is never read.
    """
    with pytest.MonkeyPatch.context() as env:
        env.delenv("LOGFIRE_TOKEN", raising=False)
        env.setenv("LOGFIRE_CREDENTIALS_DIR", str(tmp_path_factory.mktemp("logfire")))
        yield configure_tracing(
            run_id="runtime-test-run",
            traces_dir=tmp_path_factory.mktemp("traces"),
            token=None,
            verbose=False,
        )


def _last_agent_run_span(trace_path: Path) -> dict[str, Any]:
    """The most recent `kernel.agent_run` span in the Trace Store, which is this run's."""
    return [span for span in read_spans(trace_path) if span["name"] == "kernel.agent_run"][-1]


def _always_reads_a_file(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """A model that never finishes: it asks for another `read_file` call every turn."""
    return ModelResponse(parts=[ToolCallPart("read_file", {"path": "README.md"})])


def _responder(args: dict[str, Any]) -> Callable[[list[ModelMessage], AgentInfo], ModelResponse]:
    """A model function that hands `args` back through the run's output tool."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return respond


def test_the_four_instruction_parts_are_constitution_guide_prompt_and_bundle_in_order() -> None:
    planner = load_registry().get("planner")

    parts = instruction_parts(planner, BUNDLE_HEADING, REPO_ROOT)

    first_lines = [part.splitlines()[0] for part in parts]
    assert len(parts) == 4
    assert first_lines[0] == CONSTITUTION_HEADING
    assert first_lines[1] == CODING_GUIDE_HEADING
    assert first_lines[2].startswith(PLANNER_PROMPT_OPENING)
    assert first_lines[3] == BUNDLE_HEADING


def test_an_entry_without_guides_receives_three_parts_and_no_coding_guide() -> None:
    worker = load_registry().get("worker")

    parts = instruction_parts(worker, BUNDLE_HEADING, REPO_ROOT)

    first_lines = [part.splitlines()[0] for part in parts]
    assert len(parts) == 3
    assert first_lines[0] == CONSTITUTION_HEADING
    assert first_lines[1].startswith(WORKER_PROMPT_OPENING)
    assert first_lines[2] == BUNDLE_HEADING
    assert CODING_GUIDE_HEADING not in first_lines


def test_a_run_delivers_the_four_parts_in_order_and_the_prompt_as_the_user_message(
    tmp_path: Path,
) -> None:
    seen: list[tuple[list[ModelMessage], AgentInfo]] = []

    def record(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.append((messages, info))
        return _responder(PLAN_ARGS)(messages, info)

    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(record),
    )

    result = runner.run(load_registry().get("planner"), "Plan this", bundle=BUNDLE_HEADING)

    messages, info = seen[0]
    instructions = info.instructions or ""
    positions = [
        instructions.index(marker)
        for marker in (
            CONSTITUTION_HEADING,
            CODING_GUIDE_HEADING,
            PLANNER_PROMPT_OPENING,
            BUNDLE_HEADING,
        )
    ]
    assert positions == sorted(positions)
    user_parts = [part for part in messages[0].parts if isinstance(part, UserPromptPart)]
    assert [part.content for part in user_parts] == ["Plan this"]
    assert isinstance(result.output, Plan)


def test_the_model_name_is_the_primary_for_the_worker_and_the_judge_for_the_reviewer(
    tmp_path: Path,
) -> None:
    recorded: list[str] = []
    responses = iter([WORKER_ARGS, REVIEW_ARGS])
    registry = load_registry()
    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: (
            recorded.append(name) or FunctionModel(_responder(next(responses)))
        ),
    )

    runner.run(registry.get("worker"), "Answer this", bundle="")
    runner.run(registry.get("reviewer"), "Review this", bundle="")

    assert recorded == [PRIMARY_MODEL, JUDGE_MODEL]


def test_an_entry_whose_agent_carries_a_model_is_refused_before_the_factory_is_called(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    worker = load_registry().get("worker")
    with_model = replace(
        worker,
        agent=Agent[None, WorkerOutput](
            TestModel(call_tools=[]), name="worker", output_type=WorkerOutput
        ),
    )
    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: calls.append(name) or TestModel(call_tools=[]),
    )

    with pytest.raises(RegistryError, match="model"):
        runner.run(with_model, "Answer this", bundle="")

    assert calls == []


def test_a_run_that_never_stops_raises_at_the_request_limit_with_the_usage_so_far(
    tmp_path: Path,
) -> None:
    runner = AgentRunner(
        _settings(request_limit=2),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(_always_reads_a_file),
    )

    with pytest.raises(AgentRunError) as error:
        runner.run(load_registry().get("worker"), "Answer this", bundle="")

    assert error.value.usage.requests == 2


def test_a_coding_role_runs_to_the_coder_request_limit_instead(tmp_path: Path) -> None:
    runner = AgentRunner(
        _settings(request_limit=2, coder_request_limit=4),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(_always_reads_a_file),
    )

    with pytest.raises(AgentRunError) as error:
        runner.run(load_registry().get("implementer"), "Implement this", bundle="")

    assert error.value.usage.requests == 4


def test_three_failing_runs_open_the_breaker_and_the_fourth_never_reaches_the_model(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def explode(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append("called")
        raise RuntimeError("model down")

    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json", failure_threshold=3),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(explode),
    )
    worker = load_registry().get("worker")

    for _ in range(3):
        with pytest.raises(RuntimeError, match="model down"):
            runner.run(worker, "Answer this", bundle="")

    with pytest.raises(CircuitOpenError, match="worker"):
        runner.run(worker, "Answer this", bundle="")
    assert len(calls) == 3


def test_a_completed_run_returns_the_contract_its_usage_and_a_traced_agent_run_span(
    tmp_path: Path, trace_path: Path
) -> None:
    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: TestModel(call_tools=[]),
    )

    result = runner.run(load_registry().get("triage"), "hello", bundle="")

    assert isinstance(result.output, TriageDecision)
    assert result.usage.requests == 1
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.usage.cost_usd == Decimal("0")
    span = _last_agent_run_span(trace_path)
    assert span["attributes"]["role"] == "triage"
    assert span["attributes"]["validation_retries"] == 0


def test_the_span_counts_the_retry_the_run_needed_for_a_valid_output(
    tmp_path: Path, trace_path: Path
) -> None:
    answers = iter([{"mode": "sideways"}, TRIAGE_ARGS])

    def one_bad_output_then_a_good_one(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, next(answers))])

    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(one_bad_output_then_a_good_one),
    )

    runner.run(load_registry().get("triage"), "hello", bundle="")

    assert _last_agent_run_span(trace_path)["attributes"]["validation_retries"] == 1


def test_an_agents_own_instructions_never_reach_the_model_only_the_kernels_do(
    tmp_path: Path,
) -> None:
    worker = load_registry().get("worker")
    rogue = replace(
        worker, agent=Agent(name="worker", output_type=WorkerOutput, instructions="ROGUE")
    )
    seen: list[str | None] = []

    def record(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        request = messages[-1]
        seen.append(request.instructions if isinstance(request, ModelRequest) else None)
        return _responder({"content": "fine", "gaps": []})(messages, info)

    runner = AgentRunner(
        _settings(),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(record),
    )
    runner.run(rogue, "hello", bundle=BUNDLE_HEADING)

    assert seen[0] is not None
    assert "ROGUE" not in seen[0]
    assert seen[0].startswith(CONSTITUTION_HEADING)


def test_the_budget_is_also_enforced_as_tokens_when_the_model_reports_no_price(
    tmp_path: Path,
) -> None:
    worker = load_registry().get("worker")

    def costly(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        response = _responder({"content": "fine", "gaps": []})(messages, info)
        return replace(response, usage=RequestUsage(input_tokens=700, output_tokens=700))

    runner = AgentRunner(
        _settings(budget_usd=Decimal("0.003")),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(costly),
    )

    with pytest.raises(AgentRunError) as stopped:
        runner.run(worker, "hello", bundle=BUNDLE_HEADING)

    assert stopped.value.usage.input_tokens == 700
    assert "1000" in str(stopped.value)


def test_a_usage_limit_stop_is_not_a_model_failure_and_leaves_the_breaker_closed(
    tmp_path: Path,
) -> None:
    worker = load_registry().get("worker")
    breakers = BreakerStore(tmp_path / "breakers.json")
    runner = AgentRunner(
        _settings(request_limit=1),
        breakers,
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(_always_reads_a_file),
    )

    for _ in range(3):
        with pytest.raises(AgentRunError):
            runner.run(worker, "hello", bundle=BUNDLE_HEADING)

    assert breakers.states()["worker"] == BreakerState.CLOSED


def test_a_budget_passed_for_one_call_replaces_the_settings_budget(tmp_path: Path) -> None:
    worker = load_registry().get("worker")

    def costly(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        response = _responder({"content": "fine", "gaps": []})(messages, info)
        return replace(response, usage=RequestUsage(input_tokens=700, output_tokens=700))

    runner = AgentRunner(
        _settings(budget_usd=Decimal("5")),
        BreakerStore(tmp_path / "breakers.json"),
        root=REPO_ROOT,
        model_factory=lambda name: FunctionModel(costly),
    )

    with pytest.raises(AgentRunError) as stopped:
        runner.run(worker, "hello", bundle=BUNDLE_HEADING, budget_usd=Decimal("0.003"))

    assert "1000" in str(stopped.value)
