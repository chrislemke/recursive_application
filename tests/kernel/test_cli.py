"""The `ra` entry point, exercised through Typer's test runner.

Every command builds its collaborators through `build_context()` and reaches its work through a
module attribute of `kernel/cli.py`, so a test replaces both and never touches a model, git, or
the real runtime directory. What is asserted here is what a caller sees: the arguments the
command passed on, the text it printed, and the exit code it left behind. The credential tests
run the real `build_context` through `_isolate_build_context`, which points `.env` and `.ra` at
`tmp_path` and only reads the checkout.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.exceptions import UserError
from pydantic_ai.models import Model
from typer.testing import CliRunner

from recursive_application.kernel import cli
from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.checks import run_checks, run_red_check
from recursive_application.kernel.cli import KernelContext, app
from recursive_application.kernel.evals import CaseResult, DatasetError, EvalReport
from recursive_application.kernel.git import Repo
from recursive_application.kernel.loop import EvalRequest, LoopOptions, LoopResult, Runners
from recursive_application.kernel.paths import ensure_ra_dirs
from recursive_application.kernel.providers import model_factory
from recursive_application.kernel.records import (
    EvalCase,
    IterationRecord,
    Mode,
    Outcome,
    Plan,
    RunRecord,
)
from recursive_application.kernel.registry import load_registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.sensors import FEEDBACK_FILENAME, FeedbackStore
from recursive_application.kernel.settings import Settings, load_settings
from recursive_application.organism.wiki import Wiki

runner = CliRunner()

CLOCK_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
"""The one moment every faked run happens at, so a written record is comparable."""


def _context(tmp_path: Path) -> KernelContext:
    """A Kernel context over a temporary runtime directory: no key, no `.env`, no model."""
    settings = Settings(_env_file=None)
    ra_dir = tmp_path / ".ra"
    ra_dir.mkdir(exist_ok=True)
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    breakers = BreakerStore(ra_dir / "breaker.json")
    return KernelContext(
        settings=settings,
        root=tmp_path,
        ra_dir=ra_dir,
        registry=load_registry(),
        repo=Repo(tmp_path),
        wiki=wiki,
        breakers=breakers,
        agents=AgentRunner(settings, breakers, root=tmp_path),
        runners=Runners(
            checks=run_checks,
            red_check=run_red_check,
            evals=lambda request: EvalReport(run_id=request.run_id, datasets=[]),
            approve=lambda text: True,
            clock=lambda: CLOCK_TIME,
            tracing=lambda run_id: ra_dir / f"{run_id}.jsonl",
        ),
        model_factory=model_factory(settings),
    )


@dataclass
class _LoopCall:
    """One `LoopRunner.run` the CLI made."""

    mode: Mode | None
    task: str | None
    options: LoopOptions


def _fake_loop(calls: list[_LoopCall], result: LoopResult | Exception) -> Callable[..., Any]:
    """A stand-in for `LoopRunner` that records the run it was asked for and answers `result`."""

    class FakeLoopRunner:
        def __init__(self, **collaborators: Any) -> None:
            self.collaborators = collaborators

        def run(self, mode: Mode | None, task: str | None, options: LoopOptions) -> LoopResult:
            calls.append(_LoopCall(mode, task, options))
            if isinstance(result, Exception):
                raise result
            return result

    return FakeLoopRunner


def _result(
    outcome: Outcome,
    *,
    output: str | None = None,
    reason: str | None = None,
    questions: list[str] | None = None,
    exit_code: int = 0,
) -> LoopResult:
    """What the Loop runner hands the CLI back at the end of a run."""
    return LoopResult(
        record=RunRecord(mode=Mode.ANSWER, task="hello", outcome=outcome),
        output=output,
        reason=reason,
        questions=questions or [],
        exit_code=exit_code,
    )


ANSWER = "A Protected Path is a file only the human may change."


def _isolate_build_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Let the real `build_context` run without the real `.env` or the real runtime directory.

    Settings come from the environment and an absent file under `tmp_path`; `.ra` is created
    under `tmp_path`. The checkout itself is only read (the registry, the Wiki, the frontier).
    """
    monkeypatch.setattr(cli, "load_settings", lambda: load_settings(tmp_path / ".env"))
    monkeypatch.setattr(cli, "ensure_ra_dirs", lambda root: ensure_ra_dirs(tmp_path))


def test_help_exits_zero_and_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("ask", "improve", "evals", "status", "wiki"):
        assert command in result.output


def test_ask_passes_its_flags_to_the_loop_and_prints_the_answer_and_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[_LoopCall] = []
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop(calls, _result("accepted", output=ANSWER)))

    result = runner.invoke(
        app, ["ask", "hello", "--yes", "--max-iterations", "2", "--budget", "1.5"]
    )

    assert result.exit_code == 0
    assert calls == [
        _LoopCall(None, "hello", LoopOptions(yes=True, max_iterations=2, budget_usd=Decimal("1.5")))
    ]
    assert ANSWER in result.output
    assert "Outcome: accepted" in result.output


LINT_TEXT = "Orphans:\n(none)\nUnindexed:\npages/tasks/new.md\n"


def test_wiki_lint_prints_the_report_and_exits_with_the_code_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "lint_wiki", lambda wiki: (LINT_TEXT, 1))

    result = runner.invoke(app, ["wiki", "lint"])

    assert result.exit_code == 1
    assert LINT_TEXT in result.output


@pytest.mark.parametrize(("outcome", "exit_code"), [("rejected", 1), ("aborted", 2), ("error", 3)])
def test_ask_exits_with_the_code_the_run_ended_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: Outcome, exit_code: int
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(
        cli,
        "LoopRunner",
        _fake_loop([], _result(outcome, output=ANSWER, reason="budget", exit_code=exit_code)),
    )

    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == exit_code
    assert f"Outcome: {outcome}" in result.output
    assert "Reason: budget" in result.output


def test_ask_prints_triage_s_questions_instead_of_an_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    questions = ["Which repository?", "By when?"]
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(
        cli,
        "LoopRunner",
        _fake_loop(
            [], _result("aborted", questions=questions, reason="clarification", exit_code=2)
        ),
    )

    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == 2
    assert "Which repository?\nBy when?\n" in result.output


def test_an_unexpected_failure_is_an_internal_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], RuntimeError("x")))

    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == 3
    assert "internal error: x" in result.stderr


FEEDBACK_QUESTION = "Was this answer useful?"


def test_no_feedback_is_asked_for_when_stdin_is_not_a_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], _result("accepted", output=ANSWER)))

    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == 0
    assert FEEDBACK_QUESTION not in result.output
    assert not (tmp_path / ".ra" / FEEDBACK_FILENAME).exists()


def test_a_negative_answer_at_a_terminal_lands_in_the_feedback_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = _result("accepted", output=ANSWER)
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], answer))

    result = runner.invoke(app, ["ask", "hello"], input="n\ntoo vague\n")

    assert result.exit_code == 0
    assert FEEDBACK_QUESTION in result.output
    entries = FeedbackStore(tmp_path / ".ra" / FEEDBACK_FILENAME).list_all()
    assert [(entry.run_id, entry.positive, entry.comment, entry.at) for entry in entries] == [
        (answer.record.run_id, False, "too vague", CLOCK_TIME)
    ]


def test_an_unattended_run_is_never_asked_for_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "stdin_is_a_terminal", lambda: True)
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], _result("accepted", output=ANSWER)))

    result = runner.invoke(app, ["ask", "hello", "--yes"], input="n\ntoo vague\n")

    assert result.exit_code == 0
    assert FEEDBACK_QUESTION not in result.output
    assert not (tmp_path / ".ra" / FEEDBACK_FILENAME).exists()


GROWTH_PLAN = Plan(
    title="Teach the Worker what the Gate is",
    evidence="The answers dataset holds no case about the Gate.",
    cause="Nothing in the Organism states what the Gate is.",
    change="Add a glossary module and the answers case that proves it.",
    target_cases=[
        EvalCase(
            name="answers-4-what-is-the-gate", inputs="What is the Gate?", must_contain=["Gate"]
        )
    ],
    predicted_impact="The new answers case passes and no Guard Case regresses.",
)


def _growth_result(
    outcome: Outcome, *, reason: str | None = None, exit_code: int = 0
) -> LoopResult:
    """What the Loop runner hands back from an improve run: two Iterations and no Answer."""
    record = RunRecord(
        mode=Mode.GROWTH,
        task=None,
        outcome=outcome,
        iterations=[
            IterationRecord(number=1, plan=GROWTH_PLAN, outcome="accepted"),
            IterationRecord(number=2, outcome="rejected", reason="no red: 1 passed"),
        ],
    )
    return LoopResult(record=record, reason=reason, exit_code=exit_code)


def test_improve_hands_its_goal_to_the_growth_loop_and_prints_one_line_per_iteration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[_LoopCall] = []
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop(calls, _growth_result("accepted")))

    result = runner.invoke(app, ["improve", "--goal", "reduce cost", "--yes"])

    assert result.exit_code == 0
    assert calls == [_LoopCall(Mode.GROWTH, None, LoopOptions(yes=True, goal="reduce cost"))]
    assert "Iteration 1: accepted Teach the Worker what the Gate is\n" in result.output
    assert "Iteration 2: rejected no red: 1 passed\n" in result.output
    assert "Outcome: accepted" in result.output


def test_improve_exits_with_the_code_the_run_ended_on_and_prints_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(
        cli,
        "LoopRunner",
        _fake_loop([], _growth_result("aborted", reason="iteration limit", exit_code=2)),
    )

    result = runner.invoke(app, ["improve"])

    assert result.exit_code == 2
    assert "Outcome: aborted" in result.output
    assert "Reason: iteration limit" in result.output


@dataclass
class _EvalsCall:
    """One `run_evals` the CLI made: which datasets, how often, and how wide."""

    names: list[str] | None
    repeat: int
    include_expensive: bool


def _fake_run_evals(
    calls: list[_EvalsCall], result: tuple[EvalReport, Path] | Exception
) -> Callable[..., Any]:
    """A stand-in for `run_evals` that records the selection it was given."""

    def run_evals(
        names: list[str] | None,
        *,
        ctx: Any,
        reports_dir: Path,
        judge_model: Any,
        repeat: int = 1,
        include_expensive: bool = False,
    ) -> tuple[EvalReport, Path]:
        calls.append(_EvalsCall(names, repeat, include_expensive))
        if isinstance(result, Exception):
            raise result
        return result

    return run_evals


def test_evals_runs_the_named_dataset_and_prints_the_report_and_where_it_went(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[_EvalsCall] = []
    report = EvalReport(
        run_id="r1",
        datasets=["triage"],
        cases=[CaseResult(dataset="triage", name="a-clear-request", passed=True)],
    )
    saved = tmp_path / "reports" / "r1.json"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "run_evals", _fake_run_evals(calls, (report, saved)))

    result = runner.invoke(app, ["evals", "--dataset", "triage", "--repeat", "3"])

    assert result.exit_code == 0
    assert calls == [_EvalsCall(["triage"], 3, False)]
    assert "triage: 1/1 passed" in result.output
    assert f"Report saved to {saved}" in result.output


def test_the_full_suite_runs_every_dataset_including_the_expensive_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[_EvalsCall] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(
        cli,
        "run_evals",
        _fake_run_evals(calls, (EvalReport(datasets=[]), tmp_path / "r2.json")),
    )

    result = runner.invoke(app, ["evals", "--all"])

    assert result.exit_code == 0
    assert calls == [_EvalsCall(None, 1, True)]


def test_an_unknown_dataset_is_a_usage_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(
        cli, "run_evals", _fake_run_evals([], DatasetError("unknown dataset: 'nope'"))
    )

    result = runner.invoke(app, ["evals", "--dataset", "nope"])

    assert result.exit_code == 2
    assert "unknown dataset: 'nope'" in result.stderr


STATUS_TEXT = "## Breakers\n\n(none)\n\n## Total cost\n\nTotal cost: 0 USD"


def test_status_prints_the_report_over_the_checkout_s_frontier_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Path] = []

    def fake_render_status(
        *,
        ra_dir: Path,
        wiki: Any,
        frontier_dir: Path,
        budget_usd: Decimal,
        breakers: Any,
        settings: Settings,
    ) -> str:
        seen.append(frontier_dir)
        return STATUS_TEXT

    monkeypatch.setattr(cli, "build_context", lambda check_credentials: _context(tmp_path))
    monkeypatch.setattr(cli, "render_status", fake_render_status)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert STATUS_TEXT in result.output
    assert seen == [tmp_path / "evals" / "frontier"]


INGEST_SUMMARY = "Recorded the document."


def test_wiki_ingest_hands_the_path_to_the_librarian_and_prints_its_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[Path, str]] = []

    def fake_ingest_wiki(
        path: Path,
        *,
        agents: Any,
        registry: Any,
        wiki: Any,
        root: Path,
        ra_dir: Path,
        budget_usd: Decimal,
        run_id: str,
    ) -> str:
        seen.append((path, run_id))
        return INGEST_SUMMARY

    document = tmp_path / "notes.md"
    document.write_text("# notes\n", encoding="utf-8")
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "ingest_wiki", fake_ingest_wiki)

    result = runner.invoke(app, ["wiki", "ingest", str(document)])

    assert result.exit_code == 0
    assert INGEST_SUMMARY in result.output
    assert [path for path, _ in seen] == [document]
    assert seen[0][1] != ""


def test_a_document_that_is_not_there_is_a_usage_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_ingest_wiki(path: Path, **collaborators: Any) -> str:
        raise FileNotFoundError(f"no such document: {path}")

    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "ingest_wiki", fake_ingest_wiki)

    result = runner.invoke(app, ["wiki", "ingest", str(tmp_path / "gone.md")])

    assert result.exit_code == 2
    assert "no such document" in result.stderr


def test_ask_refuses_an_openai_primary_without_its_key_naming_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_build_context(monkeypatch, tmp_path)
    monkeypatch.setenv("RA_MODEL", "openai:gpt-5.4")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], _result("accepted", output=ANSWER)))

    result = runner.invoke(app, ["ask", "hello", "--yes"])

    assert result.exit_code == 2
    assert "OPENAI_API_KEY" in result.stderr


def test_ask_refuses_a_chatgpt_primary_without_a_sign_in_naming_codex_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_build_context(monkeypatch, tmp_path)
    monkeypatch.setenv("RA_MODEL", "chatgpt:gpt-5.5")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], _result("accepted", output=ANSWER)))

    result = runner.invoke(app, ["ask", "hello", "--yes"])

    assert result.exit_code == 2
    assert "codex login" in result.stderr


def test_status_runs_without_the_credentials_ask_would_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_build_context(monkeypatch, tmp_path)
    monkeypatch.setenv("RA_MODEL", "chatgpt:gpt-5.5")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "render_status", lambda **collaborators: STATUS_TEXT)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert STATUS_TEXT in result.output


def test_evals_hands_run_evals_the_judge_model_built_from_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def fake_run_evals(names: Any, *, judge_model: Any, **options: Any) -> tuple[EvalReport, Path]:
        seen.append(judge_model)
        return EvalReport(datasets=[]), tmp_path / "r3.json"

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "run_evals", fake_run_evals)

    result = runner.invoke(app, ["evals", "--dataset", "triage"])

    assert result.exit_code == 0
    assert isinstance(seen[0], Model)
    assert seen[0].system == "openrouter"
    assert seen[0].model_name == "openai/gpt-5.4-mini"


def test_the_evals_runner_hands_evaluate_request_the_judge_model_built_from_its_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def fake_evaluate_request(request: Any, *, judge_model: Any, **options: Any) -> EvalReport:
        seen.append(judge_model)
        return EvalReport(run_id=request.run_id, datasets=[])

    _isolate_build_context(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(cli, "evaluate_request", fake_evaluate_request)

    cli.build_context().runners.evals(EvalRequest(run_id="r1"))

    assert isinstance(seen[0], Model)
    assert seen[0].system == "openrouter"
    assert seen[0].model_name == "openai/gpt-5.4-mini"


def test_a_model_name_pydantic_ai_refuses_is_a_usage_error_on_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_context", lambda: _context(tmp_path))
    monkeypatch.setattr(cli, "LoopRunner", _fake_loop([], UserError("Unknown model: nope")))

    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == 2
    assert "Unknown model: nope" in result.stderr
