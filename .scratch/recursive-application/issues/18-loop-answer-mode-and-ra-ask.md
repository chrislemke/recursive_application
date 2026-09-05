# 18: Loop, Answer Mode, and `ra ask`

**What to build:** `ra ask "a question"` runs one complete Loop in Answer Mode: Sense collects findings, Triage performs its Reflection and picks Answer, the Kernel builds one Target Case from the request and the generic answer rubric, the Worker answers, the Gate runs the judge, a failed judge feeds its reason into the next Iteration, and after the iteration limit the best output is printed with a warning and a Sensor Finding is recorded. The Run Record and the trace file exist afterwards. A clarification gap prints the questions and stops. At a terminal the Operator is asked for feedback. This is the thinnest complete path through all five phases and the first real CLI command; the runner's interface is written here in full so the following three tickets only add cases.

Source: spec sections "Loop semantics" (Answer, stop rules, clarification) and "CLI"; Testing Decisions seams 1 and 9; user stories 1, 2, 5, 11 to 15.

**Blocked by:** 14 (Agent runtime), 15 (Eval task functions, custom evaluators, and `ra evals`), 16 (Sensors), 17 (Gate)

**Status:** ready-for-agent

- [ ] The runner's seam is written in the seams-document format and confirmed by the user before the first red test: run(mode, task, options) returning a Run Record, agents overridden by function models, a runners bundle (checks, evals, approval) plus the git wrapper and the clock injected
- [ ] Answer accepted on the first try produces a Run Record with one Iteration, outcome accepted, and a trace file
- [ ] Answer best-effort after the limit returns the best output with a warning, outcome rejected, and a Sensor Finding
- [ ] Stop rules each end the run with outcome aborted and a named reason: iteration limit, wall time by the injected clock, USD budget summed over the run with a token fallback, no progress for two Iterations, an open breaker
- [ ] A Triage clarification gap prints the questions, runs nothing else, and exits 2
- [ ] Through the Typer runner with the Loop faked: `ask TEXT [--yes] [--max-iterations N] [--budget USD]` passes its options through, prints the outcome, and exits 0 for accepted, 1 for rejected or best-effort, 2 for aborted or usage error, 3 for an internal error
- [ ] The feedback prompt appears only when stdin is a terminal and never under `--yes`; a negative answer is appended to the feedback file
- [ ] All four checks exit 0
- [ ] Manual, for the human afterwards: `uv run ra ask "What can you do right now, and what would you need to grow?"` produces an Answer grounded in the Capability Inventory, records a trace, and asks for feedback
- [ ] The runner passes the Loop position (Mode, Iteration, phase, role, previous Gate outcome) into every State Bundle it assembles, and a function-model agent can be shown receiving it
