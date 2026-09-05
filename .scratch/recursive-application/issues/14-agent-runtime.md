# 14: Agent runtime

**What to build:** One Kernel entry point runs any registry entry: it assembles the instructions in order (Constitution, guides, the agent's prompt, the State Bundle), injects the model for the entry's tier from Settings, applies the usage limits from Settings with the higher request limit for the coding roles, runs under the entry's breaker, records Usage, and is traced. Agents in the registry never set a model themselves.

Source: spec sections "The Coding Guide and the guides mechanism" (instruction order), "Agent registry" (model injection), "Loop semantics" (budgets and breaker); the plan's agent runtime item.

**Blocked by:** 02 (Protected Path rule, write scope, and Settings), 04 (Trace Store), 05 (Circuit breaker), 12 (Organism registry), 13 (State Bundle and Capability Inventory)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] Instructions arrive in the order Constitution, guides, prompt, State Bundle, and a guide listed by an entry is read from disk
- [ ] The model is chosen by tier from Settings; a registry agent with a model set is refused
- [ ] Request and cost limits come from Settings; the coding roles get the coder request limit; exceeding a limit raises and the Usage so far is recorded
- [ ] The run is wrapped in the breaker named after the entry; an open breaker raises without a model call
- [ ] The returned value is the entry's contract and the Usage carries requests, tokens, and cost when available
- [ ] Every test uses a test or function model; nothing reaches the network
- [ ] All four checks exit 0
