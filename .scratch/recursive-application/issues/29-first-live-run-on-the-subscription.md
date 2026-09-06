# 29: First live run on the ChatGPT subscription

**What to build:** The system exercised once against the ChatGPT subscription and once against the OpenAI API with the Operator's credentials, the way ticket 25 does against OpenRouter. This needs the real Sign-in and human judgement, so it is a human ticket. Defects found go back into the tracker through triage.

Source: the spec amendment of 2026-09-06 (Providers, story 80); ADR 0011.

**Blocked by:** 28

**Status:** ready-for-human

- [ ] The user has read the research document's section A5 (terms) and decided to proceed
- [ ] `codex login status` reports a ChatGPT Sign-in before the run
- [ ] With `RA_MODEL=chatgpt:<model>` and `RA_JUDGE_MODEL=chatgpt:<model>` set to slugs `ra status` lists as served, `uv run ra status` opens with `## Providers`, a `valid until` line, and the models line; note the token's lifetime from `valid until` (Codex's source does not fix it)
- [ ] `uv run ra ask "Summarize docs/self-improving-loops.md into five bullet points for a new engineer." --yes` completes a Loop; the Run Record's cost is the list price, not 0
- [ ] `uv run ra evals --dataset triage` persists a report
- [ ] `grep -c Bearer .ra/traces/*.jsonl` prints 0 for every trace file, and no Run Record holds a token
- [ ] `codex login status` still reports a ChatGPT Sign-in afterwards, and `auth.json` has the modification time it had before (the Kernel wrote nothing)
- [ ] If any run ends on a 401 from an expired token, file the Codex-driven refresh follow-up (`codex app-server` account read) as a new ticket
- [ ] The same `ra status` and `ra ask` with `RA_MODEL=openai:<model>` and `OPENAI_API_KEY` set
