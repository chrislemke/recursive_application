"""Git as the state store (ADR 0002).

The Kernel drives git through fixed argument lists and never through a shell. Nothing here
pushes or signs, and `git` itself is never exposed to a model: the read helpers on `Repo`
are what the Organism's git tools call.
"""

import subprocess
from pathlib import Path

_READ_LIMIT = 20_000
_KERNEL_IDENTITY = ("-c", "user.name=ra Kernel", "-c", "user.email=ra@localhost")


class GitError(RuntimeError):
    """A git invocation failed; the message carries git's stderr."""


def _refuse_option(argument: str) -> None:
    """Reject a `ref` or `path` that git would read as an option, before git runs."""
    if argument.startswith("-"):
        raise GitError(f"refusing argument that looks like a git option: {argument!r}")


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n[truncated: {omitted} more characters]"


class Repo:
    """One working copy, addressed by its root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _run(self, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=False
        )
        if result.returncode not in ok:
            said = result.stderr.strip() or result.stdout.strip()
            raise GitError(said or f"git {' '.join(args)} exited {result.returncode}")
        return result

    def _read(self, *args: str) -> str:
        """Run a read helper and cut its output at the read limit."""
        return _truncate(self._run(*args).stdout, _READ_LIMIT)

    def is_repo(self) -> bool:
        """Whether `root` is the top level of a git working copy."""
        try:
            top = self._run("rev-parse", "--show-toplevel").stdout.strip()
        except GitError:
            return False
        return Path(top).resolve() == self.root.resolve()

    def has_commits(self) -> bool:
        """Whether HEAD points at a commit."""
        try:
            self._run("rev-parse", "--verify", "--quiet", "HEAD")
        except GitError:
            return False
        return True

    def head_sha(self) -> str:
        """The commit HEAD points at; raises `GitError` when there is none."""
        return self._run("rev-parse", "--verify", "HEAD").stdout.strip()

    def is_clean(self) -> bool:
        """Whether the working tree and index match HEAD; ignored files do not count."""
        return not self.changed_paths()

    def changed_paths(self) -> list[str]:
        """Modified, staged, deleted, renamed (both names) and untracked paths, sorted.

        Paths are repo-relative POSIX; ignored files are excluded and untracked files inside
        an untracked directory are listed one by one.
        """
        output = self._run("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
        fields = output.split("\0")
        paths: set[str] = set()
        index = 0
        while index < len(fields) and fields[index]:
            entry = fields[index]
            status, path = entry[:2], entry[3:]
            paths.add(path)
            if "R" in status or "C" in status:
                index += 1
                paths.add(fields[index])
            index += 1
        return sorted(paths)

    def diff_text(self, max_chars: int = 20_000) -> str:
        """The working tree against HEAD, with untracked files rendered as additions.

        Neither the index nor the working tree is touched; past `max_chars` the text is cut
        and ends in a visible marker.
        """
        parts = [self._run("diff", "HEAD", "--").stdout]
        untracked = self._run("ls-files", "--others", "--exclude-standard", "-z").stdout
        for path in filter(None, untracked.split("\0")):
            parts.append(self._run("diff", "--no-index", "--", "/dev/null", path, ok=(0, 1)).stdout)
        return _truncate("".join(parts), max_chars)

    def commit_all(self, message: str) -> str:
        """Stage everything and commit it as `ra Kernel <ra@localhost>`, unsigned.

        Signing is switched off on the command line so the commit never blocks on a signer,
        whatever the global or repository configuration says. Returns the new sha.
        """
        self._run("add", "--all")
        self._run(
            "-c",
            "commit.gpgsign=false",
            *_KERNEL_IDENTITY,
            "commit",
            "--quiet",
            f"--message={message}",
        )
        return self.head_sha()

    def log(self, n: int = 20, path: str | None = None) -> str:
        """One line per commit, newest first, optionally limited to `path`."""
        paths = [path] if path is not None else []
        for argument in paths:
            _refuse_option(argument)
        return self._read("log", "--oneline", f"--max-count={n}", "--", *paths)

    def show(self, ref: str = "HEAD") -> str:
        """Header, stat and patch of one commit."""
        _refuse_option(ref)
        return self._read("show", "--stat", "--patch", ref, "--")

    def reset_hard_clean(self) -> None:
        """Undo a rejected Iteration: `reset --hard HEAD`, then `clean -fd`.

        Ignored files such as the runtime directory `.ra/` survive because `-x` is not passed.
        """
        self._run("reset", "--hard", "HEAD", "--quiet")
        self._run("clean", "-fd", "--quiet")

    def blame(self, path: str) -> str:
        """Who last changed each line of `path`."""
        _refuse_option(path)
        return self._read("blame", "--", path)

    def status(self) -> str:
        """The short-form status; empty when the tree is clean."""
        return self._read("status", "--short")

    def diff(self, ref: str = "HEAD", path: str | None = None) -> str:
        """The working tree against `ref`, optionally limited to `path`."""
        paths = [path] if path is not None else []
        for argument in (ref, *paths):
            _refuse_option(argument)
        return self._read("diff", ref, "--", *paths)
