# 23: `ra status`, `ra wiki ingest`, `ra wiki lint`

**What to build:** The Operator sees the system's health and agenda at a glance and keeps the Wiki fed and consistent. `ra status` shows breaker states, open Sensor Findings, recent runs, total cost, the eval trend, the frontier ratios, and the Librarian's frontier proposals, and is well formed on a fresh runtime directory. `ra wiki ingest PATH` has the Librarian read the path and write pages through its Wiki tool, then rebuilds the index and appends the log. `ra wiki lint` prints the orphan and unindexed pages.

Source: spec section "CLI"; user stories 9, 10, 69; ADR 0009 (proposals surfaced in status).

**Blocked by:** 14 (Agent runtime), 16 (Sensors)

**Status:** ready-for-agent

- [ ] The seam for each command is written in the seams-document format and confirmed by the user before the first red test
- [ ] status on an empty runtime directory prints every section with empty values and exits 0
- [ ] status with seeded runtime data shows breaker states, findings ranked, the last runs, summed cost, the eval trend across reports, each frontier ratio, and any open frontier proposal
- [ ] wiki ingest runs the Librarian on a test model over a temporary path, and afterwards the index is rebuilt and the log has a new entry
- [ ] wiki lint prints orphans and unindexed pages and its exit code follows the CLI exit code rule
- [ ] All four checks exit 0
