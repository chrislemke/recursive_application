# 22: `ra ask` re-triage and `ra improve`

**What to build:** A hard question ends in an answer rather than in "run it again": after an accepted Improvement in `ra ask`, the Kernel re-runs Triage on the original Task once and, if the gap is closed, runs the Answer or Task Loop under the remaining budgets; if Triage picks Growth again, the run stops, prints what was added and what is still missing, and exits 1. `ra improve` picks the most severe open Sensor Finding, or gives the Planner a goal together with the findings, makes one Improvement per Iteration, and continues to the next finding until a stop rule.

Source: spec section "Loop semantics" (after an accepted Improvement) and "CLI"; user stories 6, 7, 16, 46.

**Blocked by:** 21 (Growth Loop: rejections, Actors, and Guard subset)

**Status:** ready-for-agent

- [ ] New runner cases are added to the seam list before their tests
- [ ] After an accepted Improvement in ask, Triage runs once more on the original Task and a Task Loop then runs under the remaining iteration, time, and budget limits
- [ ] Growth twice in one ask stops, prints the added capability and the remaining gap, and exits 1
- [ ] improve with no goal takes the top finding by severity then age; with `--goal` the Planner receives the goal and the findings together
- [ ] improve continues to the next finding after each Improvement until a stop rule, with `--yes`, `--max-iterations`, and `--budget` honoured
- [ ] Through the Typer runner with the Loop faked, both commands print their outcome and use the four exit codes
- [ ] All four checks exit 0
