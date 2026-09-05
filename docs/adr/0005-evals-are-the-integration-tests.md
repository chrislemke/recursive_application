---
status: accepted
---

# Evals are the integration tests and never run under pytest

`uv run pytest` is the Gate's first check and must be green offline in seconds, while model behaviour is non-deterministic and costs money. So pytest covers deterministic behaviour only, with `TestModel` or `FunctionModel` and `ALLOW_MODEL_REQUESTS=False` for the whole session, and live model behaviour is covered exclusively by pydantic-evals datasets run through `ra evals` or inside a Loop, whose reports are persisted as Sensor evidence. We rejected live tests behind a skip marker: a silent skip hides regressions, and an unskipped run makes the suite slow, flaky, and expensive.

## Consequences

- A green test suite says nothing about model quality; only an eval report does.
- Eval datasets are Organism files; existing cases are append-only, and changing one is a human decision.
