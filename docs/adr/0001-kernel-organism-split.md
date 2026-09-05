---
status: accepted
---

# Kernel/Organism split enforced by a path rule at the Gate

A system that rewrites its own code can also rewrite the code that judges it. We split the codebase into a human-owned Kernel (loop runner, Gate, breaker, Sensors, provider setup, CLI, Constitution, plus `pyproject.toml`, `uv.lock`, `.env`, `.gitignore`, `.claude/`, `docs/`, `CONTEXT.md`, `tests/kernel/`) and a self-editable Organism (agents, prompts, tools, evals, their tests, the Wiki). The boundary is one path rule in the Kernel, checked deterministically against `git diff` before any commit; file-tool restrictions use the same rule but are a convenience, not the boundary. This mirrors the read-only supervisor layer that the 2026 self-improving-harness literature (Self-Harness, Weng) converged on: the evaluator and permission control sit outside the loop that evolves the agent.

## Consequences

- The Organism cannot fix Kernel bugs; it can only record a finding for a human.
- Dependency changes are Kernel changes and therefore proposals, never automatic edits.
- Any tool that can write files (`python -c`, shell tricks) is harmless to the boundary, because the diff check runs after the fact.
- Tool configurations are Organism files, so the Kernel keeps a Policy Ceiling (commands no shell tool may allow, paths no tool may read, no network) and refuses to build an agent whose configuration exceeds it. Widening the ceiling is a Kernel change.
- The write scope for tools is an allowlist of tracked Organism paths, not "everything unprotected": a write into a gitignored path such as `.venv/` or `.ra/` never reaches `git diff`, so the diff check could not see it.
