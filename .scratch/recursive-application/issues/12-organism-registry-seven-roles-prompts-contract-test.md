# 12: Organism registry: seven roles, prompts, registry contract test, documentation pointers

**What to build:** The Organism exposes one registry the Kernel can load and trust. Each entry carries a name, a Pydantic AI Agent with no model set, a model tier, the phases it may act in, its tool configuration, its guides, its prompt path, and the dataset that proves it. The seven required roles are present with the right output types; each has a prompt file holding only its own job; the coding roles list the Coding Guide as a guide. The Kernel's registry contract test is the test that protects the Kernel from a bad Improvement, and the documentation pointer test keeps the Coding Guide and the Constitution honest.

Source: spec sections "Agent registry, roles, and Specialists" and "The Coding Guide and the guides mechanism"; Testing Decisions seams 6 and 10; ADR 0007.

**Blocked by:** 03 (Data contracts and the Run Record), 07 (Constitution), 08 (Wiki module and seed Wiki), 09 (Policy Ceiling and Organism tool configurations), 11 (Seed eval datasets for the seven roles)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] The registry entry is a Kernel contract with the eight fields; loading the registry validates every tool configuration against the Policy Ceiling and the write scope and refuses to build an agent that exceeds them
- [ ] The seven roles exist with these output types: Triage decision, Plan, code report for both the Test Writer and the Implementer, Worker output, Review, and a text summary for the Librarian; the Reviewer is on the judge tier and the rest on the primary tier; phases follow the Loop (Triage and Planner decide, Test Writer, Implementer, and Worker act, Reviewer gates, Librarian learns)
- [ ] The Planner, Test Writer, Implementer, and Reviewer list the Coding Guide; Triage, Worker, and Librarian list nothing
- [ ] Seven prompt files exist, are non-empty, and hold only that agent's own job; each agent produces a valid contract under a test model
- [ ] The contract test fails on a missing role, a wrong output type, a missing guide, prompt, or dataset file, a tool configuration outside the ceiling or write scope, and a Specialist that acts outside the Act phase
- [ ] Affected agents for a diff are computed as the spec says: an agent whose prompt or dataset changed, and every agent when the registry or tools module changed
- [ ] The documentation pointer test checks that every backticked repo-relative path (a token containing a slash and no angle-bracket placeholder) in the Coding Guide and the Constitution exists
- [ ] All four checks exit 0
- [ ] Each prompt file opens by naming the agent's phase in the Loop and the artifact it produces; the contract test checks that a prompt mentions the phase its entry lists (ADR 0010)
