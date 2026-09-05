# Pydantic AI skill, verbatim copy

Source: the `building-pydantic-ai-agents` skill shipped inside the installed `pydantic_ai` package (pydantic-ai-slim 2.40.0, skill version 1.1.1), copied unmodified on 2026-09-05 from `.venv/lib/python3.12/site-packages/pydantic_ai/.agents/skills/building-pydantic-ai-agents/`.

Why a copy: the system runs outside Claude Code, and `docs/` is a Protected Path, so the reference the agents read is the one the human vetted and it matches the installed library.

Refresh: whenever the Pydantic AI dependency is upgraded (a human-only change), copy the directory again and update the versions above.

How agents use it: read `SKILL.md`, then exactly one reference from its routing table. The two project overrides that the skill cannot know (agents never set a model; output types come from the Kernel contracts) are in `docs/coding-guide.md`.
