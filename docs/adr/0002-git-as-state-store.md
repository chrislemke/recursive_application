---
status: accepted
---

# Git commits are the immutable, versioned state store

The orchestration patterns we follow require immutable, versioned state snapshots with rollback and replay. For a system whose state *is* its source tree, git already provides that. Each accepted Improvement is one commit made by the Kernel (never by an agent); a rejected Iteration is undone with `git reset --hard` and `git clean -fd`; the system never pushes. Because the reset is destructive, the Kernel refuses to start a Growth Loop on a dirty working tree, and a lock file under `.ra/` prevents two `ra` processes from editing the repo at once. We rejected a separate state database and copy-on-write working directories as extra machinery with no benefit for a single-repo, single-process system.

## Consequences

- Agents read git history through read-only tools; `git` itself stays off the shell allowlist so pushes and commits cannot be issued by a model.
- Runtime data under `.ra/` is gitignored and never auto-deleted; the Wiki and eval datasets are tracked because they are the compressed knowledge.
