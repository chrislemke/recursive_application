# 03: Data contracts and the Run Record

**What to build:** Every piece of data that crosses an agent boundary or lands in a Run Record is a frozen contract that rejects unknown fields and works as a Pydantic AI output type. Run Records persist as one file per run under the runtime directory, can have Iterations appended, and can be listed in start order.

Source: the Phase 1 seams document, records module (tracer bullets 1 to 6 including 3b); spec section "Data contracts".

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** done

- [x] Built red to green, one tracer bullet at a time, in the seams document's order
- [x] Assigning a field on a contract raises a validation error; an unknown field raises a validation error
- [x] A Triage decision built from a plain dict with a connection gap that needs "network access" validates, with Growth as its Mode and no clarifying questions
- [x] A Plan with two test sentences and an actor round-trips through JSON unchanged; a Plan built without them has an empty tests list and no actor
- [x] A check result's output is truncated to 2,000 characters on construction; a Gate result lists only its failed checks by name
- [x] Adding two Usage values adds every field including the decimal cost
- [x] Appending an Iteration then loading returns an equal Run Record from a file named by the run id; total usage sums the Iterations' cost; listing returns records in start order and an empty list for a missing directory
- [x] The full contract set exists as specified: Mode, Outcome, Capability Gap, Reflection, Triage decision, Eval Case, Plan, check result, code report, Worker output, Review, Sensor Finding with the six sources, Gate check and Gate result, Usage, Iteration record with test report and code report, Run Record with the generated id shape
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** Red to green through the seams doc's seven tracer bullets (1, 2, 3, 3b, 4, 5, 6) in order, twelve tests in `tests/kernel/test_records.py`, all at the listed interface. `records.py` holds the full contract set on a frozen `extra="forbid"` base, `RunRecord` unfrozen with the generated id, and `RunStore` with `save`, `append_iteration`, `load`, `list_all`. Library facts verified against the installed packages: `pydantic/main.py:84` raises `ValidationError` (`frozen_instance`) on assignment and `extra_forbidden` on an unknown field; `pydantic/_internal/_fields.py:716` `smart_deepcopy`s mutable defaults, so `list[str] = []` is per instance; a scratch run showed `Decimal("0.01")` serialises to the JSON string `"0.01"` and a UTC `datetime` comes back as `TzInfo(UTC)`, both equal after the round trip; on pydantic-ai 2.40.0 `Agent(name="triage", output_type=TriageDecision)` run with `TestModel` returns a `TriageDecision`; a generated `run_id` matched `\d{8}-\d{6}-[0-9a-f]{6}`.

Points for the human to confirm:

- **Two contracts have no tracer bullet.** `WorkerOutput` and `SensorFinding` exist as specified but no seams-doc bullet exercises them, so nothing in the suite touches them. Suggest a bullet if they should be pinned.
- **Two acceptance claims are verified, not tested.** The `run_id` shape and "works as a Pydantic AI output type" appear in the acceptance list but not in the bullets; both were checked by the scratch run above, not by a test in the suite. Suggest adding bullets 7 and 8 to the seams doc if they should be regression-tested.
- **One targeted ignore.** ty 0.0.78 types Pydantic frozen fields as read-only, so the bullet 1 assignment is a static error; `setattr` with a constant name trips ruff B010 (`B` is enabled). The test line carries `# ty: ignore[invalid-assignment]` with a comment saying why.
- **Keyword spelling of a literal.** The seams doc writes `GateCheck("pytest", "failed")`; Pydantic models take keywords, so the test spells the same literal as `GateCheck(name="pytest", status="failed")`.
- **Unspecified choice.** `RunStore.save` writes JSON with `indent=2` so Run Records are readable in a diff.

**2026-09-05, reviewed.** Two-axis review (standards, spec), applied: `list_all` orders by `(started_at, run_id)` so equal start times are deterministic; two tests added for the acceptance claims that had none (the `run_id` shape, and a contract as a Pydantic AI output type on `TestModel`), recorded as bullets 7 and 8 in the seams doc's amendments. Kept: the targeted `ty: ignore` on the frozen-assignment test, which the standards review judged the honest alternative. `WorkerOutput` and `SensorFinding` remain untested until a later seam uses them. All four checks exit 0 on the whole tree.
