---
status: accepted
---

# The Kernel is synchronous and runs one agent at a time

Pydantic AI is async-first and the orchestration literature favours parallel agents, but the Loop is inherently sequential: each phase consumes the previous phase's contract, one process holds the repo lock and edits one working tree, and one commit follows one Improvement. The Kernel therefore uses `run_sync`, `evaluate_sync`, and blocking subprocesses, and awaits only where a library offers no synchronous entry point. Concurrency across agents stays out until a Sensor Finding shows the wall-time budget is the bottleneck.

## Consequences

- Wall-time budgets assume serial calls; one slow model call blocks the whole run.
- Every trace reads as one linear story per run, which keeps the anomaly rules simple.
