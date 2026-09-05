# 06: Git as the state store

**What to build:** The Kernel drives git through fixed argument lists and no shell: it can tell whether a tree is clean, list changed paths, render the diff with untracked files as additions, commit everything as the Kernel author unsigned regardless of the global git configuration, and hard reset and clean while keeping ignored runtime data. The read helpers that will back the Organism's git tools refuse dash-prefixed arguments before git runs.

Source: the Phase 1 seams document, git module (seven tracer bullets); ADR 0002; spec section "Git and runtime state".

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] Built red to green, one tracer bullet at a time, on the temporary repository fixture
- [ ] The fixture repo is a repo, has commits, and is clean; after editing the README, adding a file, and writing under the ignored runtime directory it is not clean and the changed paths list exactly the two tracked changes
- [ ] The diff text shows the edit and the new file's content as additions and is truncated with a marker past the limit
- [ ] Committing returns a new sha, leaves the tree clean, records the message and the Kernel author, and still works when the repo's own config demands signing with an unusable signing program
- [ ] Hard reset and clean restores the README, removes the junk file, and keeps the ignored runtime file
- [ ] Blame, status, and diff helpers return the expected text; every helper refuses a ref or path starting with a dash by raising the git error before git runs
- [ ] A freshly initialised repo without commits reports is-repo true, has-commits false, and head sha raises; a plain directory reports is-repo false
- [ ] Nothing pushes, nothing signs, argv is fixed
- [ ] All four checks exit 0
