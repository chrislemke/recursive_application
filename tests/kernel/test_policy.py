"""The Policy Ceiling, through `kernel.policy`.

In-process logic only: a tool configuration is data, and the ceiling is a Kernel constant.
"""

import pytest

from recursive_application.kernel.policy import (
    PolicyError,
    ToolConfig,
    forbidden_reason,
    validate_tool_config,
)


def test_a_configuration_inside_the_ceiling_validates() -> None:
    assert validate_tool_config(ToolConfig()) is None
    assert (
        validate_tool_config(
            ToolConfig(write_globs=["tests/organism/**"], shell_commands=["uv", "pytest"])
        )
        is None
    )


@pytest.mark.parametrize(
    "command",
    [
        # Git is never on a shell allowlist (ADR 0002).
        "git",
        # A recursive delete, a network client, an installer, an editing utility.
        "rm",
        "curl",
        "pip",
        "sed",
        # Not a single bare word, so the allowlist could never match it.
        "uv run",
    ],
)
def test_a_shell_command_above_the_ceiling_is_refused_by_name(command: str) -> None:
    with pytest.raises(PolicyError) as refusal:
        validate_tool_config(ToolConfig(shell_commands=[command]))
    assert command in str(refusal.value)


@pytest.mark.parametrize(
    "glob",
    [
        # Protected Paths.
        "docs/**",
        "src/recursive_application/kernel/**",
        # Gitignored, so a write there would never reach the git diff.
        ".ra/**",
        ".venv/**",
        # Wider than the one writable directory below it.
        "tests/**",
    ],
)
def test_a_write_glob_outside_the_write_scope_is_refused_by_name(glob: str) -> None:
    with pytest.raises(PolicyError) as refusal:
        validate_tool_config(ToolConfig(write_globs=[glob]))
    assert glob in str(refusal.value)


@pytest.mark.parametrize("glob", ["wiki/pages/**", "README.md"])
def test_a_write_glob_inside_the_write_scope_validates(glob: str) -> None:
    assert validate_tool_config(ToolConfig(write_globs=[glob])) is None


@pytest.mark.parametrize("command", ["uv run pytest", 'python -c "print(1)"'])
def test_a_command_the_ceiling_allows_has_no_reason(command: str) -> None:
    assert forbidden_reason(command) is None


@pytest.mark.parametrize(
    ("command", "named"),
    [
        # A forbidden subcommand of an allowed first token.
        ("uv add requests", "uv add"),
        ("python -m pip install x", "pip"),
        # A forbidden first token.
        ("git status", "git"),
        # Denied operators, which the harness shell would otherwise run through `/bin/sh`.
        ("cat a | tee b", "|"),
        ("ls; rm -rf /", ";"),
        ("cat $(ls)", "$("),
    ],
)
def test_a_command_above_the_ceiling_reports_the_offending_part(command: str, named: str) -> None:
    reason = forbidden_reason(command)
    assert reason is not None
    assert named in reason


@pytest.mark.parametrize(
    ("command", "named"),
    [
        # The environment file, as a whole token and inside a quoted string.
        ("cat .env", ".env"),
        ("""python -c "open('.env').read()" """.strip(), ".env"),
        # The git directory, as a path prefix and as a whole token.
        ("cat .git/config", ".git"),
        ("ls .git", ".git"),
    ],
)
def test_a_command_reading_an_unreadable_path_reports_it(command: str, named: str) -> None:
    reason = forbidden_reason(command)
    assert reason is not None
    assert named in reason


@pytest.mark.parametrize("command", ["cat .gitignore", "cat .env.example"])
def test_a_readable_neighbour_of_an_unreadable_path_has_no_reason(command: str) -> None:
    assert forbidden_reason(command) is None


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("uv run git status", "git"),
        ("uv run rm -rf /", "rm"),
        ("uv run --no-sync python -m pip install x", "pip"),
    ],
)
def test_uv_run_cannot_smuggle_a_forbidden_command_past_the_ceiling(
    command: str, reason: str
) -> None:
    found = forbidden_reason(command)

    assert found is not None
    assert reason in found


def test_uv_run_of_an_allowed_command_stays_allowed() -> None:
    assert forbidden_reason("uv run --no-sync pytest tests/organism -q") is None


def test_no_agent_may_be_scoped_to_write_under_the_eval_datasets() -> None:
    with pytest.raises(PolicyError) as refusal:
        validate_tool_config(ToolConfig(write_globs=["evals/**"]))

    assert "evals/**" in str(refusal.value)
