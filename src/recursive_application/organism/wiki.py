"""The Wiki, the system's memory as markdown in the repo.

An index, an append-only log, and topic pages under four categories. Organism code (ADR
0003), so the system may improve it; only the Librarian writes to it at run time. Every
path in this module's contracts is POSIX relative to the Wiki root.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

INDEX_FILENAME = "index.md"
"""The Wiki index, rebuilt from the pages."""

LOG_FILENAME = "log.md"
"""The append-only Wiki log."""

PAGES_DIRNAME = "pages"
"""The directory holding the category directories."""

CATEGORIES: tuple[str, ...] = ("capabilities", "lessons", "open-questions", "tasks")
"""The four page categories, in index order."""

LOG_HEADING = "# Wiki log"
"""The first line of the log."""

INDEX_HEADING = "# Wiki index"
"""The first line of the index."""

SUMMARY_LIMIT = 200
"""How much of a page's first paragraph the index shows."""

COMMIT_PREFIX = "- Commit: "
"""The line of a capability page that carries the commit proving it."""

DATASET_PREFIX = "- Dataset: "
"""The line of a capability page that carries the eval dataset proving it."""

_LINK_PATTERN = re.compile(r"\]\(([^)]+)\)")
_SCHEME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")


FRONTIER_PROPOSAL_PREFIX = "next-frontier-"
"""The file name prefix of the Librarian's frontier proposal, followed by the capability."""


@dataclass(frozen=True)
class OpenQuestion:
    """One page under `pages/open-questions/`; `capability` is set on a frontier proposal."""

    path: str
    title: str
    capability: str | None


@dataclass(frozen=True)
class CapabilityPage:
    """One page under `pages/capabilities/` and the commit and dataset that prove it."""

    name: str
    path: str
    commit: str | None
    dataset: str | None


@dataclass(frozen=True)
class LintReport:
    """Pages nothing links to and pages the index does not link to, both sorted."""

    orphans: list[str]
    unindexed: list[str]

    @property
    def is_clean(self) -> bool:
        """True when the Wiki has neither an orphan page nor a page missing from the index."""
        return not self.orphans and not self.unindexed


def _utc_now() -> datetime:
    """The current time in UTC; the default clock."""
    return datetime.now(UTC)


class Wiki:
    """Reads and writes one Wiki directory: its index, its log, and its pages."""

    def __init__(self, root: Path, clock: Callable[[], datetime] = _utc_now) -> None:
        self.root = root
        self._clock = clock

    def ensure_layout(self) -> None:
        """Create the index, the log, and the four category directories; never overwrite."""
        for category in CATEGORIES:
            directory = self.root / PAGES_DIRNAME / category
            directory.mkdir(parents=True, exist_ok=True)
            _write_if_missing(directory / ".gitkeep", "")
        _write_if_missing(self.root / INDEX_FILENAME, self._render_index())
        _write_if_missing(self.root / LOG_FILENAME, f"{LOG_HEADING}\n")

    def pages(self) -> list[str]:
        """Every markdown page under `pages/`, as POSIX paths relative to the root, sorted."""
        pages = self.root / PAGES_DIRNAME
        return sorted(path.relative_to(self.root).as_posix() for path in pages.rglob("*.md"))

    def rebuild_index(self) -> str:
        """Render the index from the pages, write it to `index.md`, and return the text."""
        text = self._render_index()
        (self.root / INDEX_FILENAME).write_text(text)
        return text

    def append_log(self, entry: str) -> None:
        """Add one timestamped line for `entry` to `log.md`; earlier lines are never touched."""
        stamp = self._clock().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (self.root / LOG_FILENAME).open("a") as log:
            log.write(f"- {stamp}: {entry}\n")

    def _pages_in(self, category: str) -> list[str]:
        """The pages of one category directory, sorted by path."""
        return [page for page in self.pages() if PurePosixPath(page).parts[1] == category]

    def list_open_questions(self) -> list[OpenQuestion]:
        """Every open question, sorted by path, frontier proposals carrying their capability."""
        questions = []
        for page in self._pages_in("open-questions"):
            path = PurePosixPath(page)
            capability = (
                path.stem.removeprefix(FRONTIER_PROPOSAL_PREFIX)
                if path.stem.startswith(FRONTIER_PROPOSAL_PREFIX)
                else None
            )
            title = _title((self.root / page).read_text()) or path.stem
            questions.append(OpenQuestion(page, title, capability))
        return questions

    def capability_page(self, name: str, summary: str, *, commit: str, dataset: str) -> str:
        """The text of a capability page: its name, its summary, and the proof of it."""
        return f"# {name}\n\n{summary}\n\n{COMMIT_PREFIX}{commit}\n{DATASET_PREFIX}{dataset}\n"

    def frontier_proposal_path(self, capability: str) -> str:
        """Where the Librarian's proposal of harder rungs for `capability` lives, root-relative."""
        return f"{PAGES_DIRNAME}/open-questions/{FRONTIER_PROPOSAL_PREFIX}{capability}.md"

    def frontier_proposal_page(self, capability: str, cases_yaml: str, reasons: list[str]) -> str:
        """The text of a frontier proposal: candidate cases as YAML and why each is harder.

        Written when every rung of a frontier file is green (ADR 0009); the human copies the
        cases they accept into `evals/frontier/<capability>.yaml`, never the system.
        """
        body = cases_yaml if cases_yaml.endswith("\n") else f"{cases_yaml}\n"
        why = "".join(f"- {reason}\n" for reason in reasons)
        return (
            f"# Next rungs for {capability}\n"
            "\n"
            f"Proposed by the Librarian after every rung of `evals/frontier/{capability}.yaml` "
            "turned green. The human copies the cases they accept into that file.\n"
            "\n"
            f"```yaml\n{body}```\n"
            "\n"
            f"{why}"
        )

    def list_capabilities(self) -> list[CapabilityPage]:
        """Every capability page, sorted by path, parsed by the capability page convention."""
        capabilities = []
        for page in self._pages_in("capabilities"):
            path = PurePosixPath(page)
            text = (self.root / page).read_text()
            capabilities.append(
                CapabilityPage(
                    _title(text) or path.stem,
                    page,
                    _prefixed_line(text, COMMIT_PREFIX),
                    _prefixed_line(text, DATASET_PREFIX),
                )
            )
        return capabilities

    def lint_report(self) -> LintReport:
        """Which pages nothing links to and which pages the index does not link to."""
        pages = self.pages()
        indexed = self._link_targets(INDEX_FILENAME)
        linked = set(indexed)
        for source in [LOG_FILENAME, *pages]:
            linked |= self._link_targets(source) - {source}
        return LintReport(
            orphans=[page for page in pages if page not in linked],
            unindexed=[page for page in pages if page not in indexed],
        )

    def _link_targets(self, source: str) -> set[str]:
        path = self.root / source
        if not path.is_file():
            return set()
        root = self.root.resolve()
        directory = path.resolve().parent
        targets = set()
        for target in _LINK_PATTERN.findall(path.read_text()):
            if _SCHEME_PATTERN.match(target):
                continue
            resolved = (directory / target).resolve()
            if resolved.is_relative_to(root):
                targets.add(resolved.relative_to(root).as_posix())
        return targets

    def index_text(self) -> str:
        """The current `index.md`, empty when the file is missing."""
        index = self.root / INDEX_FILENAME
        return index.read_text() if index.exists() else ""

    def _render_index(self) -> str:
        blocks = [INDEX_HEADING]
        for category in CATEGORIES:
            lines = [self._index_line(page) for page in self._pages_in(category)]
            blocks.append(f"## {_category_heading(category)}")
            blocks.append("\n".join(lines) or "- (none)")
        return "\n\n".join(blocks) + "\n"

    def _index_line(self, page: str) -> str:
        text = (self.root / page).read_text()
        summary = _summary(text)
        line = f"- [{_title(text) or PurePosixPath(page).stem}]({page})"
        return f"{line}: {summary}" if summary else line


def _category_heading(category: str) -> str:
    """The `##` heading of a category directory: `open-questions` reads `Open questions`."""
    return category.replace("-", " ").capitalize()


def _write_if_missing(path: Path, text: str) -> None:
    """Write `text` to `path` unless the file is already there."""
    if not path.exists():
        path.write_text(text)


def _title(text: str) -> str:
    """The text of a page's first `# ` heading."""
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _summary(text: str) -> str:
    """A page's first non-empty, non-heading block, joined to one line."""
    for block in text.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines and not lines[0].startswith("#"):
            return " ".join(lines)[:SUMMARY_LIMIT]
    return ""


def _prefixed_line(text: str, prefix: str) -> str | None:
    """What follows `prefix` on the first line that starts with it, or `None`."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None
