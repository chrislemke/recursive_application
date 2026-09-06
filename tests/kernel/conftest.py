"""Fixtures the Kernel's Loop tests share: the temporary checkout laid out like the real one."""

import shutil
from pathlib import Path

import pytest

from recursive_application.kernel.git import Repo
from recursive_application.kernel.paths import REPO_ROOT, ensure_ra_dirs

TRACKED_DIRS: tuple[str, ...] = ("evals", "wiki")
"""The tracked directories a Loop test's checkout copies from the real one."""

TRACKED_FILES: tuple[str, ...] = ("README.md",)
"""The tracked files a Loop test's checkout copies from the real one."""

ORGANISM_STUB = "src/recursive_application/organism/__init__.py"
"""The one Organism file a Loop test's checkout holds, so the tree has an editable package."""


@pytest.fixture
def checkout(git_repo: Path) -> Path:
    """The temporary repository laid out like the real checkout, with `.ra/` ready and ignored."""
    for name in TRACKED_DIRS:
        shutil.copytree(REPO_ROOT / name, git_repo / name)
    for name in TRACKED_FILES:
        shutil.copy(REPO_ROOT / name, git_repo / name)
    stub = git_repo / ORGANISM_STUB
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text('"""The Organism package, stubbed for the Loop\'s tests."""\n')
    Repo(git_repo).commit_all("lay the checkout out")
    ensure_ra_dirs(git_repo)
    return git_repo
