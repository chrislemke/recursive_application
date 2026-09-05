"""The Protected Path rule, the write scope, and the repo layout, through `kernel.paths`.

Relative paths need no repository on disk; absolute paths use a root under `tmp_path`.
"""

from pathlib import Path

import pytest

from recursive_application.kernel.paths import (
    REPO_ROOT,
    ensure_ra_dirs,
    is_protected,
    is_writable,
    protected_globs,
    resolve_repo_root,
    writable_globs,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout root under `tmp_path`, so `tmp_path` itself is outside the repo."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return checkout


def test_a_kernel_file_is_protected_and_an_organism_file_is_not() -> None:
    assert is_protected("src/recursive_application/kernel/loop.py") is True
    assert is_protected("src/recursive_application/organism/agents.py") is False


@pytest.mark.parametrize(
    "path",
    [
        # The six protected directories, spelled as the directory itself.
        "src/recursive_application/kernel",
        "tests/kernel",
        ".claude",
        "docs",
        "thoughts",
        ".scratch",
        # The six protected files.
        "pyproject.toml",
        "uv.lock",
        ".env",
        ".env.example",
        ".gitignore",
        "CONTEXT.md",
        # Nested paths under protected directories.
        "docs/adr/0001-kernel-organism-split.md",
        "src/recursive_application/kernel/prompts/constitution.md",
        "tests/kernel/test_loop.py",
        # Dot-slash spellings.
        "./pyproject.toml",
        "./docs/adr/0001-kernel-organism-split.md",
        "./.claude/settings.json",
    ],
)
def test_every_entry_of_the_rule_is_protected(path: str) -> None:
    assert is_protected(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "src/recursive_application/organism/agents.py",
        "src/recursive_application/organism/prompts/planner.md",
        "tests/organism/test_agents.py",
        "evals/frontier/text-analysis.yaml",
        "wiki/index.md",
        "README.md",
    ],
)
def test_the_organism_paths_are_not_protected(path: str) -> None:
    assert is_protected(path) is False


def test_an_absolute_path_inside_the_repo_follows_the_rule(root: Path) -> None:
    assert is_protected(root / "docs" / "coding-guide.md", root=root) is True
    assert is_protected(root / "wiki" / "index.md", root=root) is False


def test_an_absolute_path_is_resolved_through_symlinks_before_the_rule_applies(
    tmp_path: Path, root: Path
) -> None:
    link = tmp_path / "link"
    link.symlink_to(root)

    assert is_protected(link / "wiki" / "index.md", root=root) is False
    assert is_protected(link / "docs" / "coding-guide.md", root=root) is True


def test_a_relative_path_through_a_symlink_follows_the_rule_for_its_target(root: Path) -> None:
    (root / "docs").mkdir()
    (root / "wiki").mkdir()
    (root / "wiki" / "link").symlink_to(root / "docs")

    assert is_protected("wiki/link/coding-guide.md", root=root) is True
    assert is_writable("wiki/link/coding-guide.md", root=root) is False


def test_an_absolute_path_outside_the_repo_is_protected(tmp_path: Path, root: Path) -> None:
    assert is_protected(tmp_path / "elsewhere" / "index.md", root=root) is True
    assert is_protected(Path("/etc/hosts"), root=root) is True


def test_protected_globs_render_directories_with_a_double_star_and_files_verbatim() -> None:
    globs = protected_globs()

    assert "docs/**" in globs
    assert "src/recursive_application/kernel/**" in globs
    assert "uv.lock" in globs


def test_ensure_ra_dirs_creates_the_runtime_directory_with_its_four_subdirectories(
    tmp_path: Path,
) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)

    assert ra_dir == tmp_path / ".ra"
    for name in ("traces", "runs", "tasks", "evals"):
        assert (tmp_path / ".ra" / name).is_dir()


def test_ensure_ra_dirs_is_idempotent(tmp_path: Path) -> None:
    first = ensure_ra_dirs(tmp_path)
    (first / "runs" / "keep.json").write_text("{}")

    second = ensure_ra_dirs(tmp_path)

    assert second == first
    assert (second / "runs" / "keep.json").read_text() == "{}"


def test_repo_root_holds_the_project_file_and_the_package() -> None:
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "src" / "recursive_application").is_dir()


def test_resolve_repo_root_honours_the_override_variable(tmp_path: Path) -> None:
    assert resolve_repo_root({"RA_REPO_ROOT": str(tmp_path)}) == tmp_path


def test_resolve_repo_root_finds_the_checkout_without_the_override() -> None:
    root = resolve_repo_root({})

    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "recursive_application").is_dir()


@pytest.mark.parametrize("path", ["thoughts/shared/plans/x.md", ".scratch/x/spec.md"])
def test_the_plans_and_scratch_directories_are_protected(path: str) -> None:
    assert is_protected(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "wiki/index.md",
        "evals/frontier/a.yaml",
        "tests/organism/test_x.py",
        "src/recursive_application/organism/agents.py",
        "README.md",
    ],
)
def test_the_write_scope_allows_the_organism_the_evals_the_wiki_and_the_readme(
    path: str,
) -> None:
    assert is_writable(path) is True


@pytest.mark.parametrize(
    "path",
    [".venv/lib/x.py", ".ra/runs/x.json", "pyproject.toml", "docs/coding-guide.md"],
)
def test_everything_outside_the_write_scope_is_read_only(path: str) -> None:
    assert is_writable(path) is False


def test_a_path_outside_the_repo_is_never_writable(tmp_path: Path, root: Path) -> None:
    assert is_writable(tmp_path / "elsewhere" / "README.md", root=root) is False
    assert is_writable("../README.md", root=root) is False


def test_writable_globs_render_directories_with_a_double_star_and_files_verbatim() -> None:
    globs = writable_globs()

    assert "wiki/**" in globs
    assert "README.md" in globs
