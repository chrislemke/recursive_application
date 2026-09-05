"""The `ra` entry point.

Stub for this phase: every command prints that it is not implemented and exits 2.
"""

from pathlib import Path
from typing import Annotated

import typer

EXIT_ABORTED = 2

app = typer.Typer(no_args_is_help=True, add_completion=False)
wiki_app = typer.Typer(no_args_is_help=True)
app.add_typer(wiki_app, name="wiki", help="Maintain the Wiki.")

YesOption = Annotated[bool, typer.Option("--yes", "-y", help="Approve without asking.")]
MaxIterationsOption = Annotated[
    int | None, typer.Option("--max-iterations", help="Stop after N Iterations.")
]
BudgetOption = Annotated[float | None, typer.Option("--budget", help="Stop after spending USD.")]


def _not_implemented(command: str) -> None:
    typer.echo(f"ra {command}: not implemented yet", err=True)
    raise typer.Exit(code=EXIT_ABORTED)


@app.command()
def ask(
    text: Annotated[str, typer.Argument(help="The request to answer or carry out.")],
    yes: YesOption = False,
    max_iterations: MaxIterationsOption = None,
    budget: BudgetOption = None,
) -> None:
    """Answer a request or carry out a task."""
    _not_implemented("ask")


@app.command()
def improve(
    goal: Annotated[str | None, typer.Option("--goal", help="Steer the Growth Loop.")] = None,
    yes: YesOption = False,
    max_iterations: MaxIterationsOption = None,
    budget: BudgetOption = None,
) -> None:
    """Run the Growth Loop."""
    _not_implemented("improve")


@app.command()
def evals(
    dataset: Annotated[
        str | None, typer.Option("--dataset", help="One dataset, e.g. frontier/text-analysis.")
    ] = None,
    repeat: Annotated[int, typer.Option("--repeat", help="Run each case K times.")] = 1,
) -> None:
    """Run the eval datasets."""
    _not_implemented("evals")


@app.command()
def status() -> None:
    """Show the runtime state."""
    _not_implemented("status")


@wiki_app.command()
def ingest(
    path: Annotated[Path, typer.Argument(help="The document to ingest.")],
) -> None:
    """Ingest a document into the Wiki."""
    _not_implemented("wiki ingest")


@wiki_app.command()
def lint() -> None:
    """Check the Wiki for broken pages and links."""
    _not_implemented("wiki lint")
