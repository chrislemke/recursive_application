# 10: Eval datasets: loading, reports, deltas, frontier ratios, append-only rule

**What to build:** The Kernel can load any dataset file, persist an eval report with a pointer to the latest one, compute Target and Guard deltas between two reports where a case missing from the earlier report counts as failing, compute the frontier ratio per capability, and detect changed or deleted existing eval cases from a diff. The three seeded frontier ladders are validated as a Kernel test.

Source: spec section "Evals and traces" and Testing Decisions seams 4 and 11; ADRs 0005 and 0009.

**Blocked by:** 03 (Data contracts and the Run Record), 06 (Git as the state store)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] Every file under the frontier directory loads with the pydantic-evals loader; every case carries tier, capability, rung, and gap kind; rungs are consecutive from 1
- [ ] A report is persisted per run under the runtime directory's evals folder with a latest pointer; its schema records each case's pass or fail and assertion reasons and is a Kernel contract
- [ ] Comparing two reports yields Target improved and Guard regressed deltas; a case with no entry in the earlier report counts as failing, so a new dataset starts red
- [ ] Frontier ratios are computed as green over total per capability; a capability is available only when green equals total
- [ ] Given a diff of eval files, changed or deleted existing cases are named and appended cases are allowed
- [ ] No model is called in tests
- [ ] All four checks exit 0
