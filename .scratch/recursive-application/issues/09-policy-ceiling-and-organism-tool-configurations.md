# 09: Policy Ceiling and Organism tool configurations

**What to build:** The Organism owns which commands and paths each agent gets; the Kernel owns the Policy Ceiling no configuration may exceed and refuses to build an agent whose tools exceed it. Each role's tools do exactly what the spec grants: the Test Writer writes only under the Organism tests, the Implementer only under the Organism package and the README, the Librarian only under the Wiki, everyone else nothing; the shell allows the project's checks and read-only utilities and never git, install commands, network clients, or recursive deletes; no tool reads the env file or the git directory, and no tool writes anywhere a change would not reach the git diff.

Source: spec sections "Kernel, Organism, Protected Paths, and the write scope" and Testing Decisions seam 7; ADR 0001.

**Blocked by:** 02 (Protected Path rule, write scope, and Settings), 06 (Git as the state store)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] The Policy Ceiling is a Kernel value naming the forbidden commands, the paths no tool may read, the write-scope allowlist, and no network; validating a configuration that exceeds it fails with a named reason
- [ ] The shell allowlist rejects git and editing utilities and allows uv, pytest, python, ruff, ty, and the read-only utilities; the shell's timeout allows a full pytest run inside one tool call
- [ ] The Test Writer's file tool refuses a write under the Organism package; the Implementer's refuses a write under the tests; the Librarian's writes only under the Wiki; Planner, Worker, Reviewer, and Triage tools are read-only
- [ ] No tool writes under the virtualenv or the runtime directory; every file tool denies reading the env file and the git directory
- [ ] The git tools (log, diff, show, blame, status) work on a temporary repository through the Kernel's read helpers and refuse dash-prefixed arguments
- [ ] A Specialist's configuration can name any subset of the allowlist and is validated the same way
- [ ] All four checks exit 0
