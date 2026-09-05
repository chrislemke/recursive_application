---
status: accepted
---

# A hand-written markdown Wiki instead of the harness Memory capability

`pydantic-ai-harness` ships a `Memory` capability (a notebook with search tools and a SQLite journal). We chose to implement the Karpathy "LLM wiki" pattern ourselves: `wiki/index.md`, an append-only `wiki/log.md`, and topic pages, with ingest, query, and lint operations. The reasons: the memory must stay legible to humans and to the system's own Sensors, it must be editable by the Organism, and the pattern is roughly 150 lines. The harness notebook is opaque to the loop and its format is owned by a 0.x library.

## Consequences

- The Librarian is the only agent that writes to the Wiki; every other agent reads the index from its State Bundle.
- Memory format changes are Organism changes and can be made by the system itself.
