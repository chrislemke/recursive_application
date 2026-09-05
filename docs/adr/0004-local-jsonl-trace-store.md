---
status: accepted
---

# A local JSONL Trace Store fed by an OpenTelemetry span exporter; Logfire cloud is optional

Sensors have to read the system's own behaviour deterministically, offline, and without a token, so every run writes its spans to `.ra/traces/<run_id>.jsonl` through an extra span processor registered with `logfire.configure`: one flattened span per line with a fixed field set (ids, name, timings, status, attributes). Logfire cloud stays available for humans through `send_to_logfire='if-token-present'`, but nothing in the Loop depends on it. We rejected querying Logfire's API (network, latency, a token in every environment) and a database (the Trace Store is append-only and read whole, one run at a time).

## Consequences

- The span record schema is a Kernel contract. The Sensors' anomaly rules are written against it, so changing a field means migrating those rules.
- Trace files are never deleted automatically; disk use grows with runs.
