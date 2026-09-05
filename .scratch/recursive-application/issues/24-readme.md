# 24: README

**What to build:** A README that lets a new Operator set the system up and use it: what it is, setup with uv and the env file, the six commands with their flags and exit codes, the Kernel and Organism rule and the Protected Paths, where runtime data lives, how to read traces and Run Records, and how the Frontier Cases work as the growth agenda including how a human adds a rung. The README is inside the write scope, so the Implementer may edit it later; write it so that stays safe.

Source: the plan's Phase 5 README item; spec sections "CLI", "Git and runtime state", "Evals and traces".

**Blocked by:** 22 (`ra ask` re-triage and `ra improve`), 23 (`ra status`, `ra wiki ingest`, `ra wiki lint`)

**Status:** ready-for-agent

- [ ] Sections: what it is, setup, commands, the Kernel and Organism rule, where data lives, reading traces and Run Records, Frontier Cases
- [ ] Every command and flag named matches the CLI as built; exit codes listed
- [ ] Every repo-relative path mentioned exists (reuse the documentation pointer test's rule)
- [ ] All four checks exit 0
