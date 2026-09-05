# 06: Git as the state store

**What to build:** The Kernel drives git through fixed argument lists and no shell: it can tell whether a tree is clean, list changed paths, render the diff with untracked files as additions, commit everything as the Kernel author unsigned regardless of the global git configuration, and hard reset and clean while keeping ignored runtime data. The read helpers that will back the Organism's git tools refuse dash-prefixed arguments before git runs.

Source: the Phase 1 seams document, git module (seven tracer bullets); ADR 0002; spec section "Git and runtime state".

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** done

- [x] Built red to green, one tracer bullet at a time, on the temporary repository fixture
- [x] The fixture repo is a repo, has commits, and is clean; after editing the README, adding a file, and writing under the ignored runtime directory it is not clean and the changed paths list exactly the two tracked changes
- [x] The diff text shows the edit and the new file's content as additions and is truncated with a marker past the limit
- [x] Committing returns a new sha, leaves the tree clean, records the message and the Kernel author, and still works when the repo's own config demands signing with an unusable signing program
- [x] Hard reset and clean restores the README, removes the junk file, and keeps the ignored runtime file
- [x] Blame, status, and diff helpers return the expected text; every helper refuses a ref or path starting with a dash by raising the git error before git runs
- [x] A freshly initialised repo without commits reports is-repo true, has-commits false, and head sha raises; a plain directory reports is-repo false
- [x] Nothing pushes, nothing signs, argv is fixed
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** Red to green through the seams document's seven tracer bullets on the `git_repo` fixture: 17 tests in `tests/kernel/test_git.py`, importing only `Repo` and `GitError`, backed by `src/recursive_application/kernel/git.py`. Every invocation is `subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)` with no shell; a non-zero exit raises `GitError` carrying git's stderr. The argument lists settled on for the operations that were not obvious: changed paths are `git status --porcelain=v1 -z --untracked-files=all`, split on NUL, a rename or copy entry contributing both names, the result a sorted set. The diff with untracked files is `git diff HEAD --` followed by `git ls-files --others --exclude-standard -z` and, per untracked file, `git diff --no-index -- /dev/null <path>`, whose exit 1 is the "files differ" signal rather than an error; no `add -N`, so a probe confirmed the index is unchanged afterwards. The commit is `git add --all`, then `git -c commit.gpgsign=false -c "user.name=ra Kernel" -c user.email=ra@localhost commit --quiet --message=<text>`, then `rev-parse --verify HEAD` for the sha; a probe confirmed that under the test's repository config a plain commit exits 128, so the signing test is sensitive. Reset is `reset --hard HEAD --quiet` then `clean -fd --quiet`. The read helpers are `log --oneline --max-count=N -- [path]`, `show --stat --patch <ref> --`, `blame -- <path>`, `status --short`, and `diff <ref> -- [path]`, each cut at 20,000 characters; a `ref` or `path` starting with `-` raises `GitError` before any subprocess starts, verified observably (`show("--output=<tmp file>")` leaves no file behind).

Deviations and judgement calls for the human to confirm:

- **The signing test also sets `gpg.format=openpgp` in the temporary repo.** The seams document names only `commit.gpgsign=true` and an unusable `gpg.program`, but this machine's global `gpg.format=ssh` would send a signing commit to 1Password's `gpg.ssh.program` and ignore `gpg.program`, so without the format override a regression would hang the suite on a GUI prompt instead of failing.
- **`is_repo()` is true only for the top level of a working copy** (`rev-parse --show-toplevel` resolved against `root`), not for a subdirectory inside one. The seams document does not say which; the stricter reading keeps `reset_hard_clean()` from ever acting on a parent repository.
- **The truncation marker is `\n[truncated: N more characters]`**, appended after the first `max_chars` characters. The seams document asks only for "a marker".
- **`status()` is `git status --short` without `--untracked-files=all`**, so an untracked directory appears collapsed there while `changed_paths()` lists its files one by one. The seams document says "short form" and no more.
- **Three tests went green on their first run**: the truncation test, because `max_chars` landed together with `diff_text` in bullet 2, and both bullet-7 tests, because `is_repo`, `has_commits`, and `head_sha` from bullets 1 and 3 already carried that behaviour.

Also noted: the red run of bullet 6 let `git show --output=/tmp/x` write `/tmp/x` once before the refusal existed; the file was removed and the green run creates none. The "All four checks exit 0" box is left for the orchestrator's whole-tree run; the own-file runs of ruff format, ruff check, ty check, and pytest all exit 0.

**2026-09-05, reviewed.** Two-axis review (standards, spec), applied: the five read helpers share one `_read` helper (a duplication the standards review named); a failed invocation with empty stderr now reports git's stdout, so a no-op `commit_all` says "nothing to commit, working tree clean" instead of "git -c exited 1". Verified by the spec review: a staged rename yields both names, `diff_text` leaves the index untouched, commits are unsigned with the Kernel identity as author and committer, and no caller string can reach git as an option. Kept: `assert sha == repo.head_sha()`, which states the return contract though the standards review called it tautological-leaning. All four checks exit 0 on the whole tree.
