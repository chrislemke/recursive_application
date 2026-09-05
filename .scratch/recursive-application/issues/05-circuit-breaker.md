# 05: Circuit breaker

**What to build:** The Kernel can run any callable under a named breaker, one per registry name, that opens after a configurable number of consecutive failures, goes half-open after a timeout measured by an injected clock, closes on a half-open success, and persists its state to a file so a new process sees it.

Source: the Phase 1 seams document, breaker module (six tracer bullets); spec section "Loop semantics" (stop rules).

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** done

- [x] Built red to green, one tracer bullet at a time, with the clock injected
- [x] Two failing calls still reach the callable; the third opens the breaker and the next call raises the open error without invoking it
- [x] After the clock advances by the reset timeout a successful call goes through and the state reads closed
- [x] A failure during the half-open trial re-opens the breaker; a success after two failures resets the count
- [x] A new store built on the same file sees the open state, recovers after the timeout, and a third instance reports closed
- [x] Breakers are independent by name; a fresh store reports no breakers
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** `BreakerStore` in `src/recursive_application/kernel/breaker.py`, built red to green from the seams doc's six tracer bullets in order, with the clock injected (nine tests in `tests/kernel/test_breaker.py`; the fake clock and the counting callee are plain classes in the test file, no mocking library). Each breaker record holds its consecutive-failure count and, once open, the clock reading at which it opened; `states()` derives open versus half-open from the clock at read time, so nothing about the timeout is stored. State is a JSON file at `path`, written after every recorded outcome and loaded when a store is built; tests never read the file, they observe it through a second and third store.

Deviations for the human to confirm:

- **Bullets 3, 4, and 6 had no red.** The least code for bullet 2 (count up on failure, stamp the clock at or over the threshold, clear both on success, one record per name) already re-opened a half-open breaker, reset the count on success, and kept names apart. Each of those tests was then checked against a deliberate one-line mutation of the implementation: it went red, the mutation was reverted. So they are not vacuous, but they did not drive code.
- **Two tests beyond the bullets' literal wording**, both for behaviour the seams doc's semantics line names: an open breaker reads `half_open` from `states()` once the timeout has elapsed (bullet 2), and a re-opened breaker waits the full timeout again, which is the fresh timestamp (bullet 3).
- **Only `Exception` counts as a failure.** `KeyboardInterrupt` and `SystemExit` propagate without touching the breaker or the file. The seams doc says "fn's exception" without qualifying.
- **The store creates the parent directory of `path`** when it is missing, so a first run with `.ra/` absent does not fail. One line, not asked for.

Also noted: the file is written with a plain `write_text`, not atomically, so a crash mid-write could leave a file the next store cannot parse; the timeout comparison is `>=`, so advancing the clock by exactly `reset_timeout_s` makes the breaker half-open, which is what bullet 2 asks for. No change outside the two owned files was needed; nothing from the spec's "Loop semantics" was deviated from (three failures, 60 seconds, one breaker per registry name).

**2026-09-05, reviewed.** Two-axis review (standards, spec): no findings on the breaker; the self-reported deviations (only `Exception` counts as a failure, the parent directory is created) were judged reasonable, and the spec review verified half-open at exactly the timeout and the fresh timestamp on re-open. The two tests beyond the bullets are recorded in the seams doc's amendments. All four checks exit 0 on the whole tree.
