"""The `ra` entry point, exercised through Typer's test runner."""

from typer.testing import CliRunner

from recursive_application.kernel.cli import app

runner = CliRunner()


def test_help_exits_zero_and_lists_the_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("ask", "improve", "evals", "status", "wiki"):
        assert command in result.output


def test_ask_is_not_implemented_and_exits_two() -> None:
    result = runner.invoke(app, ["ask", "hello"])

    assert result.exit_code == 2
    assert "not implemented" in result.output


def test_wiki_lint_is_not_implemented_and_exits_two() -> None:
    result = runner.invoke(app, ["wiki", "lint"])

    assert result.exit_code == 2
    assert "not implemented" in result.output
