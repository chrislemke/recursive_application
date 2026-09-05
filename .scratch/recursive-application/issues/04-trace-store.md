# 04: Trace Store

**What to build:** Configuring tracing once per process makes every agent run and every Kernel span land in one JSONL file per run under the runtime directory, in the span record schema the Sensors' anomaly rules will depend on, with Logfire cloud used only when a token is present. Spans can be read back as dicts.

Source: the Phase 1 seams document, tracing module (five tracer bullets); ADR 0004.

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] Built red to green, one tracer bullet at a time; a module-scoped fixture configures tracing once and tests tell their spans apart by name
- [ ] After configuring, an Agent run on a test model leaves at least two spans in the returned file, every span carries every schema key, and the agent's name appears in the file
- [ ] Spans of one run share a trace id and a child's parent span id equals its parent's span id
- [ ] A Kernel span with an attribute records that attribute, status UNSET, and a non-negative duration; an exception inside a span records status ERROR
- [ ] Reading a missing file returns an empty list; blank lines are skipped
- [ ] Nothing is sent to Logfire cloud in tests; console output only when verbose
- [ ] All four checks exit 0
