"""Git as the state store, exercised against the real binary in a temporary repository."""

import subprocess
from pathlib import Path

import pytest

from recursive_application.kernel.git import GitError, Repo


def _git(root: Path, *args: str) -> None:
    """Test-side setup inside the temporary repository only."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def test_fixture_repo_is_a_repo_with_commits_and_a_clean_tree(git_repo: Path) -> None:
    repo = Repo(git_repo)

    assert repo.is_repo() is True
    assert repo.has_commits() is True
    assert repo.is_clean() is True


def test_edit_and_new_file_dirty_the_tree_while_ignored_runtime_data_does_not(
    git_repo: Path,
) -> None:
    repo = Repo(git_repo)
    (git_repo / "README.md").write_text("# changed\n")
    (git_repo / "new.txt").write_text("hello\n")
    (git_repo / ".ra").mkdir()
    (git_repo / ".ra" / "runtime.json").write_text("{}\n")

    assert repo.is_clean() is False
    assert repo.changed_paths() == ["README.md", "new.txt"]


def test_diff_text_shows_the_edit_and_the_untracked_file_as_additions(git_repo: Path) -> None:
    repo = Repo(git_repo)
    (git_repo / "README.md").write_text("# changed\n")
    (git_repo / "new.txt").write_text("brand new line\n")

    text = repo.diff_text()

    assert "+# changed" in text
    assert "new.txt" in text
    assert "+brand new line" in text


def test_diff_text_is_cut_at_max_chars_and_ends_in_a_truncation_marker(git_repo: Path) -> None:
    repo = Repo(git_repo)
    (git_repo / "README.md").write_text("# changed\n" * 50)

    text = repo.diff_text(max_chars=100)

    assert text.startswith("diff --git a/README.md b/README.md")
    assert text.index("\n[truncated: ") == 100
    assert text.endswith(" more characters]")


def test_commit_all_records_the_message_and_the_kernel_author_and_cleans_the_tree(
    git_repo: Path,
) -> None:
    repo = Repo(git_repo)
    previous = repo.head_sha()
    (git_repo / "a").write_text("a\n")

    sha = repo.commit_all("ra: add a")

    assert sha != previous
    assert sha == repo.head_sha()
    assert repo.is_clean() is True
    assert "ra: add a" in repo.log(n=1)
    assert "ra Kernel" in repo.show("HEAD")


def test_commit_all_is_unsigned_even_when_the_repo_config_demands_an_unusable_signer(
    git_repo: Path,
) -> None:
    _git(git_repo, "config", "commit.gpgsign", "true")
    _git(git_repo, "config", "gpg.format", "openpgp")
    _git(git_repo, "config", "gpg.program", "/nonexistent/signer")
    repo = Repo(git_repo)
    previous = repo.head_sha()
    (git_repo / "a").write_text("a\n")

    sha = repo.commit_all("ra: add a")

    assert sha != previous
    assert repo.is_clean() is True
    assert "ra: add a" in repo.log(n=1)


def test_reset_hard_clean_restores_tracked_files_removes_junk_and_keeps_runtime_data(
    git_repo: Path,
) -> None:
    repo = Repo(git_repo)
    (git_repo / "README.md").write_text("# changed\n")
    (git_repo / "junk.txt").write_text("junk\n")
    (git_repo / ".ra").mkdir()
    (git_repo / ".ra" / "keep").write_text("keep\n")

    repo.reset_hard_clean()

    assert (git_repo / "README.md").read_text() == "# test\n"
    assert not (git_repo / "junk.txt").exists()
    assert (git_repo / ".ra" / "keep").read_text() == "keep\n"
    assert repo.is_clean() is True


def test_blame_contains_the_file_text(git_repo: Path) -> None:
    repo = Repo(git_repo)

    assert "# test" in repo.blame("README.md")


def test_status_is_empty_when_clean_and_names_the_edited_file(git_repo: Path) -> None:
    repo = Repo(git_repo)

    assert repo.status() == ""

    (git_repo / "README.md").write_text("# changed\n")

    assert "README.md" in repo.status()


def test_diff_of_a_path_shows_the_removed_line(git_repo: Path) -> None:
    repo = Repo(git_repo)
    (git_repo / "README.md").write_text("# changed\n")

    assert "-# test" in repo.diff(path="README.md")


@pytest.mark.parametrize(
    ("helper", "kwargs"),
    [
        ("show", {"ref": "--output=/tmp/x"}),
        ("blame", {"path": "-x"}),
        ("log", {"path": "--all"}),
        ("diff", {"ref": "-p"}),
    ],
)
def test_read_helpers_refuse_a_ref_or_path_that_starts_with_a_dash(
    git_repo: Path, helper: str, kwargs: dict[str, str]
) -> None:
    repo = Repo(git_repo)

    with pytest.raises(GitError):
        getattr(repo, helper)(**kwargs)


def test_a_refused_argument_never_reaches_git(git_repo: Path, tmp_path: Path) -> None:
    repo = Repo(git_repo)
    target = tmp_path / "x"

    with pytest.raises(GitError):
        repo.show(f"--output={target}")

    assert not target.exists()


def test_a_fresh_repo_without_commits_is_a_repo_but_has_no_head(tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    repo = Repo(root)

    assert repo.is_repo() is True
    assert repo.has_commits() is False
    with pytest.raises(GitError):
        repo.head_sha()


def test_a_plain_directory_is_not_a_repo(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()

    assert Repo(root).is_repo() is False
