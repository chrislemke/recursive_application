# 11: Seed eval datasets for the seven roles

**What to build:** One dataset per role, two or three cases each, so every registry entry has the eval file that proves it and the Guard subset has something to guard from the first Iteration. Judge evaluators are assertions with a reason; scores are optional extras; no dataset names a model. The cases include the growth-awareness cases the spec requires.

Source: spec section "Evals and traces" (dataset list) and Testing Decisions (evals that cover the new requirements).

**Blocked by:** 10 (Eval datasets: loading, reports, deltas, frontier ratios, append-only rule)

**Status:** ready-for-agent

- [ ] The triage dataset maps requests to expected Mode and gap kind, including a request needing a Specialist, a tool, a connection, and a clarification, and a frontier-style "analyse this text" request that must map to Growth with a skill gap
- [ ] The planner dataset holds synthetic Sensor states including a frontier finding whose Plan must add a registry entry naming the frontier file as its dataset and must list tests
- [ ] The test-writer dataset gives a Plan and a scratch copy of the Organism; the produced tests must be collected by pytest and fail
- [ ] The implementer dataset gives failing tests in a scratch copy; they must pass afterwards with ruff and ty clean under a tool-call cap
- [ ] The answers dataset asks questions about the system with rubrics, including the self-description question whose rubric requires naming the Organism surfaces, the Kernel limit, and at least one frontier ratio
- [ ] The reviewer dataset holds diff and Plan pairs: a tautological test and an eval edit are rejected, an honest diff is accepted
- [ ] The librarian dataset gives a run summary; the produced log entry and page satisfy a rubric
- [ ] Every file loads through the loader from ticket 10; a Kernel test asserts this
- [ ] All four checks exit 0
- [ ] The answers dataset includes a case asking which loop the system runs in and where the answering agent sits, judged against a rubric that requires the five phases and the agent's own phase
- [ ] The planner dataset includes a case adding a tool, asserting that the Plan's Target Cases exercise that tool (ADR 0010: every addition arrives with its gate)
