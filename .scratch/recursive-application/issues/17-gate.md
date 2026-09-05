# 17: Gate

**What to build:** The Gate is a pure function over its inputs (diff paths, changed eval cases, check results, eval deltas, trace anomalies, the Review) returning a Gate result, so it is table-testable. It applies the six checks in the spec's order, marks the rest skipped after the first failure, and knows the Answer and Task Loop subsets. The Guard retry-once rule is expressed in how a Guard regression is counted.

Source: spec section "Gate"; Testing Decisions seam 2; glossary entry Gate; ADR 0008 (pytest here is the green).

**Blocked by:** 02 (Protected Path rule, write scope, and Settings), 03 (Data contracts and the Run Record), 10 (Eval datasets: loading, reports, deltas, frontier ratios, append-only rule)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] The function has no side effects; every case in the table gives the same result on every call
- [ ] Order and short-circuit: a Protected Path or a path outside the write scope fails first and leaves later checks skipped; then a changed or deleted existing eval case; then the four check results; then eval deltas; then anomalies; then the Review
- [ ] Eval step: Target Cases must improve and Guard Cases must not regress; a Guard Case that passed in the latest report and fails now counts as a regression only after its one retry also fails
- [ ] Answer and Task Loop Iterations use only the eval, anomaly, and Review steps; the Reviewer is skipped in Answer Mode
- [ ] A failed check's excerpt is stored, truncated, in the Gate result
- [ ] All four checks exit 0
