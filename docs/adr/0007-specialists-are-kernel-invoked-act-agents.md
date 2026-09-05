---
status: accepted
---

# Specialists are Plan-selected Act-phase agents invoked by the Kernel

The Constitution promises that the system can add agents to itself. For that promise to hold, the Organism registry accepts entries beyond the seven required roles: a Specialist has a name, a prompt, a tool configuration within the Policy Ceiling, a model tier, the guides it reads, and the eval dataset that proves it. A Plan may name a Specialist as its Actor; the Kernel invokes it in the Act phase, in the slot the Worker or the Implementer would otherwise fill, and nowhere else. We rejected agents calling agents (delegation trees) and Specialists acting in Decide, Gate, or Learn: the Kernel stays the only orchestrator, so one linear trace per run and one place for budgets and breakers survive growth (ADR 0006), and the Gate is never performed by something the Organism wrote.

## Consequences

- A Growth Loop that adds a Specialist is one Improvement: prompt, registry entry, tool configuration, and a new dataset whose cases are the Plan's Target Cases. The Capability Inventory lists the Specialist only once that dataset is green.
- A Plan naming an unknown or ineligible Actor is rejected by the Kernel before Act and counts as an Iteration without progress.
