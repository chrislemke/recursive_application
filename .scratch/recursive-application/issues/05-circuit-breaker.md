# 05: Circuit breaker

**What to build:** The Kernel can run any callable under a named breaker, one per registry name, that opens after a configurable number of consecutive failures, goes half-open after a timeout measured by an injected clock, closes on a half-open success, and persists its state to a file so a new process sees it.

Source: the Phase 1 seams document, breaker module (six tracer bullets); spec section "Loop semantics" (stop rules).

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] Built red to green, one tracer bullet at a time, with the clock injected
- [ ] Two failing calls still reach the callable; the third opens the breaker and the next call raises the open error without invoking it
- [ ] After the clock advances by the reset timeout a successful call goes through and the state reads closed
- [ ] A failure during the half-open trial re-opens the breaker; a success after two failures resets the count
- [ ] A new store built on the same file sees the open state, recovers after the timeout, and a third instance reports closed
- [ ] Breakers are independent by name; a fresh store reports no breakers
- [ ] All four checks exit 0
