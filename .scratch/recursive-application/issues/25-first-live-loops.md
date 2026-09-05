# 25: First live loops

**What to build:** The system exercised on itself against OpenRouter with the Operator's approvals, as the plan's Phase 5 describes. This needs the real key, real spend, and human judgement on prompts, so it is a human ticket. Defects found go back into the tracker as new issues through triage; prompt tuning follows what the traces show.

Source: the plan's Phase 5 (live runs and manual verification).

**Blocked by:** 24 (README)

**Status:** ready-for-human

- [ ] All human work is committed once before the first Growth Loop, because the Kernel refuses a dirty tree
- [ ] `uv run ra wiki ingest docs/` fills the Wiki and `uv run ra wiki lint` is clean
- [ ] `uv run ra ask "Summarize docs/self-improving-loops.md into five bullet points for a new engineer."` runs a Task Loop and passes its Target Cases
- [ ] `uv run ra ask "Learn to answer questions about this repo's git history, e.g. who changed the gate last and why."` runs a Growth Loop against the repo-history frontier ladder; the Target Cases are approved by hand
- [ ] `uv run ra evals` shows no regression against the report before the Growth Loop
- [ ] `uv run ra improve --max-iterations 2` makes at most two Improvements
- [ ] Exactly one commit per accepted Improvement, authored by the Kernel, touching no Protected Path
- [ ] `uv run ra status` shows the accepted Improvement, its cost, the eval trend, and the frontier ratios; the Wiki index and log reflect the runs
