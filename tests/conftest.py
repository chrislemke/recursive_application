"""Shared fixtures for the Kernel and Organism test suites.

Protected Path. Three guarantees for every test in the session:

1. Real model requests are disabled, so an agent that is not given a `TestModel`
   or `FunctionModel` fails loudly instead of reaching the network.
2. The process environment is clean of provider keys, Logfire keys, and every
   `RA_*` variable before each test, and restored afterwards.
3. `git_repo` provides a real git repository in a temporary directory with commit
   signing disabled, so an unattended commit never blocks on a GUI signer.
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_ai import models

models.ALLOW_MODEL_REQUESTS = False

_SECRET_KEYS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LOGFIRE_TOKEN")
_RA_PREFIX = "RA_"


@pytest.fixture(autouse=True)
def _clean_environment() -> Iterator[None]:
    """Remove provider, Logfire, and `RA_*` variables, then restore the environment."""
    saved = dict(os.environ)
    for key in list(os.environ):
        if key in _SECRET_KEYS or key.startswith(_RA_PREFIX):
            del os.environ[key]
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A real repository with signing off, an author, one commit, and `.ra/` ignored."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "tag.gpgsign", "false")
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("# test\n")
    (root / ".gitignore").write_text(".ra/\n")
    _git(root, "add", "--all")
    _git(root, "commit", "--quiet", "--message", "initial")
    return root
