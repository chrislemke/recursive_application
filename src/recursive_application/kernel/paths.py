"""The Protected Path rule, the write scope, and the repo layout.

The single source of truth for which paths the Organism may never modify (ADR 0001) and
which paths a tool may write to. Every other Kernel module asks here instead of keeping
its own list.
"""

import os
from collections.abc import Mapping
from pathlib import Path, PurePath, PurePosixPath

REPO_ROOT_VARIABLE = "RA_REPO_ROOT"
"""The environment variable that overrides where the checkout is."""


def resolve_repo_root(env: Mapping[str, str] | None = None) -> Path:
    """`RA_REPO_ROOT` from `env` (default `os.environ`) if set, else the checkout of this package.

    The checkout is the ancestor of this package holding `pyproject.toml` and `src/`.
    """
    override = (os.environ if env is None else env).get(REPO_ROOT_VARIABLE)
    if override:
        return Path(override).resolve()
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "pyproject.toml").is_file() and (ancestor / "src").is_dir():
            return ancestor
    raise RuntimeError("no checkout with pyproject.toml and src/ above this package")


REPO_ROOT: Path = resolve_repo_root()
"""The checkout the Kernel operates on, resolved once at import."""

RA_DIRNAME = ".ra"
"""The gitignored runtime directory under the repo root."""

TRACES_DIRNAME = "traces"
"""Runtime subdirectory: one JSONL Trace Store file per run."""

RUNS_DIRNAME = "runs"
"""Runtime subdirectory: one Run Record per run."""

TASKS_DIRNAME = "tasks"
"""Runtime subdirectory: per-run Target Cases and task output."""

EVALS_DIRNAME = "evals"
"""Runtime subdirectory: persisted eval reports and the latest pointer."""

RA_SUBDIRS: tuple[str, ...] = (TRACES_DIRNAME, RUNS_DIRNAME, TASKS_DIRNAME, EVALS_DIRNAME)
"""What `ensure_ra_dirs` creates inside the runtime directory."""

PROTECTED_DIRS: tuple[str, ...] = (
    "src/recursive_application/kernel",
    "tests/kernel",
    ".claude",
    "docs",
    "thoughts",
    ".scratch",
)
"""Directories the Organism may never modify, repo-relative POSIX."""

PROTECTED_FILES: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
    ".env",
    ".env.example",
    ".gitignore",
    "CONTEXT.md",
)
"""Files the Organism may never modify, repo-relative POSIX."""

WRITABLE_DIRS: tuple[str, ...] = (
    "src/recursive_application/organism",
    "tests/organism",
    "evals",
    "wiki",
)
"""The write-scope allowlist's directories: the only places a tool may write under."""

WRITABLE_FILES: tuple[str, ...] = ("README.md",)
"""The write-scope allowlist's files."""


def _relative_to_root(path: str | PurePath, root: Path) -> PurePosixPath | None:
    """`path` as a repo-relative POSIX path, or `None` when it leaves `root`.

    A relative path is taken as relative to `root`. Every path is resolved through symlinks
    and `..` before it is compared against the resolved `root`, so a link that points out of
    the checkout, or from one part of it into another, follows the rule of its target.
    """
    resolved = (root / Path(path)).resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        return None
    return PurePosixPath(resolved.relative_to(resolved_root).as_posix())


def _matches(relative: PurePosixPath, directories: tuple[str, ...], files: tuple[str, ...]) -> bool:
    """Whether `relative` is one of `files` or sits under one of `directories`."""
    return str(relative) in files or any(
        relative.is_relative_to(directory) for directory in directories
    )


def is_protected(path: str | PurePath, root: Path = REPO_ROOT) -> bool:
    """True when the Organism may never modify `path`; a path outside `root` counts as protected."""
    relative = _relative_to_root(path, root)
    if relative is None:
        return True
    return _matches(relative, PROTECTED_DIRS, PROTECTED_FILES)


def protected_globs() -> list[str]:
    """The Protected Path rule as glob patterns: directories as `<dir>/**`, files verbatim."""
    return [f"{directory}/**" for directory in PROTECTED_DIRS] + list(PROTECTED_FILES)


def is_writable(path: str | PurePath, root: Path = REPO_ROOT) -> bool:
    """True only when `path` is inside the write-scope allowlist; outside `root` is never writable.

    Everything else is read-only for every tool, gitignored paths such as `.venv/` and `.ra/`
    included, because a write there never reaches `git diff`.
    """
    relative = _relative_to_root(path, root)
    if relative is None:
        return False
    return _matches(relative, WRITABLE_DIRS, WRITABLE_FILES)


def writable_globs() -> list[str]:
    """The write-scope allowlist as glob patterns: directories as `<dir>/**`, files verbatim."""
    return [f"{directory}/**" for directory in WRITABLE_DIRS] + list(WRITABLE_FILES)


def ensure_ra_dirs(root: Path = REPO_ROOT) -> Path:
    """Create `.ra/` under `root` with its subdirectories, idempotently; return the `.ra` path."""
    ra_dir = root / RA_DIRNAME
    for name in RA_SUBDIRS:
        (ra_dir / name).mkdir(parents=True, exist_ok=True)
    return ra_dir
