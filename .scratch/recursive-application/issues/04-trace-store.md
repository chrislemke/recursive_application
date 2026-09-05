# 04: Trace Store

**What to build:** Configuring tracing once per process makes every agent run and every Kernel span land in one JSONL file per run under the runtime directory, in the span record schema the Sensors' anomaly rules will depend on, with Logfire cloud used only when a token is present. Spans can be read back as dicts.

Source: the Phase 1 seams document, tracing module (five tracer bullets); ADR 0004.

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** done

- [x] Built red to green, one tracer bullet at a time; a module-scoped fixture configures tracing once and tests tell their spans apart by name
- [x] After configuring, an Agent run on a test model leaves at least two spans in the returned file, every span carries every schema key, and the agent's name appears in the file
- [x] Spans of one run share a trace id and a child's parent span id equals its parent's span id
- [x] A Kernel span with an attribute records that attribute, status UNSET, and a non-negative duration; an exception inside a span records status ERROR
- [x] Reading a missing file returns an empty list; blank lines are skipped
- [x] Nothing is sent to Logfire cloud in tests; console output only when verbose
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** `configure_tracing` and `read_spans` in `src/recursive_application/kernel/tracing.py`, built red to green from the seams doc's five tracer bullets in order (six tests in `tests/kernel/test_tracing.py`; one module-scoped fixture configures tracing once into `<tmp>/test-run.jsonl` and every test finds its own spans by name or by its own agent's name). `configure_tracing` creates `traces_dir`, calls `logfire.configure(send_to_logfire="if-token-present", token=token, console=ConsoleOptions() when verbose else False, metrics=False, additional_span_processors=[SimpleSpanProcessor(exporter)])`, then `logfire.instrument_pydantic_ai()`, and returns the path. The exporter and the span-to-dict conversion are internal; each ended span is appended as one JSON object with exactly the schema keys (`trace_id`, `span_id`, `parent_span_id`, `name`, `start_ns`, `end_ns`, `duration_ms`, `status`, `status_description`, `attributes`), ids as `032x`/`016x` hex, non-JSON attribute values rendered through `default=str`, flushed per export. Library facts came from `thoughts/shared/research/2026-09-05-settings-tracing-library-facts.md` sections B and C: no token means no network call and no `.logfire/` (B2); additional processors receive scrubbed, message-formatted spans and never pending spans, but do receive `logfire.info` log records (B3); `SimpleSpanProcessor` exports synchronously at span end (B4); an exception escaping `logfire.span` sets `ERROR` with description `ValueError: boom` (B6); instrumentation version 5 names the agent span `invoke_agent <name>` and the model span `chat test`, and propagates `gen_ai.agent.name` to the child (C2). The Pydantic AI runs produced exactly two spans each: `invoke_agent probe_agent` (root, `parent_span_id` null) with child `chat test`, and `invoke_agent lineage_agent` with child `chat test`; both stayed `UNSET`.

Deviations for the human to confirm:

- **Bullets 2, 3, and 4 had no red.** Bullet 1's test asserts every schema key, so its least code was the whole span-to-dict conversion, which already carried trace ids, parent links, attributes, status, and duration. Each of the three tests was then checked against a deliberate one-line mutation of the implementation (parent always null; attributes always empty; duration always `-1.0`; status always `UNSET`): every one went red and the mutation was reverted. They are not vacuous, but they did not drive code.
- **Bullet 5 went red with `FileNotFoundError` and `JSONDecodeError`, not `AssertionError`.** The reader itself was the failing behaviour (no existence check, no blank-line filter), so this is the right reason, just not one of the three the coding guide lists.
- **Two assertions beyond the bullets' literal wording.** Bullet 4's test also asserts `status_description == "ValueError: boom"` (research B6), because that schema field is exercised nowhere else; and a blank-line test sits next to the missing-file test, because this ticket's checkbox and the seams doc's interface line both name it while bullet 5 does not.
- **Bullet 2 identifies the child by attribute.** `chat test` spans of several runs share one name, so the test picks the one whose `attributes["gen_ai.agent.name"] == "lineage_agent"`, then asserts its `trace_id` and `parent_span_id` against the root found by name.
- **The module fixture removes `LOGFIRE_TOKEN` itself** through a scoped `MonkeyPatch` before calling `configure_tracing`, because a module-scoped fixture is set up before the function-scoped conftest cleanup runs. The shell here carried no token, so this is hygiene, not a fix for an observed leak.
- **Console output is not covered by a test.** The seams doc has no console bullet and a second `configure` would drop the fixture's exporter. It was verified by a probe outside the suite: `verbose=False` wrote nothing to stdout, `verbose=True` wrote the span tree, neither attempted a socket connection, neither created `.logfire/`. Note the console prints Logfire's message (`console_agent run`), not the span name (`invoke_agent console_agent`).
- **Type-driven fallbacks.** opentelemetry-sdk 1.44.0 types `get_span_context()`, `start_time`, and `end_time` as optional, so `trace_id`, `span_id`, and `duration_ms` are written as `null` if the SDK ever hands over a span without them. Never observed; every exported span had all three.
- **Not passed:** `service_name` (the research file's recommended shape sets `"recursive-application"`; the seams doc does not ask for it) and no pending-span guard (they never reach custom exporters in 5.0.0, and the instruction was to keep everything the SDK hands over, log records included). `configure_tracing` creating a missing `traces_dir` is implemented but untested, since testing it needs a second `configure`.

Also noted: `run_sync` under pytest emits a `DeprecationWarning` ("There is no current event loop") from `pydantic_graph`, not from this module. The four checks are clean on the two owned files and `tests/kernel/test_tracing.py` passes alongside `test_cli.py` and `test_records.py` (21 tests). No change outside the owned files was needed; no `.logfire/` exists at the repo root.

**2026-09-05, reviewed.** Two-axis review (standards, spec), applied: the module fixture points `LOGFIRE_CREDENTIALS_DIR` at an empty temporary directory. The standards review found, and a probe confirmed, that `if-token-present` reads `.logfire/logfire_credentials.json` from the working directory, so a developer's `logfire projects use` at the repo root would have sent the suite's spans to the cloud; with the override no token is loaded. Noted, not changed: the lineage test identifies spans by pydantic-ai's names (`invoke_agent <name>`, `chat test`) and the `gen_ai.agent.name` attribute, the only handles the instrumentation offers. All four checks exit 0 on the whole tree.
