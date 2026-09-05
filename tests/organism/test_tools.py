"""The Organism's tool configurations, through `organism.tools`.

Every configuration is checked against the Kernel's Policy Ceiling, and every toolset is
driven through one real tool call on a temporary repository layout.
"""

import re
from pathlib import Path

import pytest

from recursive_application.kernel.policy import PolicyError, ToolConfig, validate_tool_config
from recursive_application.organism.tools import (
    ROLE_TOOL_CONFIGS,
    SHELL_COMMANDS,
    describe_tools,
    toolsets_for,
)

from .conftest import call_tool

REQUIRED_ROLES = (
    "triage",
    "planner",
    "test_writer",
    "implementer",
    "worker",
    "reviewer",
    "librarian",
)


def test_every_required_role_has_a_configuration_inside_the_ceiling() -> None:
    assert sorted(ROLE_TOOL_CONFIGS) == sorted(REQUIRED_ROLES)
    for config in ROLE_TOOL_CONFIGS.values():
        assert validate_tool_config(config) is None


def test_each_role_writes_only_where_the_spec_grants_it() -> None:
    write_globs = {role: config.write_globs for role, config in ROLE_TOOL_CONFIGS.items()}
    assert write_globs == {
        "triage": [],
        "planner": [],
        "test_writer": ["tests/organism/**"],
        "implementer": ["src/recursive_application/organism/**", "README.md"],
        "worker": [],
        "reviewer": [],
        "librarian": ["wiki/**"],
    }
    assert ROLE_TOOL_CONFIGS["triage"].files is False


def test_only_the_two_coding_roles_get_a_shell_and_it_allows_the_checks() -> None:
    assert SHELL_COMMANDS == (
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
    with_shell = {role for role, config in ROLE_TOOL_CONFIGS.items() if config.shell_commands}
    assert with_shell == {"test_writer", "implementer"}
    for role in with_shell:
        assert ROLE_TOOL_CONFIGS[role].shell_commands == list(SHELL_COMMANDS)
        # A full pytest run has to fit inside one tool call.
        assert ROLE_TOOL_CONFIGS[role].shell_timeout_s == 600


def test_only_the_three_reading_roles_get_the_git_tools() -> None:
    with_git = {role for role, config in ROLE_TOOL_CONFIGS.items() if config.git_read}
    assert with_git == {"planner", "implementer", "reviewer"}


@pytest.mark.parametrize(
    ("command", "named"),
    [
        ("git status", "git"),
        ("sed -i s/a/b/ x", "sed"),
        ("uv add requests", "uv add"),
        ("ls | cat", "|"),
    ],
)
def test_the_shell_refuses_a_command_above_the_ceiling(
    root: Path, command: str, named: str
) -> None:
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root), "run_command", {"command": command}
    )
    assert reply.startswith("refused:")
    assert named in reply


def test_the_shell_runs_a_command_the_allowlist_permits(root: Path) -> None:
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root),
        "run_command",
        {"command": 'python -c "print(6*7)"'},
    )
    assert "42" in reply


def test_the_test_writer_writes_under_the_organism_tests(root: Path) -> None:
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["test_writer"], root),
        "write_file",
        {"path": "tests/organism/test_new.py", "content": "def test_new() -> None: ...\n"},
    )
    assert "refused" not in reply
    assert (root / "tests/organism/test_new.py").read_text() == "def test_new() -> None: ...\n"


def test_the_test_writer_is_refused_outside_the_organism_tests(root: Path) -> None:
    toolsets = toolsets_for(ROLE_TOOL_CONFIGS["test_writer"], root)
    written = call_tool(
        toolsets,
        "write_file",
        {"path": "src/recursive_application/organism/x.py", "content": "x = 1\n"},
    )
    assert written.startswith("refused:")
    assert "src/recursive_application/organism/x.py" in written
    assert not (root / "src/recursive_application/organism/x.py").exists()

    edited = call_tool(
        toolsets,
        "edit_file",
        {"path": "README.md", "old_text": "# checkout", "new_text": "# hijacked"},
    )
    assert edited.startswith("refused:")
    assert (root / "README.md").read_text() == "# checkout\n"


def test_the_implementer_writes_the_organism_package_and_the_readme_only(root: Path) -> None:
    toolsets = toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root)
    refused = call_tool(
        toolsets, "write_file", {"path": "tests/organism/t.py", "content": "x = 1\n"}
    )
    assert refused.startswith("refused:")
    assert not (root / "tests/organism/t.py").exists()

    call_tool(
        toolsets,
        "write_file",
        {"path": "src/recursive_application/organism/new.py", "content": "new = 1\n"},
    )
    call_tool(toolsets, "write_file", {"path": "README.md", "content": "# rewritten\n"})
    assert (root / "src/recursive_application/organism/new.py").read_text() == "new = 1\n"
    assert (root / "README.md").read_text() == "# rewritten\n"


def test_the_librarian_writes_the_wiki_only(root: Path) -> None:
    toolsets = toolsets_for(ROLE_TOOL_CONFIGS["librarian"], root)
    call_tool(
        toolsets,
        "write_file",
        {"path": "wiki/pages/lessons/a.md", "content": "# a lesson\n"},
    )
    assert (root / "wiki/pages/lessons/a.md").read_text() == "# a lesson\n"

    refused = call_tool(toolsets, "write_file", {"path": "README.md", "content": "# hijacked\n"})
    assert refused.startswith("refused:")
    assert (root / "README.md").read_text() == "# checkout\n"


@pytest.mark.parametrize("role", ["planner", "worker", "reviewer"])
@pytest.mark.parametrize("tool", ["write_file", "edit_file", "create_directory"])
def test_a_reading_role_is_offered_no_writing_file_tool(root: Path, role: str, tool: str) -> None:
    call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS[role], root),
        tool,
        {"path": "README.md", "content": "# hijacked\n"},
    )
    assert tool not in {
        described.name for described in describe_tools(ROLE_TOOL_CONFIGS[role], root)
    }
    assert (root / "README.md").read_text() == "# checkout\n"


def test_triage_gets_no_tools_at_all(root: Path) -> None:
    assert toolsets_for(ROLE_TOOL_CONFIGS["triage"], root) == []


@pytest.mark.parametrize("path", [".venv/lib/x.py", ".ra/runs/x.json"])
def test_no_tool_writes_where_the_git_diff_would_not_see_it(root: Path, path: str) -> None:
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root),
        "write_file",
        {"path": path, "content": "x\n"},
    )
    assert reply.startswith("refused:")
    assert not (root / path).exists()


def test_the_file_tool_denies_the_environment_file_and_the_git_directory(root: Path) -> None:
    toolsets = toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root)
    environment = call_tool(toolsets, "read_file", {"path": ".env"})
    assert "denied" in environment
    assert "sk-or-secret" not in environment
    assert "denied" in call_tool(toolsets, "read_file", {"path": ".git/HEAD"})
    assert "# checkout" in call_tool(toolsets, "read_file", {"path": "README.md"})


def test_the_git_tools_read_the_repository(git_repo: Path) -> None:
    toolsets = toolsets_for(ROLE_TOOL_CONFIGS["planner"], git_repo)
    assert "initial" in call_tool(toolsets, "git_log", {})
    assert "README.md" in call_tool(toolsets, "git_show", {})
    assert "# test" in call_tool(toolsets, "git_blame", {"path": "README.md"})

    (git_repo / "README.md").write_text("# edited\n")
    assert "README.md" in call_tool(toolsets, "git_status", {})
    assert "-# test" in call_tool(toolsets, "git_diff", {"path": "README.md"})


def test_a_git_tool_reports_a_refused_argument_as_its_reply(git_repo: Path) -> None:
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["planner"], git_repo), "git_log", {"path": "--all"}
    )
    assert "refusing argument that looks like a git option" in reply


def test_the_shell_never_passes_the_provider_key_to_a_subprocess(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    reply = call_tool(
        toolsets_for(ROLE_TOOL_CONFIGS["implementer"], root),
        "run_command",
        {
            "command": (
                "python -c \"print(__import__('os').environ.get('OPENROUTER_API_KEY', 'unset'))\""
            )
        },
    )
    assert "unset" in reply
    assert "sk-or-test" not in reply


def test_a_specialist_writes_only_where_its_own_configuration_names(root: Path) -> None:
    specialist = ToolConfig(
        write_globs=["src/recursive_application/organism/specialists/**"],
        shell_commands=["uv", "pytest"],
    )
    assert validate_tool_config(specialist) is None

    (root / "src/recursive_application/organism/specialists").mkdir()
    toolsets = toolsets_for(specialist, root)
    call_tool(
        toolsets,
        "write_file",
        {"path": "src/recursive_application/organism/specialists/s.py", "content": "s = 1\n"},
    )
    assert (root / "src/recursive_application/organism/specialists/s.py").read_text() == "s = 1\n"

    refused = call_tool(
        toolsets,
        "write_file",
        {"path": "src/recursive_application/organism/other.py", "content": "other = 1\n"},
    )
    assert refused.startswith("refused:")
    assert not (root / "src/recursive_application/organism/other.py").exists()


def test_a_specialist_configuration_above_the_ceiling_is_refused_by_name() -> None:
    with pytest.raises(PolicyError) as refusal:
        validate_tool_config(ToolConfig(write_globs=["evals/**"], shell_commands=["curl"]))
    assert "curl" in str(refusal.value)


def test_the_implementer_is_described_by_the_tools_it_really_has(root: Path) -> None:
    described = describe_tools(ROLE_TOOL_CONFIGS["implementer"], root)
    descriptions = {tool.name: tool.description for tool in described}
    assert {"write_file", "run_command", "git_log"} <= set(descriptions)
    assert all(descriptions.values())
    assert [tool.name for tool in described] == [
        "check_command",
        "create_directory",
        "edit_file",
        "file_info",
        "find_files",
        "git_blame",
        "git_diff",
        "git_log",
        "git_show",
        "git_status",
        "list_directory",
        "read_file",
        "run_command",
        "search_files",
        "start_command",
        "stop_command",
        "write_file",
    ]
    # A whole first sentence, never one cut short at an abbreviation such as "(e.g.".
    assert not [name for name, text in descriptions.items() if re.search(r"\b[a-z]\.$", text)]


def test_a_read_only_agent_and_a_toolless_agent_are_described_as_they_are(root: Path) -> None:
    worker = {tool.name for tool in describe_tools(ROLE_TOOL_CONFIGS["worker"], root)}
    assert "read_file" in worker
    assert "write_file" not in worker
    assert describe_tools(ROLE_TOOL_CONFIGS["triage"], root) == []


def test_a_specialist_may_create_the_directory_its_own_scope_names(root: Path) -> None:
    config = ToolConfig(
        write_globs=["src/recursive_application/organism/specialists/**"],
        shell_commands=["uv", "pytest"],
    )
    toolsets = toolsets_for(config, root)

    call_tool(
        toolsets, "create_directory", {"path": "src/recursive_application/organism/specialists"}
    )
    reply = call_tool(
        toolsets, "create_directory", {"path": "src/recursive_application/organism/other"}
    )

    assert (root / "src/recursive_application/organism/specialists").is_dir()
    assert "refused" in reply
    assert not (root / "src/recursive_application/organism/other").exists()
