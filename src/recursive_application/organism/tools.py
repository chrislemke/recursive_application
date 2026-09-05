"""The tool configurations of the Organism's agents, and the toolsets they build.

The Organism owns which commands and paths each agent gets; the Kernel's Policy Ceiling
(`kernel/policy.py`) is the limit every configuration here is validated against.
"""

import fnmatch
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai.tools import RunContext, Tool
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset, ToolsetTool, WrapperToolset
from pydantic_ai_harness import FileSystem, Shell

from recursive_application.kernel.git import GitError, Repo
from recursive_application.kernel.paths import is_writable
from recursive_application.kernel.policy import (
    DENIED_OPERATORS,
    SECRET_ENV_PATTERNS,
    UNREADABLE_PATTERNS,
    ToolConfig,
    forbidden_reason,
)

SHELL_COMMANDS: tuple[str, ...] = (
    "uv",
    "pytest",
    "python",
    "ruff",
    "ty",
    "rg",
    "grep",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "diff",
)
"""The first tokens a coding agent's shell accepts: the project's checks and read-only utilities."""

ROLE_TOOL_CONFIGS: Mapping[str, ToolConfig] = {
    "triage": ToolConfig(files=False),
    "planner": ToolConfig(git_read=True),
    "test_writer": ToolConfig(
        write_globs=["tests/organism/**"], shell_commands=list(SHELL_COMMANDS)
    ),
    "implementer": ToolConfig(
        write_globs=["src/recursive_application/organism/**", "README.md"],
        shell_commands=list(SHELL_COMMANDS),
        git_read=True,
    ),
    # The Worker reads but never edits code, and the repo-history Frontier Cases stay red
    # until a Growth Loop exposes git to an Act-phase agent.
    "worker": ToolConfig(),
    "reviewer": ToolConfig(git_read=True),
    "librarian": ToolConfig(write_globs=["wiki/**"]),
}
"""The tool configuration of each required role, keyed by its registry name."""


WRITING_TOOL_NAMES: frozenset[str] = frozenset({"write_file", "edit_file", "create_directory"})
"""The harness file tools that write, and so pass their path through the write scope."""

RUNNING_TOOL_NAMES: frozenset[str] = frozenset({"run_command", "start_command"})
"""The shell tools that start a process, and so pass their command line through the ceiling."""


def _repo_relative(path: str, root: Path) -> str | None:
    """`path` as a POSIX path relative to `root`, or `None` when it leaves `root`.

    Canonicalised first, the way the harness canonicalises before matching its own patterns,
    so `..`, `./` and a symlink cannot spell a path past the write scope.
    """
    resolved = (root / path).resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        return None
    return resolved.relative_to(resolved_root).as_posix()


@dataclass
class _ScopedFileToolset(WrapperToolset[Any]):
    """The harness file tools with this agent's write scope applied to every write.

    The harness gates writes by pattern lists that also filter its directory walks, so the
    scope is enforced here instead, leaving the agent free to read the whole checkout.
    """

    root: Path
    write_globs: tuple[str, ...]

    def _in_write_scope(self, path: str) -> bool:
        """Whether `path` is inside both this agent's globs and the Kernel's write scope.

        A directory on the way to one of the globs counts too, so an agent scoped to
        `<dir>/**` can create `<dir>` itself.
        """
        relative = _repo_relative(path, self.root)
        if relative is None:
            return False
        return is_writable(relative, self.root) and any(
            fnmatch.fnmatch(relative, glob) or glob.startswith(f"{relative}/")
            for glob in self.write_globs
        )

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        """Refuse a write outside the scope, naming the path, instead of performing it."""
        if name in WRITING_TOOL_NAMES:
            path = str(tool_args.get("path", ""))
            if not self._in_write_scope(path):
                return f"refused: {path} is outside this agent's write scope"
        return await super().call_tool(name, tool_args, ctx, tool)


@dataclass
class _CeilingShellToolset(WrapperToolset[Any]):
    """The harness shell with the Policy Ceiling applied to the command line first.

    The harness validates only the first token and sandboxes no path, so a subcommand, an
    operator, or a read of the environment file would otherwise walk through its allowlist.
    """

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        """Refuse a command line the ceiling forbids, naming the reason, instead of running it."""
        if name in RUNNING_TOOL_NAMES:
            reason = forbidden_reason(str(tool_args.get("command", "")))
            if reason is not None:
                return f"refused: {reason}"
        return await super().call_tool(name, tool_args, ctx, tool)


def _git_reply(read: Callable[[], str]) -> str:
    """The text a git read helper produced, or the text of the `GitError` it raised.

    A refusal reaches the model as an ordinary reply, so the agent can correct itself
    instead of the run failing.
    """
    try:
        return read()
    except GitError as error:
        return str(error)


def _git_toolset(root: Path) -> FunctionToolset[Any]:
    """The five read-only git tools over the working copy at `root`."""
    repo = Repo(root)

    def git_log(n: int = 20, path: str | None = None) -> str:
        """Read the commit history, one line per commit, newest first."""
        return _git_reply(lambda: repo.log(n, path))

    def git_show(ref: str = "HEAD") -> str:
        """Read one commit: its header, its stat, and its patch."""
        return _git_reply(lambda: repo.show(ref))

    def git_blame(path: str) -> str:
        """Read who last changed each line of a file."""
        return _git_reply(lambda: repo.blame(path))

    def git_status() -> str:
        """Read the short-form status of the working tree."""
        return _git_reply(repo.status)

    def git_diff(ref: str = "HEAD", path: str | None = None) -> str:
        """Read the working tree as a diff against a commit."""
        return _git_reply(lambda: repo.diff(ref, path))

    toolset: FunctionToolset[Any] = FunctionToolset()
    toolset.add_function(git_log)
    toolset.add_function(git_show)
    toolset.add_function(git_blame)
    toolset.add_function(git_status)
    toolset.add_function(git_diff)
    return toolset


def toolsets_for(config: ToolConfig, root: Path) -> list[AbstractToolset[Any]]:
    """The toolsets `config` grants an agent, all rooted at `root`."""
    toolsets: list[AbstractToolset[Any]] = []
    if config.files:
        files = FileSystem(
            root_dir=root,
            denied_patterns=list(UNREADABLE_PATTERNS),
            read_only=not config.write_globs,
        )
        toolset = files.get_toolset()
        if config.write_globs:
            toolset = _ScopedFileToolset(
                wrapped=toolset, root=root, write_globs=tuple(config.write_globs)
            )
        toolsets.append(toolset)
    if config.shell_commands:
        shell = Shell(
            cwd=root,
            allowed_commands=list(config.shell_commands),
            denied_operators=list(DENIED_OPERATORS),
            default_timeout=config.shell_timeout_s,
            denied_env_patterns=list(SECRET_ENV_PATTERNS),
        )
        toolsets.append(_CeilingShellToolset(wrapped=shell.get_toolset()))
    if config.git_read:
        toolsets.append(_git_toolset(root))
    return toolsets


@dataclass(frozen=True)
class ToolDescription:
    """One tool an agent has, as the Capability Inventory renders it."""

    name: str
    description: str


_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
_SENTENCE_END = re.compile(r"(?<!\b[A-Za-z])\.(?=\s|$)")


def _first_sentence(description: str | None) -> str:
    """The first sentence of a tool's description, without the docstring's return schema."""
    if not description:
        return ""
    summary = _SUMMARY.search(description)
    text = (summary.group(1) if summary else description).strip()
    # Not every full stop ends a sentence: "(e.g. a server)" holds two that do not.
    stop = _SENTENCE_END.search(text)
    return text if stop is None else text[: stop.end()]


def _function_tools(toolset: AbstractToolset[Any]) -> Mapping[str, Tool[Any]]:
    """The tools a toolset holds; a wrapper is followed down to the toolset it delegates to."""
    while isinstance(toolset, WrapperToolset):
        toolset = toolset.wrapped
    return toolset.tools if isinstance(toolset, FunctionToolset) else {}


def describe_tools(config: ToolConfig, root: Path) -> list[ToolDescription]:
    """Every tool `toolsets_for(config, root)` exposes, sorted by name.

    The Capability Inventory renders this, so it names the tools an agent really has and
    leaves out the writing tools an agent without a write scope was never offered.
    """
    described = [
        ToolDescription(name=name, description=_first_sentence(tool.description))
        for toolset in toolsets_for(config, root)
        for name, tool in _function_tools(toolset).items()
        if config.write_globs or name not in WRITING_TOOL_NAMES
    ]
    return sorted(described, key=lambda tool: tool.name)
