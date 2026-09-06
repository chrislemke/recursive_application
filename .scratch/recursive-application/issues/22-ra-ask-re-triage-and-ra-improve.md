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
- [x] Through the Typer runner with the Loop faked, both commands print their outcome and use the four exit codes
- [ ] All four checks exit 0

## Comments

**2026-09-06, implemented, CLI bullet 4.** `ra improve` is a real command. It builds the `LoopRunner` from `build_context()` the way `ask` does (both now go through one `_loop_runner(ctx)` helper) and calls `run(Mode.GROWTH, None, LoopOptions(yes=..., max_iterations=..., budget_usd=_budget_usd(budget), goal=goal))`. It prints one line per Iteration of the returned record as `Iteration <n>: <outcome> <plan title or reason>` (the Plan's title when the Iteration has a Plan, else its `reason`), then `Outcome: <outcome>` and, when there is one, `Reason: <reason>` through the same `_print_result` that `ask` uses; there is no output line and no feedback prompt, and the exit code is `result.exit_code`. Two tests in `tests/kernel/test_cli.py` run it through the Typer runner with the Loop faked: `improve --goal "reduce cost" --yes` passes `Mode.GROWTH`, `task=None`, `LoopOptions(yes=True, goal="reduce cost")`, prints the literal lines `Iteration 1: accepted Teach the Worker what the Gate is` and `Iteration 2: rejected no red: 1 passed` and `Outcome: accepted`, and exits 0; a fake returning `exit_code=2` with `reason="iteration limit"` exits 2 and prints `Outcome: aborted` and `Reason: iteration limit`. The stub helper `_not_implemented` had no caller left and was deleted. The checkbox on the two commands' printed outcome and exit codes is ticked: `ask` was already covered for 0, 1, 2, and 3, and `improve` now is for 0 and 2 through the same `_run_command` path.
Decided here, not in the seams doc: an Iteration with neither Plan nor reason prints `Iteration <n>: <outcome>` with nothing after the outcome and no trailing space, the title wins when both are present, and the Iteration's `outcome` field is printed as is.
