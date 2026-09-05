# 03: Data contracts and the Run Record

**What to build:** Every piece of data that crosses an agent boundary or lands in a Run Record is a frozen contract that rejects unknown fields and works as a Pydantic AI output type. Run Records persist as one file per run under the runtime directory, can have Iterations appended, and can be listed in start order.

Source: the Phase 1 seams document, records module (tracer bullets 1 to 6 including 3b); spec section "Data contracts".

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] Built red to green, one tracer bullet at a time, in the seams document's order
- [ ] Assigning a field on a contract raises a validation error; an unknown field raises a validation error
- [ ] A Triage decision built from a plain dict with a connection gap that needs "network access" validates, with Growth as its Mode and no clarifying questions
- [ ] A Plan with two test sentences and an actor round-trips through JSON unchanged; a Plan built without them has an empty tests list and no actor
- [ ] A check result's output is truncated to 2,000 characters on construction; a Gate result lists only its failed checks by name
- [ ] Adding two Usage values adds every field including the decimal cost
- [ ] Appending an Iteration then loading returns an equal Run Record from a file named by the run id; total usage sums the Iterations' cost; listing returns records in start order and an empty list for a missing directory
- [ ] The full contract set exists as specified: Mode, Outcome, Capability Gap, Reflection, Triage decision, Eval Case, Plan, check result, code report, Worker output, Review, Sensor Finding with the six sources, Gate check and Gate result, Usage, Iteration record with test report and code report, Run Record with the generated id shape
- [ ] All four checks exit 0
