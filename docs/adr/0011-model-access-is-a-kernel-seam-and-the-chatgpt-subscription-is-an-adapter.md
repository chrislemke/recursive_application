---
status: accepted
---

# Model access is a Kernel seam, and the ChatGPT subscription is an adapter behind it

The spec ruled out "Codex or other provider integrations beyond a model string" and any custom Pydantic AI model class, and the Operator now wants a tier to run on a ChatGPT subscription instead of API credit. We keep the model string as the only configuration (`RA_MODEL`, `RA_JUDGE_MODEL`) and put one Kernel module behind the agent runtime's existing `model_factory` seam: it builds the model for both tiers from the name's scheme, checks the credentials that scheme needs, and for the new `chatgpt:` scheme reads the Codex CLI's Sign-in and adapts pydantic-ai's OpenAI Responses model to the ChatGPT backend at the HTTP transport. The Kernel never performs the login and never writes the Sign-in file: `codex login` stays the Operator's step, and refreshing stays Codex's job, because refresh tokens rotate, Codex's own writer is unlocked, and OpenAI's automation guidance is not to call the token endpoint yourself. A run whose token would expire before its wall-time budget ends is refused before it starts.

## Considered options

- **A Codex process as an Actor** (`codex exec`, `codex app-server`, or `codex mcp-server` performing the Act phase). Rejected: the run would use Codex's tools, not the Organism's tool configurations, so the Policy Ceiling, the write scope, the usage limits, the circuit breaker, and the Trace Store would not see it, and the Kernel would stop being the Watcher (ADR 0010).
- **A custom pydantic-ai `Model` subclass** for the backend. Rejected: it would duplicate the Responses request and response mapping the library already owns, and it is the thing the spec forbade; the difference between the API and the backend is a header set and a streaming requirement, which is a transport concern.
- **A local proxy** (an OpenAI-compatible gateway that holds the Sign-in). Rejected: a second process to run and a third place for credentials, for no gain over an in-process transport.

## Consequences

- Whether OpenAI allows the Sign-in outside the Codex products is the Operator's risk: the Codex documentation neither permits nor forbids it, calls API keys the right way to authenticate automation, and excludes generic OAuth clients from its runner guidance (research document, section A5). The Kernel identifies itself honestly by default; switching a tier back to a key is one environment variable.
- A subscription run reports cost at the OpenAI list price for model ids the price data knows, and 0 for the others (the backend's current default among them), so the token fallback is the budget rule there; the Run Record does not say which Provider ran.
- The Sign-in file is a secret outside the repo: the Policy Ceiling denies `.codex` to every tool, and no token may reach a trace, a Run Record, a message, or a `repr`.
- Adding a further Provider is a new scheme in one table, plus its adapter; nothing in the runtime, the Loop, or the evals changes.
