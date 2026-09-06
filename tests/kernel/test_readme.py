"""The README, with its text as the seam.

`README.md` is inside the write scope, so the Implementer may edit it. These tests keep what an
Operator reads true of the code: every repo-relative path it names exists, every `ra` command
and flag it names is registered, and all four exit codes are listed. Nothing here tests wording.
"""

import re

import pytest
import typer.main
from typer.core import TyperCommand, TyperGroup

from recursive_application.kernel.cli import app
from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.pointers import PLACEHOLDER, backticked_spans, missing_pointers

README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

RUNNER_PREFIX = "uv run "
"""How the README spells a command for a shell that has no `ra` on its path."""

_FLAG = re.compile(r"--[a-z][a-z-]*")
_EXIT_CODE_ROW = re.compile(r"^\| `(\d)` \|", re.MULTILINE)


def _command_spans(text: str) -> list[str]:
    """Every backticked span that runs `ra` with a command: no placeholder, no bare option."""
    spans = [span.removeprefix(RUNNER_PREFIX) for span in backticked_spans(text)]
    return [
        span
        for span in spans
        if span.startswith("ra ")
        and PLACEHOLDER not in span
        and len(span.split()) > 1
        and not span.split()[1].startswith("-")
    ]


def _flag_spans(text: str) -> list[str]:
    """Every backticked span that is one `--flag` on its own, as the prose names them."""
    return [span for span in backticked_spans(text) if _FLAG.fullmatch(span)]


Registered = TyperGroup | TyperCommand
"""What Typer registers under a name: a command, or a group of them such as `ra wiki`."""


def _root() -> TyperGroup:
    """The `ra` group itself."""
    root = typer.main.get_command(app)
    assert isinstance(root, TyperGroup)
    return root


def _options_of(command: Registered) -> set[str]:
    """The `--flag` spellings one command accepts."""
    return {opt for param in command.params for opt in param.opts if opt.startswith("--")}


def _registered(command: TyperGroup) -> list[Registered]:
    """What a group holds, each a Typer command or group."""
    return [found for found in command.commands.values() if isinstance(found, Registered)]


def _command_named(words: list[str]) -> tuple[Registered, list[str]]:
    """The command the words after `ra` name, and the words left after its name.

    `ra wiki ingest PATH` resolves through the `wiki` group; a name `ra` does not know raises.
    """
    command: Registered = _root()
    while isinstance(command, TyperGroup) and words:
        name, *words = words
        found = command.commands.get(name)
        if not isinstance(found, Registered):
            raise LookupError(f"`ra` has no command {name!r}")
        command = found
    return command, words


def _every_option() -> set[str]:
    """Every `--flag` any `ra` command accepts, the groups walked to their leaves."""
    options: set[str] = set()
    pending: list[Registered] = [_root()]
    while pending:
        command = pending.pop()
        options |= _options_of(command)
        if isinstance(command, TyperGroup):
            pending.extend(_registered(command))
    return options


def test_the_readme_has_no_dangling_pointer() -> None:
    assert missing_pointers(README) == []


@pytest.mark.parametrize("span", _command_spans(README))
def test_every_ra_command_in_the_readme_is_registered_with_its_flags(span: str) -> None:
    command, rest = _command_named(span.split()[1:])

    assert set(_FLAG.findall(" ".join(rest))) <= _options_of(command)


def test_every_flag_the_readme_names_on_its_own_belongs_to_some_ra_command() -> None:
    assert set(_flag_spans(README)) <= _every_option()


def test_the_readme_lists_all_four_exit_codes() -> None:
    assert sorted(_EXIT_CODE_ROW.findall(README)) == ["0", "1", "2", "3"]
