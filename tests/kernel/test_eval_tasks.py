"""The eval task functions, the custom evaluators, and the eval runner.

Every dataset under `evals/` is answered by one task function, and this is where the mapping
from a dataset name to its task, the two Kernel evaluators, and `run_evals` are held to the
seams document. Every model is a `TestModel` handed to the runner through `model_factory`,
and the judge is replaced too, so nothing here reaches the network.
"""

import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_evals.evaluators import llm_as_a_judge
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.eval_tasks import (
    TASK_KINDS,
    EvalContext,
    copy_checkout,
    dataset_kind,
    evaluate_request,
    run_evals,
    task_for,
)
from recursive_application.kernel.evals import (
    EVALS_DIR,
    CaseResult,
    DatasetError,
    EvalReport,
    ReportStore,
    dataset_name,
    list_datasets,
    load_dataset,
    results_from,
)
from recursive_application.kernel.loop import EvalRequest
from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.registry import load_registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.settings import Settings
from recursive_application.organism.wiki import Wiki

PRIMARY_MODEL = "openrouter:primary/model"
JUDGE_MODEL = "openrouter:judge/model"


def _settings() -> Settings:
    """Settings with no `.env` behind them, so a run's limits are exactly the test's."""
    return Settings(
        _env_file=None,
        ra_model=PRIMARY_MODEL,
        ra_judge_model=JUDGE_MODEL,
        ra_request_limit=5,
        ra_coder_request_limit=5,
        ra_budget_usd=Decimal("5"),
    )


def _context(tmp_path: Path, model_factory: Callable[[str], Model]) -> EvalContext:
    """An eval context over the real checkout, with a temporary runtime directory and Wiki."""
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    return EvalContext(
        runner=AgentRunner(
            _settings(),
            BreakerStore(tmp_path / "breakers.json"),
            root=REPO_ROOT,
            model_factory=model_factory,
        ),
        registry=load_registry(),
        root=REPO_ROOT,
        run_id="evals-test-run",
        iteration_limit=5,
        scratch=tmp_path / "scratch",
        ra_dir=tmp_path / ".ra",
        wiki=wiki,
        budget_usd=Decimal("5"),
    )


def test_a_frontier_dataset_maps_to_the_frontier_kind_and_a_role_dataset_to_its_own() -> None:
    assert dataset_kind("frontier/text-analysis") == "frontier"
    assert dataset_kind("test-writer") == "test-writer"


def test_every_seeded_dataset_maps_to_a_kind_that_has_a_task_function() -> None:
    kinds = [dataset_kind(dataset_name(path)) for path in list_datasets(EVALS_DIR)]

    assert kinds
    assert set(kinds) <= set(TASK_KINDS)


def test_a_dataset_kind_without_a_task_function_is_refused_by_name(tmp_path: Path) -> None:
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    with pytest.raises(DatasetError) as raised:
        task_for("nope", ctx)

    assert "nope" in str(raised.value)


def _probe_report(tmp_path: Path, evaluator: str, outputs: dict[str, str]) -> list[CaseResult]:
    """Run `evaluator` over one case per entry of `outputs`, the case's inputs being its output."""
    cases = "\n".join(
        f"  - name: {name}\n    inputs: |\n"
        + "".join(f"      {line}\n" for line in text.splitlines())
        + f"    evaluators:\n      - {evaluator}\n"
        for name, text in outputs.items()
    )
    path = tmp_path / "probe.yaml"
    path.write_text(f"cases:\n{cases}", encoding="utf-8")
    report = load_dataset(path).evaluate_sync(lambda inputs: inputs, progress=False)
    return results_from("probe", report)


def test_the_no_secrets_evaluator_fails_an_output_carrying_a_key_shaped_token(
    tmp_path: Path,
) -> None:
    results = _probe_report(
        tmp_path,
        "NoSecrets",
        {
            "leaks": "the key is sk-or-v1-0123456789abcdef0123456789abcdef",
            "clean": "no secrets here",
        },
    )

    leaks, clean = results[0], results[1]
    assert leaks.name == "leaks"
    assert not leaks.passed
    assert "sk-" in leaks.reasons[0]
    assert clean.name == "clean"
    assert clean.passed


def test_the_organism_targets_evaluator_fails_a_plan_that_targets_a_protected_path(
    tmp_path: Path,
) -> None:
    results = _probe_report(
        tmp_path,
        "OrganismTargetsOnly",
        {
            "kernel": "target_paths:\n- docs/coding-guide.md\n",
            "organism": "target_paths:\n- src/recursive_application/organism/agents.py\n",
        },
    )

    kernel, organism = results[0], results[1]
    assert kernel.name == "kernel"
    assert not kernel.passed
    assert "docs/coding-guide.md" in kernel.reasons[0]
    assert organism.name == "organism"
    assert organism.passed


TRIAGE_GROWTH_ARGS: dict[str, Any] = {
    "mode": "growth",
    "reasoning": "no agent analyses an argument today",
    "reflection": {
        "required_capabilities": ["argument analysis"],
        "gaps": [
            {
                "kind": "skill",
                "description": "no agent reconstructs premises",
                "how_to_acquire": "add a Specialist with its own prompt",
            }
        ],
    },
}


def test_the_triage_task_renders_the_decision_as_yaml_the_dataset_can_assert_on(
    tmp_path: Path,
) -> None:
    ctx = _context(
        tmp_path, lambda name: TestModel(call_tools=[], custom_output_args=TRIAGE_GROWTH_ARGS)
    )

    output = task_for("triage", ctx)("Analyse the argument of this text.")

    assert "mode: growth" in output
    assert "kind: skill" in output


WORKER_ANSWER = "A Protected Path is a path the Kernel owns and the Organism may never modify."


def test_the_answers_task_renders_the_workers_content_as_it_is(tmp_path: Path) -> None:
    ctx = _context(
        tmp_path,
        lambda name: TestModel(call_tools=[], custom_output_args={"content": WORKER_ANSWER}),
    )

    output = task_for("answers", ctx)("What is a Protected Path?")

    assert output == WORKER_ANSWER


REVIEW_ARGS: dict[str, Any] = {
    "matches_plan": True,
    "gaming_suspected": False,
    "notes": "the diff does what the Plan says",
    "verdict": "accept",
}

REVIEWER_INPUTS = """\
plan:
  title: The Wiki can read back its log entries
  evidence: Nothing reads the Wiki log back.
  cause: organism/wiki.py has no accessor for the log.
  change: Add Wiki.log_entries().
  target_paths:
    - src/recursive_application/organism/wiki.py
  target_cases:
    - name: wiki-reads-its-log
      inputs: What did the Wiki log during the last run?
  predicted_impact: The log becomes readable.
diff: |
  --- a/src/recursive_application/organism/wiki.py
  +++ b/src/recursive_application/organism/wiki.py
  +    def log_entries(self) -> list[str]:
"""


def _recording_model(args: dict[str, Any], seen: list[str]) -> FunctionModel:
    """A model that records the user prompt it is given and answers with `args`."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen.extend(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return FunctionModel(respond)


def test_the_reviewer_task_reads_its_yaml_mapping_and_renders_the_review_as_yaml(
    tmp_path: Path,
) -> None:
    seen: list[str] = []
    ctx = _context(tmp_path, lambda name: _recording_model(REVIEW_ARGS, seen))

    output = task_for("reviewer", ctx)(REVIEWER_INPUTS)

    assert "The Wiki can read back its log entries" in seen[0]
    assert "+    def log_entries(self) -> list[str]:" in seen[0]
    assert "verdict: accept" in output


@pytest.fixture
def judge_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put pydantic-evals' default judge back after a test that sets it.

    The setter is process-global and has no getter, so the module attribute it writes is
    recorded here and restored when the test ends.
    """
    monkeypatch.setattr(llm_as_a_judge, "_default_model", llm_as_a_judge._default_model)


def test_run_evals_sets_the_judge_once_before_the_first_run_and_saves_the_report(
    tmp_path: Path, judge_default: None
) -> None:
    events: list[tuple[str, object]] = []
    judge = TestModel(call_tools=[])
    ctx = _context(
        tmp_path,
        lambda name: (
            events.append(("model", name))
            or TestModel(call_tools=[], custom_output_args=TRIAGE_GROWTH_ARGS)
        ),
    )
    reports_dir = tmp_path / "reports"

    report, path = run_evals(
        ["triage"],
        ctx=ctx,
        reports_dir=reports_dir,
        judge_model=judge,
        judge_setter=lambda model: (
            events.append(("judge", model)) or set_default_judge_model(model)
        ),
    )

    assert report.datasets == ["triage"]
    assert report.run_id == "evals-test-run"
    assert {result.dataset for result in report.cases} == {"triage"}
    assert path == reports_dir / "evals-test-run.json"
    assert ReportStore(reports_dir).load_latest() == report
    assert [event for event in events if event[0] == "judge"] == [("judge", judge)]
    assert events[0] == ("judge", judge)


def _stand_in_datasets(evals_dir: Path) -> None:
    """One empty dataset per kind, so a selection is observable without running a case."""
    (evals_dir / "frontier").mkdir(parents=True)
    for name in (
        "triage",
        "planner",
        "test-writer",
        "implementer",
        "answers",
        "reviewer",
        "librarian",
        "frontier/text-analysis",
    ):
        (evals_dir / f"{name}.yaml").write_text("cases: []\n", encoding="utf-8")


def test_the_whole_suite_leaves_out_the_expensive_datasets_unless_they_are_asked_for(
    tmp_path: Path,
) -> None:
    evals_dir = tmp_path / "evals"
    _stand_in_datasets(evals_dir)
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    cheap, _ = run_evals(
        None,
        ctx=ctx,
        reports_dir=tmp_path / "reports",
        judge_model=JUDGE_MODEL,
        judge_setter=lambda model: None,
        evals_dir=evals_dir,
    )
    everything, _ = run_evals(
        None,
        ctx=ctx,
        reports_dir=tmp_path / "reports",
        judge_model=JUDGE_MODEL,
        judge_setter=lambda model: None,
        evals_dir=evals_dir,
        include_expensive=True,
    )

    assert cheap.datasets == [
        "answers",
        "frontier/text-analysis",
        "librarian",
        "planner",
        "reviewer",
        "triage",
    ]
    assert everything.datasets == [
        "answers",
        "frontier/text-analysis",
        "implementer",
        "librarian",
        "planner",
        "reviewer",
        "test-writer",
        "triage",
    ]


def test_run_evals_refuses_a_dataset_name_that_names_no_file(tmp_path: Path) -> None:
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    with pytest.raises(DatasetError) as raised:
        run_evals(
            ["nope"],
            ctx=ctx,
            reports_dir=tmp_path / "reports",
            judge_model=JUDGE_MODEL,
            judge_setter=lambda model: None,
        )

    assert "nope" in str(raised.value)


def test_a_dataset_that_names_its_own_model_is_refused_before_the_judge_is_set(
    tmp_path: Path,
) -> None:
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir()
    path = evals_dir / "triage.yaml"
    path.write_text(
        "cases:\n"
        "  - name: names-a-model\n"
        "    inputs: hello\n"
        "    evaluators:\n"
        "      - LLMJudge:\n"
        "          rubric: is polite\n"
        "          model: openrouter:x/y\n",
        encoding="utf-8",
    )
    set_judges: list[object] = []
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    with pytest.raises(DatasetError) as raised:
        run_evals(
            None,
            ctx=ctx,
            reports_dir=tmp_path / "reports",
            judge_model=JUDGE_MODEL,
            judge_setter=set_judges.append,
            evals_dir=evals_dir,
        )

    assert str(path) in str(raised.value)
    assert "names-a-model" in str(raised.value)
    assert set_judges == []


LIBRARIAN_PAGE = "wiki/pages/capabilities/repo-history.md"
LIBRARIAN_PAGE_TEXT = (
    "# repo-history\n\nThe Worker answers questions about the repository's history.\n\n"
    "- Commit: 4f2a91c\n- Dataset: evals/frontier/repo-history.yaml\n"
)
LIBRARIAN_SUMMARY = "Wrote the capability page for repo-history."


def _librarian_model() -> FunctionModel:
    """A Librarian that writes one capability page through its file tool, then reports."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "write_file",
                        {"path": LIBRARIAN_PAGE, "content": LIBRARIAN_PAGE_TEXT},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(LIBRARIAN_SUMMARY)])

    return FunctionModel(respond)


def test_the_librarian_task_writes_into_a_scratch_wiki_and_renders_its_pages(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path, lambda name: _librarian_model())

    output = task_for("librarian", ctx)("run_summary: |\n  Run 20260905-101500-a1b2c3 accepted.\n")

    assert "pages/capabilities/repo-history.md" in output
    assert "- Commit: 4f2a91c" in output
    assert LIBRARIAN_SUMMARY in output
    assert "log_tail: '# Wiki log'" in output
    assert not (REPO_ROOT / LIBRARIAN_PAGE).exists()


ANSWER_CASES = (
    "cases:\n  - name: answer-r1\n    inputs: say hello\n    evaluators:\n      - Contains: hello\n"
)
"""One runtime Target Case of an Answer run, as the Loop writes it before an Iteration."""


def _answer_report(
    tmp_path: Path, output: str, *, dataset: str | None = None, targets: list[str] | None = None
) -> EvalReport:
    """The report `evaluate_request` produces for an Answer run that produced `output`."""
    path = tmp_path / "cases.yaml"
    path.write_text(ANSWER_CASES, encoding="utf-8")
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    return evaluate_request(
        EvalRequest(
            run_id="r1",
            task_dataset=str(path),
            dataset=dataset,
            output=output,
            targets=["answer-r1/answer-r1"] if targets is None else targets,
        ),
        ctx=ctx,
        reports_dir=tmp_path / "reports",
        judge_model=JUDGE_MODEL,
        judge_setter=lambda model: None,
    )


def test_an_answer_request_judges_the_output_against_the_run_s_own_task_dataset(
    tmp_path: Path,
) -> None:
    passed = _answer_report(tmp_path, "hello world")
    failed = _answer_report(tmp_path, "nothing")

    assert passed.run_id == "r1"
    assert passed.datasets == ["answer-r1"]
    assert [(case.dataset, case.name, case.passed) for case in passed.cases] == [
        ("answer-r1", "answer-r1", True)
    ]
    assert [case.passed for case in failed.cases] == [False]


def test_an_answer_request_is_reported_under_the_dataset_name_it_names(tmp_path: Path) -> None:
    report = _answer_report(tmp_path, "hello world", dataset="answer-r1", targets=[])

    assert report.datasets == ["answer-r1"]
    assert [case.dataset for case in report.cases] == ["answer-r1"]


def test_the_kernel_imports_nothing_from_the_organism_when_the_eval_tasks_load() -> None:
    script = (
        "import sys\n"
        "import recursive_application.kernel.eval_tasks\n"
        "print(sorted(m for m in sys.modules if m.startswith('recursive_application.organism')))\n"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert loaded == "[]"


def test_a_scratch_checkout_carries_the_protected_documents_the_kernel_tests_read(
    tmp_path: Path,
) -> None:
    ctx = _context(tmp_path, lambda name: TestModel(call_tools=[]))

    scratch = copy_checkout(ctx, "implementer")

    assert (scratch / "docs" / "coding-guide.md").is_file()
    assert (scratch / "CONTEXT.md").is_file()
    assert (scratch / "wiki" / "index.md").is_file()
    assert (scratch / "src" / "recursive_application" / "organism" / "wiki.py").is_file()
    assert not (scratch / ".venv").exists()
