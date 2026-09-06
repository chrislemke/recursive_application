"""The `ra` entry point: the Operator's commands, wired to the Kernel's modules.

Every command does the same three things: build its collaborators through `build_context()`,
call one function that already does the work, and turn what came back into printed text and an
exit code. Nothing here decides anything, so each command reaches its function through a module
attribute and a test can replace it, and the one error handler is the only place that turns an
exception into an exit code.
"""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.checks import run_checks, run_red_check
from recursive_application.kernel.eval_tasks import (
    WIKI_DIRNAME,
    EvalContext,
    evaluate_request,
    run_evals,
)
from recursive_application.kernel.evals import (
    EVALS_DIR,
    FRONTIER_DIRNAME,
    DatasetError,
    EvalReport,
)
from recursive_application.kernel.git import Repo
from recursive_application.kernel.loop import (
    EvalRequest,
    LoopOptions,
    LoopResult,
    LoopRunner,
    Runners,
)
from recursive_application.kernel.paths import (
    EVALS_DIRNAME,
    REPO_ROOT,
    TRACES_DIRNAME,
    ensure_ra_dirs,
)
from recursive_application.kernel.policy import PolicyError
from recursive_application.kernel.records import Mode, RunRecord
from recursive_application.kernel.registry import Registry, RegistryError, load_registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.sensors import FEEDBACK_FILENAME, FeedbackEntry, FeedbackStore
from recursive_application.kernel.settings import Settings, SettingsError, load_settings
from recursive_application.kernel.status import ingest_wiki, lint_wiki, render_status
from recursive_application.kernel.tracing import configure_tracing
from recursive_application.kernel.wiki_protocol import WikiMaintainer

EXIT_ABORTED = 2
"""The exit code of an aborted run and of every usage error."""

EXIT_INTERNAL = 3
"""The exit code of a failure the Kernel did not foresee."""

USAGE_ERRORS: tuple[type[Exception], ...] = (
    DatasetError,
    SettingsError,
    PolicyError,
    RegistryError,
    FileNotFoundError,
)
"""What the Operator can fix: a bad name, a missing Setting, a refused configuration, a path."""

BREAKER_FILENAME = "breaker.json"
"""Where the breaker states live under the runtime directory."""

SCRATCH_DIRNAME = "scratch"
"""Where an eval run puts its scratch checkouts, under the runtime directory."""

FEEDBACK_QUESTION = "Was this answer useful? [y/n]"
"""What the Operator is asked at a terminal once an Answer has been printed."""

COMMENT_QUESTION = "What was wrong?"
"""What follows a negative verdict; the next line typed is the comment kept with it."""

app = typer.Typer(no_args_is_help=True, add_completion=False)
wiki_app = typer.Typer(no_args_is_help=True)
app.add_typer(wiki_app, name="wiki", help="Maintain the Wiki.")

YesOption = Annotated[bool, typer.Option("--yes", "-y", help="Approve without asking.")]
MaxIterationsOption = Annotated[
    int | None, typer.Option("--max-iterations", help="Stop after N Iterations.")
]
BudgetOption = Annotated[float | None, typer.Option("--budget", help="Stop after spending USD.")]


@dataclass(frozen=True)
class KernelContext:
    """Everything a command needs, built once per invocation and never reached for again."""

    settings: Settings
    root: Path
    ra_dir: Path
    registry: Registry
    repo: Repo
    wiki: WikiMaintainer
    breakers: BreakerStore
    agents: AgentRunner
    runners: Runners


def _eval_context(
    *,
    settings: Settings,
    registry: Registry,
    agents: AgentRunner,
    wiki: WikiMaintainer,
    root: Path,
    ra_dir: Path,
    run_id: str,
) -> EvalContext:
    """The context every eval run needs, from the same pieces the rest of the Kernel gets."""
    return EvalContext(
        runner=agents,
        registry=registry,
        root=root,
        run_id=run_id,
        iteration_limit=settings.ra_max_iterations,
        scratch=ra_dir / SCRATCH_DIRNAME,
        ra_dir=ra_dir,
        wiki=wiki,
        budget_usd=settings.ra_budget_usd,
    )


def _approve(text: str) -> bool:
    """Show the Plan and its Target Cases, and let the human decide."""
    typer.echo(text)
    return typer.confirm("Approve?")


def build_context() -> KernelContext:
    """Build the Kernel's collaborators for one command: Settings, registry, git, Wiki, runners.

    The Organism's Wiki is imported here and not at module level, so the Kernel still imports
    nothing from the Organism when it is loaded; the same rule `load_registry` follows.
    """
    from recursive_application.organism.wiki import Wiki

    settings = load_settings()
    settings.require_api_key()
    root = REPO_ROOT
    ra_dir = ensure_ra_dirs(root)
    registry = load_registry(root)
    repo = Repo(root)
    wiki = Wiki(root / WIKI_DIRNAME)
    breakers = BreakerStore(
        ra_dir / BREAKER_FILENAME,
        failure_threshold=settings.ra_breaker_failures,
        reset_timeout_s=settings.ra_breaker_reset_s,
    )
    agents = AgentRunner(settings, breakers, root=root)

    def evals(request: EvalRequest) -> EvalReport:
        return evaluate_request(
            request,
            ctx=_eval_context(
                settings=settings,
                registry=registry,
                agents=agents,
                wiki=wiki,
                root=root,
                ra_dir=ra_dir,
                run_id=request.run_id,
            ),
            reports_dir=ra_dir / EVALS_DIRNAME,
            judge_model=settings.ra_judge_model,
        )

    runners = Runners(
        checks=run_checks,
        red_check=run_red_check,
        evals=evals,
        approve=_approve,
        clock=lambda: datetime.now(UTC),
        tracing=lambda run_id: configure_tracing(
            run_id=run_id, traces_dir=ra_dir / TRACES_DIRNAME, token=settings.logfire_token
        ),
    )
    return KernelContext(
        settings=settings,
        root=root,
        ra_dir=ra_dir,
        registry=registry,
        repo=repo,
        wiki=wiki,
        breakers=breakers,
        agents=agents,
        runners=runners,
    )


def _run_command(action: Callable[[], int]) -> None:
    """The one exit-code rule: what `action` returns, or what its failure means.

    A failure the Operator can act on prints its own message and exits 2; anything else is the
    Kernel's own fault, so it is named as such and exits 3 rather than reaching a traceback.
    """
    try:
        code = action()
    except USAGE_ERRORS as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=EXIT_ABORTED) from error
    except (typer.Exit, typer.Abort):
        raise
    except Exception as error:
        typer.echo(f"internal error: {error}", err=True)
        raise typer.Exit(code=EXIT_INTERNAL) from error
    raise typer.Exit(code=code)


def _new_run_id() -> str:
    """A run id for a command that is not a Loop run but still names one in what it writes."""
    return RunRecord(mode=Mode.TASK).run_id


def _budget_usd(budget: float | None) -> Decimal | None:
    """The budget as the Loop counts it; Typer has no `Decimal`, so the CLI converts here."""
    return None if budget is None else Decimal(str(budget))


def stdin_is_a_terminal() -> bool:
    """Whether a human is there to answer a question, which only a terminal tells us."""
    return sys.stdin.isatty()


def _ask_for_feedback(ctx: KernelContext, result: LoopResult, *, yes: bool) -> None:
    """Ask the Operator what the Answer was worth and keep a negative verdict.

    Only at a terminal and never under `--yes`, so a scripted run cannot block on a question
    nobody is there to answer; the comment is the line after the verdict, and the Sensors turn
    the entry into a finding from there.
    """
    if yes or not stdin_is_a_terminal():
        return
    typer.echo(FEEDBACK_QUESTION)
    if not sys.stdin.readline().strip().lower().startswith("n"):
        return
    typer.echo(COMMENT_QUESTION)
    FeedbackStore(ctx.ra_dir / FEEDBACK_FILENAME).append(
        FeedbackEntry(
            run_id=result.record.run_id,
            at=ctx.runners.clock(),
            positive=False,
            comment=sys.stdin.readline().strip(),
        )
    )


def _loop_runner(ctx: KernelContext) -> LoopRunner:
    """The Loop over the context's collaborators, the same for `ask` and `improve`."""
    return LoopRunner(
        settings=ctx.settings,
        registry=ctx.registry,
        agents=ctx.agents,
        repo=ctx.repo,
        wiki=ctx.wiki,
        root=ctx.root,
        ra_dir=ctx.ra_dir,
        runners=ctx.runners,
        breakers=ctx.breakers,
    )


def _print_iterations(record: RunRecord) -> None:
    """One line per Iteration: its number, how it ended, and the Plan's title or the reason."""
    for iteration in record.iterations:
        about = iteration.plan.title if iteration.plan else iteration.reason
        line = f"Iteration {iteration.number}: {iteration.outcome}"
        typer.echo(line if about is None else f"{line} {about}")


def _print_result(result: LoopResult) -> None:
    """What the Operator sees of a run: the questions or the output, then how it ended."""
    if result.questions:
        for question in result.questions:
            typer.echo(question)
    elif result.output is not None:
        typer.echo(result.output)
    typer.echo(f"Outcome: {result.record.outcome}")
    if result.reason:
        typer.echo(f"Reason: {result.reason}")


@app.command()
def ask(
    text: Annotated[str, typer.Argument(help="The request to answer or carry out.")],
    yes: YesOption = False,
    max_iterations: MaxIterationsOption = None,
    budget: BudgetOption = None,
) -> None:
    """Answer a request or carry out a task."""

    def action() -> int:
        ctx = build_context()
        result = _loop_runner(ctx).run(
            None,
            text,
            LoopOptions(yes=yes, max_iterations=max_iterations, budget_usd=_budget_usd(budget)),
        )
        _print_result(result)
        _ask_for_feedback(ctx, result, yes=yes)
        return result.exit_code

    _run_command(action)


@app.command()
def improve(
    goal: Annotated[str | None, typer.Option("--goal", help="Steer the Growth Loop.")] = None,
    yes: YesOption = False,
    max_iterations: MaxIterationsOption = None,
    budget: BudgetOption = None,
) -> None:
    """Run the Growth Loop."""

    def action() -> int:
        ctx = build_context()
        result = _loop_runner(ctx).run(
            Mode.GROWTH,
            None,
            LoopOptions(
                yes=yes,
                max_iterations=max_iterations,
                budget_usd=_budget_usd(budget),
                goal=goal,
            ),
        )
        _print_iterations(result.record)
        _print_result(result)
        return result.exit_code

    _run_command(action)


@app.command()
def evals(
    dataset: Annotated[
        str | None, typer.Option("--dataset", help="One dataset, e.g. frontier/text-analysis.")
    ] = None,
    repeat: Annotated[int, typer.Option("--repeat", help="Run each case K times.")] = 1,
    everything: Annotated[
        bool, typer.Option("--all", help="Include the expensive datasets.")
    ] = False,
) -> None:
    """Run the eval datasets."""

    def action() -> int:
        ctx = build_context()
        report, path = run_evals(
            [dataset] if dataset else None,
            ctx=_eval_context(
                settings=ctx.settings,
                registry=ctx.registry,
                agents=ctx.agents,
                wiki=ctx.wiki,
                root=ctx.root,
                ra_dir=ctx.ra_dir,
                run_id=_new_run_id(),
            ),
            reports_dir=ctx.ra_dir / EVALS_DIRNAME,
            judge_model=ctx.settings.ra_judge_model,
            repeat=repeat,
            include_expensive=everything,
        )
        for line in report.summary_lines():
            typer.echo(line)
        typer.echo(f"Report saved to {path}")
        return 0

    _run_command(action)


@app.command()
def status() -> None:
    """Show the runtime state."""

    def action() -> int:
        ctx = build_context()
        typer.echo(
            render_status(
                ra_dir=ctx.ra_dir,
                wiki=ctx.wiki,
                frontier_dir=ctx.root / EVALS_DIR.name / FRONTIER_DIRNAME,
                budget_usd=ctx.settings.ra_budget_usd,
                breakers=ctx.breakers,
            )
        )
        return 0

    _run_command(action)


@wiki_app.command()
def ingest(
    path: Annotated[Path, typer.Argument(help="The document to ingest.")],
) -> None:
    """Ingest a document into the Wiki."""

    def action() -> int:
        ctx = build_context()
        typer.echo(
            ingest_wiki(
                path,
                agents=ctx.agents,
                registry=ctx.registry,
                wiki=ctx.wiki,
                root=ctx.root,
                ra_dir=ctx.ra_dir,
                budget_usd=ctx.settings.ra_budget_usd,
                run_id=_new_run_id(),
            )
        )
        return 0

    _run_command(action)


@wiki_app.command()
def lint() -> None:
    """Check the Wiki for broken pages and links."""

    def action() -> int:
        ctx = build_context()
        text, code = lint_wiki(ctx.wiki)
        typer.echo(text.rstrip("\n"))
        return code

    _run_command(action)
