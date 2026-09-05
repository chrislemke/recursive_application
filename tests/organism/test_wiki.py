"""The Wiki, exercised through `Wiki` on a real directory under `tmp_path`.

The Wiki is the system's memory: an index, an append-only log, and topic pages in four
categories. Time is an injected clock fixed by the test; the only directory outside
`tmp_path` any test reads is the repo's own seed `wiki/`, and it reads it, never writes it.
"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.organism.wiki import (
    CapabilityPage,
    LintReport,
    OpenQuestion,
    Wiki,
)

CATEGORY_DIRNAMES = ("capabilities", "lessons", "open-questions", "tasks")


def test_ensure_layout_creates_the_index_the_log_and_the_four_category_directories(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"

    Wiki(root).ensure_layout()

    assert (root / "index.md").is_file()
    assert (root / "log.md").is_file()
    for category in CATEGORY_DIRNAMES:
        assert (root / "pages" / category / ".gitkeep").is_file()


def snapshot(root: Path) -> dict[str, str]:
    """Every file under `root` as a POSIX relative path mapped to its text."""
    return {
        str(path.relative_to(root).as_posix()): path.read_text()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_a_second_ensure_layout_leaves_the_existing_index_and_log_untouched(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    wiki = Wiki(root)
    wiki.ensure_layout()
    (root / "index.md").write_text("# Wiki index\n\n## Lessons\n\n- a lesson\n")
    (root / "log.md").write_text("# Wiki log\n\n- 2026-09-05T14:15:00Z: Ingested docs/x.md\n")
    before = snapshot(root)

    wiki.ensure_layout()

    assert snapshot(root) == before


EMPTY_INDEX = (
    "# Wiki index\n"
    "\n"
    "## Capabilities\n"
    "\n"
    "- (none)\n"
    "\n"
    "## Lessons\n"
    "\n"
    "- (none)\n"
    "\n"
    "## Open questions\n"
    "\n"
    "- (none)\n"
    "\n"
    "## Tasks\n"
    "\n"
    "- (none)\n"
)


def test_rebuild_index_renders_the_four_categories_as_empty_for_a_wiki_without_pages(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    assert wiki.rebuild_index() == EMPTY_INDEX


def test_ensure_layout_writes_the_index_the_way_rebuild_index_renders_it(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")

    wiki.ensure_layout()

    assert wiki.index_text() == EMPTY_INDEX


def test_the_repos_seed_wiki_holds_the_layout_and_the_rendered_empty_index() -> None:
    seed = Wiki(REPO_ROOT / "wiki")

    assert seed.index_text() == EMPTY_INDEX
    assert (seed.root / "log.md").read_text() == "# Wiki log\n"
    for category in CATEGORY_DIRNAMES:
        assert (seed.root / "pages" / category / ".gitkeep").is_file()


def write_page(wiki: Wiki, path: str, text: str) -> None:
    """Put a page into the Wiki the way the Librarian's file tool would."""
    (wiki.root / path).write_text(text)


def test_pages_lists_every_markdown_page_under_pages_sorted_by_path(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/tasks/a-task.md", "# A task\n")
    write_page(wiki, "pages/lessons/first-lesson.md", "# First lesson\n")

    assert wiki.pages() == ["pages/lessons/first-lesson.md", "pages/tasks/a-task.md"]


FIRST_LESSON = "# First lesson\n\nKeep tests at seams.\n\nMore text.\n"


def test_rebuild_index_lists_a_page_under_its_category_by_title_and_first_paragraph(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/lessons/first-lesson.md", FIRST_LESSON)

    assert wiki.rebuild_index() == (
        "# Wiki index\n"
        "\n"
        "## Capabilities\n"
        "\n"
        "- (none)\n"
        "\n"
        "## Lessons\n"
        "\n"
        "- [First lesson](pages/lessons/first-lesson.md): Keep tests at seams.\n"
        "\n"
        "## Open questions\n"
        "\n"
        "- (none)\n"
        "\n"
        "## Tasks\n"
        "\n"
        "- (none)\n"
    )


def test_rebuild_index_writes_the_text_it_returns_and_renders_the_same_pages_the_same_way(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/lessons/first-lesson.md", FIRST_LESSON)

    rendered = wiki.rebuild_index()

    assert wiki.index_text() == rendered
    assert wiki.rebuild_index() == rendered


def test_a_first_paragraph_longer_than_200_characters_is_cut_in_the_index(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/lessons/long.md", "# Long\n\n" + "x" * 250 + "\n")

    assert "- [Long](pages/lessons/long.md): " + "x" * 200 + "\n" in wiki.rebuild_index()


def test_a_page_without_a_paragraph_is_listed_without_a_summary(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/tasks/bare.md", "# Bare\n")

    assert "- [Bare](pages/tasks/bare.md)\n" in wiki.rebuild_index()


def test_a_page_without_a_heading_is_listed_under_its_file_stem(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/tasks/no-heading.md", "Body.")

    assert "- [no-heading](pages/tasks/no-heading.md): Body.\n" in wiki.rebuild_index()


def fixed_clock() -> datetime:
    """The clock every log test reads: 2026-09-05T14:15:00Z."""
    return datetime(2026, 9, 5, 14, 15, tzinfo=UTC)


def test_append_log_adds_one_dated_line_for_the_entry(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki", clock=fixed_clock)
    wiki.ensure_layout()

    wiki.append_log("Ingested docs/x.md")

    log = (wiki.root / "log.md").read_text()
    assert log.splitlines()[-1] == "- 2026-09-05T14:15:00Z: Ingested docs/x.md"


def test_a_second_append_log_keeps_the_earlier_line_and_adds_one(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki", clock=fixed_clock)
    wiki.ensure_layout()
    wiki.append_log("Ingested docs/x.md")

    wiki.append_log("Rebuilt the index")

    log = (wiki.root / "log.md").read_text()
    assert log == (
        "# Wiki log\n"
        "- 2026-09-05T14:15:00Z: Ingested docs/x.md\n"
        "- 2026-09-05T14:15:00Z: Rebuilt the index\n"
    )


def test_append_log_stamps_the_entry_in_utc_whatever_zone_the_clock_reads(
    tmp_path: Path,
) -> None:
    berlin = timezone(timedelta(hours=2))
    wiki = Wiki(tmp_path / "wiki", clock=lambda: datetime(2026, 9, 5, 16, 15, tzinfo=berlin))
    wiki.ensure_layout()

    wiki.append_log("Ingested docs/x.md")

    log = (wiki.root / "log.md").read_text()
    assert log.splitlines()[-1] == "- 2026-09-05T14:15:00Z: Ingested docs/x.md"


def test_list_open_questions_names_the_capability_of_a_frontier_proposal_and_nothing_else(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/open-questions/why-flaky.md", "# Why is answers flaky?\n")
    write_page(
        wiki,
        "pages/open-questions/next-frontier-text-analysis.md",
        "# Next rungs for text-analysis\n",
    )

    assert wiki.list_open_questions() == [
        OpenQuestion(
            "pages/open-questions/next-frontier-text-analysis.md",
            "Next rungs for text-analysis",
            "text-analysis",
        ),
        OpenQuestion("pages/open-questions/why-flaky.md", "Why is answers flaky?", None),
    ]


def test_lint_report_is_clean_for_a_freshly_seeded_wiki(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    report = wiki.lint_report()

    assert report == LintReport(orphans=[], unindexed=[])
    assert report.is_clean


def test_a_page_added_without_rebuilding_the_index_is_unindexed_and_an_orphan(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/tasks/new.md", "# New task\n\nDo the thing.\n")

    report = wiki.lint_report()

    assert report.unindexed == ["pages/tasks/new.md"]
    assert report.orphans == ["pages/tasks/new.md"]
    assert not report.is_clean


def test_a_link_from_an_indexed_page_clears_the_orphan_but_not_the_missing_index_entry(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/lessons/l.md", "# A lesson\n\nSomething learned.\n")
    wiki.rebuild_index()
    write_page(wiki, "pages/tasks/new.md", "# New task\n\nDo the thing.\n")

    write_page(
        wiki,
        "pages/lessons/l.md",
        "# A lesson\n\nSomething learned.\n\nSee [new](../tasks/new.md).\n",
    )

    report = wiki.lint_report()
    assert report.unindexed == ["pages/tasks/new.md"]
    assert report.orphans == []


def test_rebuilding_the_index_leaves_the_lint_report_clean(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/lessons/l.md", "# A lesson\n\nSomething learned.\n")
    write_page(wiki, "pages/tasks/new.md", "# New task\n\nDo the thing.\n")

    wiki.rebuild_index()

    assert wiki.lint_report() == LintReport(orphans=[], unindexed=[])


def test_capability_page_renders_the_name_summary_commit_and_dataset(tmp_path: Path) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    text = wiki.capability_page(
        "repo-history",
        "Answers questions about git history.",
        commit="abc1234",
        dataset="evals/frontier/repo-history.yaml",
    )

    assert text == (
        "# repo-history\n"
        "\n"
        "Answers questions about git history.\n"
        "\n"
        "- Commit: abc1234\n"
        "- Dataset: evals/frontier/repo-history.yaml\n"
    )


def test_list_capabilities_reads_back_the_commit_and_dataset_of_a_capability_page(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(
        wiki,
        "pages/capabilities/repo-history.md",
        "# repo-history\n"
        "\n"
        "Answers questions about git history.\n"
        "\n"
        "- Commit: abc1234\n"
        "- Dataset: evals/frontier/repo-history.yaml\n",
    )

    assert wiki.list_capabilities() == [
        CapabilityPage(
            "repo-history",
            "pages/capabilities/repo-history.md",
            "abc1234",
            "evals/frontier/repo-history.yaml",
        )
    ]


def test_a_capability_page_without_the_proof_lines_reports_no_commit_and_no_dataset(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    write_page(wiki, "pages/capabilities/bare.md", "# bare\n\nStill unproven.\n")

    assert wiki.list_capabilities() == [
        CapabilityPage("bare", "pages/capabilities/bare.md", None, None)
    ]


def test_frontier_proposal_page_holds_the_candidate_cases_and_why_each_is_harder(
    tmp_path: Path,
) -> None:
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    text = wiki.frontier_proposal_page(
        "text-analysis",
        "cases:\n  - name: text-analysis-6-three-texts\n    inputs: Compare three texts.\n",
        ["Rung 6 asks for a synthesis across three texts instead of two."],
    )

    assert text == (
        "# Next rungs for text-analysis\n"
        "\n"
        "Proposed by the Librarian after every rung of `evals/frontier/text-analysis.yaml` "
        "turned green. The human copies the cases they accept into that file.\n"
        "\n"
        "```yaml\n"
        "cases:\n"
        "  - name: text-analysis-6-three-texts\n"
        "    inputs: Compare three texts.\n"
        "```\n"
        "\n"
        "- Rung 6 asks for a synthesis across three texts instead of two.\n"
    )
    assert (
        wiki.frontier_proposal_path("text-analysis")
        == "pages/open-questions/next-frontier-text-analysis.md"
    )
