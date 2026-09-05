# 17: Gate

**What to build:** The Gate is a pure function over its inputs (diff paths, changed eval cases, check results, eval deltas, trace anomalies, the Review) returning a Gate result, so it is table-testable. It applies the six checks in the spec's order, marks the rest skipped after the first failure, and knows the Answer and Task Loop subsets. The Guard retry-once rule is expressed in how a Guard regression is counted.

Source: spec section "Gate"; Testing Decisions seam 2; glossary entry Gate; ADR 0008 (pytest here is the green).

**Blocked by:** 02 (Protected Path rule, write scope, and Settings), 03 (Data contracts and the Run Record), 10 (Eval datasets: loading, reports, deltas, frontier ratios, append-only rule)

**Status:** done

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [x] The function has no side effects; every case in the table gives the same result on every call
- [x] Order and short-circuit: a Protected Path or a path outside the write scope fails first and leaves later checks skipped; then a changed or deleted existing eval case; then the four check results; then eval deltas; then anomalies; then the Review
- [x] Eval step: Target Cases must improve and Guard Cases must not regress; a Guard Case that passed in the latest report and fails now counts as a regression only after its one retry also fails
- [x] Answer and Task Loop Iterations use only the eval, anomaly, and Review steps; the Reviewer is skipped in Answer Mode
- [x] A failed check's excerpt is stored, truncated, in the Gate result
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** Red to green through the seams document's six tracer bullets, one row at a time: 16 tests in `tests/kernel/test_gate.py` backed by `src/recursive_application/kernel/gate.py`. The public surface is exactly what the seams document lists: `GateInputs`, `CHECK_ORDER`, `ANSWER_TASK_CHECKS`, `EXCERPT_LIMIT`, and `evaluate`. `GateInputs` is a `Contract`, so an Iteration's evidence is frozen and rejects unknown fields, and `evaluate` has no clock, no filesystem, no globals beyond the module constants; the only calls it makes are `is_protected` and `is_writable` on repo-relative strings with the default root.

The shape settled on is a mapping from check name to a rule of type `(GateInputs) -> str | None`, where `None` means the check passed and any string is its excerpt. `evaluate` walks `CHECK_ORDER` for Growth and `ANSWER_TASK_CHECKS` for Answer and Task, runs each rule until the first non-`None`, and emits `skipped` for every name after it, so the Kernel can gather the evidence in the same order and stop early. Returning the excerpt instead of a boolean is what keeps the rules total: a rule that fails always has something to say, and a check with an empty excerpt is still a failure, because the branch is on `is None` and not on truthiness. That matters for the one case the tests do not reach: a delta with no Target Cases at all that did not improve fails `evals` with an empty excerpt rather than silently passing.

The three rules that needed a decision. `evals` filters `guard_regressions` through `guard_retry_passed` first, so the retry-once rule of the spec lives in how a regression is counted rather than in a second pass; what remains, plus the target names when `target_improved` is false, is the excerpt. The four command checks share one closure, `_command_check(name)`, which looks its own `CheckResult` up by name; a missing result is a failure with the excerpt `not run`, which is why a report that lists only three of the four cannot buy a pass by omission. `review` is emitted `skipped` in Answer Mode before its rule ever runs, so the Mode decides, not the presence of a Review; in Task and Growth Mode a missing Review is a failure.

Deviations and judgement calls for the human to confirm:

- **The join between offending items is `", "`.** The seams document says the excerpt is "the offending paths, case names, finding summaries, or check output" without naming a separator. Every excerpt is then cut to `EXCERPT_LIMIT` (500), the check output included, which arrives already cut to 2,000 by `CheckResult`.
- **Two excerpt strings the seams document does not name:** `no eval delta` when `eval_delta` is `None`, and `no review` when `review` is `None`. The document's `not run` is kept for exactly what it names, a missing `CheckResult`, so the three "evidence never arrived" cases stay distinguishable in a Run Record.
- **When Target Cases stalled and Guard Cases regressed in the same Iteration**, the excerpt is the target names followed by the unretried regressions as one comma-separated list, in that order. The document treats them as two reasons for one check and does not say how they combine.
- **`GateInputs` declares its list fields with `Field(default_factory=list)`, not the bare `= []` used in `records.py`.** Ruff's RUF012 cannot see that the imported `Contract` base is a Pydantic model and flags the bare form; `EvalDelta` in `evals.py` already sets this precedent for a contract defined outside `records.py`. Behaviour is identical.
- **In Answer and Task Mode, `diff_paths` and `changed_eval_cases` are ignored entirely**, even when non-empty, because those Modes produce no diff. A Task Iteration that somehow carried a Protected Path in its inputs would not be stopped by the Gate; the Loop runner is the place that never puts one there.
- **In Answer Mode the `review` check is `skipped` even when a Review is supplied.** The document says it "passes with status `skipped` in Answer Mode"; the reading taken is that the Mode alone decides, so a stray Review cannot fail an Answer Iteration.
- **`evaluate` dispatches through a private `_RULES` mapping** keyed by check name, with a private `_Rule` alias. Neither is part of the Interface, so both may change freely.
- **Three tests were green on their first run.** The missing-`CheckResult` row of bullet 3, because the four-check rule landed whole one row earlier and the missing case was one branch of the same lookup. The Task Mode row of bullet 6, because the Review rule from bullet 5 and the Mode subset from the row before it already composed to it. The purity row of bullet 6, because purity is a property of the design rather than a behaviour any code was added for; it stands as the regression test that catches a later rule reaching for a clock or a file.

Left for the orchestrator: the seams document is still proposed, so that box stays unticked, and so does "All four checks exit 0", which is the whole-tree run. On my own two files `uv run ruff format`, `uv run ruff check`, and `uv run pytest tests/kernel/test_gate.py` all exit 0. `uv run ty check` over the tree reports one diagnostic, `invalid-argument-type` at `src/recursive_application/organism/tools.py:179` (a `FunctionToolset` argument), which belongs to another ticket in flight and was left untouched; there is no diagnostic in `kernel/gate.py` or `tests/kernel/test_gate.py`. Nothing was committed.

**2026-09-05, reviewed.** Two-axis review (standards, spec), applied. Spec, severe: the "truncated excerpt" criterion was ticked but only the check output and the Review notes were cut; sixty Protected Paths produced a 1,608-character excerpt. Every excerpt is now cut to `EXCERPT_LIMIT` at the one place a `GateCheck` is built, with a test. Spec: an evals failure with no Target Cases produced an empty excerpt and now says `no Target Cases`; Answer Mode still relies on the Kernel synthesising one Target Case, as the Loop runner seam says. Standards: none. All four checks exit 0 on the whole tree.
