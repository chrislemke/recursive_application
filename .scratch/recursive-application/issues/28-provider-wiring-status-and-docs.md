# 28: Provider wiring, the status section, and the Operator docs

**What to build:** The `chatgpt:` branch of `model_factory`; `build_context` checking credentials through the module and building both tiers through the factory (the Judge Model as a `Model` instance); `ra status` running without a credential check and opening with a `## Providers` section that names each tier's Provider and whether its key or Sign-in is present; pydantic-ai's `UserError` mapped to exit 2; the README "Providers" section and the `.env.example` lines.

Source: the spec amendment of 2026-09-06 (Providers, stories 81 and 82); the seams document `thoughts/shared/plans/2026-09-06-provider-seams.md`, section "the wiring".

**Blocked by:** 26, 27

**Status:** ready-for-agent

**Owns:** `src/recursive_application/kernel/providers.py` (the `chatgpt` branch only), `src/recursive_application/kernel/cli.py`, `src/recursive_application/kernel/status.py`, `tests/kernel/test_providers.py` (bullet 4 only), `tests/kernel/test_cli.py`, `tests/kernel/test_status.py`, `README.md`, `.env.example`.

- [ ] `model_factory` builds `chatgpt:<model>` through `chatgpt_model` with the Sign-in path, clock, transport, and originator from Settings
- [ ] `require_credentials` deepens the `chatgpt` check to `load_sign_in` and `valid_for(now, ra_max_minutes)`, naming the expiry and `codex login`
- [ ] `build_context` calls `require_credentials`, passes the factory to `AgentRunner`, and gives the evals the Judge Model instance; `status` skips the check
- [ ] `ask` exits 2 naming `OPENAI_API_KEY` or `codex login` when the tier's credential is missing; `UserError` exits 2
- [ ] `render_status` opens with `## Providers` and reports keys as `set` or `missing`, the Sign-in as `valid until <instant> (plan <plan>)` or `not signed in (run codex login)`, and the served models from the Codex cache, never a value
- [ ] README and `.env.example` document the three Providers, the `codex login` step, and the terms note from ADR 0011
- [ ] All four checks exit 0
