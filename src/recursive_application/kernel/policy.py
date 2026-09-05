"""The Policy Ceiling: the limits no Organism tool configuration may exceed (ADR 0001).

The Organism owns which commands and paths each of its agents gets; the Kernel owns this
ceiling and refuses to build an agent whose configuration exceeds it. Widening the ceiling
is a Kernel change and therefore a human decision.
"""

import re
import shlex
from collections.abc import Mapping

from pydantic import Field

from recursive_application.kernel.paths import WRITABLE_DIRS, writable_globs
from recursive_application.kernel.records import Contract

FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        # Git is the Kernel's state store, never a model's tool (ADR 0002).
        "git",
        # Package managers and their installers: dependencies are a Kernel change.
        "pip",
        "pip3",
        "uvx",
        "npm",
        "brew",
        "apt",
        # Network clients: no tool reaches the network.
        "curl",
        "wget",
        "ssh",
        "scp",
        "nc",
        # Utilities that delete or edit outside the file tool's write scope.
        "rm",
        "mv",
        "cp",
        "sed",
        "awk",
        "tee",
        "dd",
        "chmod",
        "vi",
        "vim",
        "nano",
        # Environment readers, which would print the provider keys.
        "env",
        "printenv",
        "sudo",
    }
)
"""The commands no shell tool may allow, whatever an Organism configuration says."""


FORBIDDEN_SUBCOMMANDS: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "uv": (
        ("add",),
        ("remove",),
        ("pip",),
        ("sync",),
        ("lock",),
        ("tool",),
        ("publish",),
        ("self",),
    ),
    "python": (("-m", "pip"),),
    "python3": (("-m", "pip"),),
}
"""Subcommands of an otherwise allowed command that no shell tool may run."""

DENIED_OPERATORS: tuple[str, ...] = ("|", "&&", "||", ";", ">", "<", "`", "$(")
"""Shell operators no command line may contain; the harness shell would run them."""


UNREADABLE_PATTERNS: tuple[str, ...] = (".env", ".git/**")
"""The paths no tool may read, as glob patterns for the tools that take patterns."""

SECRET_ENV_PATTERNS: tuple[str, ...] = ("*_API_KEY", "*TOKEN*", "*SECRET*")
"""Environment variable names a shell tool never passes on to a subprocess."""

NETWORK_ALLOWED = False
"""No tool reaches the network; only the human may grant it."""

_UNREADABLE_IN_COMMAND: tuple[tuple[str, re.Pattern[str]], ...] = (
    # `.env` as a whole token, a path segment, or inside a quoted string, but never
    # `.env.example`, which is a readable file of its own.
    (".env", re.compile(r"(?<![\w.])\.env(?![\w.])")),
    # `.git` as a token or a path prefix, but never `.gitignore`.
    (".git", re.compile(r"\.git(?:/|\b)")),
)


class PolicyError(ValueError):
    """A tool configuration exceeds the Policy Ceiling; the message names the value."""


class ToolConfig(Contract):
    """What one agent's tools may do, inside the ceiling."""

    files: bool = True
    write_globs: list[str] = Field(default_factory=list)
    shell_commands: list[str] = Field(default_factory=list)
    git_read: bool = False
    shell_timeout_s: int = 600


AGENT_UNWRITABLE_DIRS: tuple[str, ...] = ("evals",)
"""Writable for the Kernel, never for an agent's tool: the Kernel appends Target Cases from
approved Plans and the human writes Frontier Cases (spec, "the write scope")."""

RUNNER_COMMANDS: Mapping[str, tuple[str, ...]] = {"uv": ("run",)}
"""Commands whose named subcommand runs another command, which the ceiling checks in turn."""


def _inside_write_scope(glob: str) -> bool:
    """Whether `glob` stays inside the write-scope allowlist of `kernel.paths`.

    It does when it is one of the allowlist's own patterns, or when it narrows one of the
    writable directories.
    """
    return glob in writable_globs() or any(
        glob.startswith(f"{directory}/") for directory in WRITABLE_DIRS
    )


def validate_tool_config(config: ToolConfig) -> None:
    """Raise `PolicyError` naming the first value in `config` that exceeds the ceiling."""
    for command in config.shell_commands:
        if command.split() != [command]:
            raise PolicyError(f"shell command is not a single bare word: {command!r}")
        if command in FORBIDDEN_COMMANDS:
            raise PolicyError(f"shell command above the Policy Ceiling: {command!r}")
    for glob in config.write_globs:
        if not _inside_write_scope(glob):
            raise PolicyError(f"write glob outside the write scope: {glob!r}")
        if any(
            glob == f"{directory}/**" or glob.startswith(f"{directory}/")
            for directory in AGENT_UNWRITABLE_DIRS
        ):
            raise PolicyError(f"no agent writes under the eval datasets: {glob!r}")


def forbidden_reason(command: str) -> str | None:
    """Why the ceiling refuses this shell command line, or `None` when it is allowed.

    The Organism's shell wrapper calls this before every run, because the harness shell
    validates only the first token and has no path sandbox of its own.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        return f"command line does not parse as shell words: {error}"
    for operator in DENIED_OPERATORS:
        if operator in command:
            return f"denied shell operator: {operator}"
    for path, pattern in _UNREADABLE_IN_COMMAND:
        if pattern.search(command):
            return f"names an unreadable path: {path}"
    return _forbidden_tokens(tokens)


def _forbidden_tokens(tokens: list[str]) -> str | None:
    """The ceiling's verdict on one command's words, following `uv run` to the command it runs."""
    if not tokens:
        return None
    first, rest = tokens[0], tokens[1:]
    if first in FORBIDDEN_COMMANDS:
        return f"forbidden command: {first}"
    for sequence in FORBIDDEN_SUBCOMMANDS.get(first, ()):
        if tuple(rest[: len(sequence)]) == sequence:
            return f"forbidden subcommand: {' '.join((first, *sequence))}"
    if rest and rest[0] in RUNNER_COMMANDS.get(first, ()):
        inner = rest[1:]
        while inner and inner[0].startswith("-"):
            inner = inner[1:]
        return _forbidden_tokens(inner)
    return None
