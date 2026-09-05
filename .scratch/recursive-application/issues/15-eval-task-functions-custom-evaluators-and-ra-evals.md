# 15: Eval task functions, custom evaluators, and `ra evals`

**What to build:** `ra evals` runs one dataset or all of them, prints the report, persists it with the latest pointer, and prints where it went. A task function exists for every dataset kind and a Kernel test proves every dataset file maps to one. Two custom evaluators check for secrets in output and for Organism-only target paths. The Judge Model is set through the pydantic-evals default judge before any run, so datasets never name a model. The test-writer and implementer datasets are marked expensive and run only in the full suite.

Source: spec sections "Evals and traces" and "CLI"; Testing Decisions seam 4; ADR 0005.

**Blocked by:** 11 (Seed eval datasets for the seven roles), 14 (Agent runtime)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] A task function per dataset kind (triage, planner, test-writer, implementer, answers, reviewer, librarian, frontier) runs the right agent through the agent runtime; a test asserts every file under the evals directory has a task function
- [ ] The no-secrets evaluator fails an output containing a key-shaped token; the Organism-only evaluator fails a Plan whose targets include a Protected Path
- [ ] The default judge is set to the Judge Model before any dataset runs; a dataset naming a model is rejected
- [ ] `ra evals [--dataset NAME] [--repeat K]` accepts a role name or a frontier capability, prints the report and the persisted path, and exits 0; an unknown dataset exits 2
- [ ] The test-writer and implementer datasets are excluded unless the full suite is requested
- [ ] Tests fake every model; nothing reaches the network
- [ ] All four checks exit 0
- [ ] Manual, for the human afterwards: `uv run ra evals --dataset triage` against OpenRouter persists a report
