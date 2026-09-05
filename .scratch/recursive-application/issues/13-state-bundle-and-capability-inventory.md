# 13: State Bundle and Capability Inventory

**What to build:** The Kernel renders, with no model call, the Capability Inventory and the State Bundle every agent receives. The inventory lists the registry's agents with their phases and tool names and descriptions, each marked proven or unproven by its dataset, the Wiki's capability pages, and each frontier capability as green over total, available only when the whole file is green. The State Bundle adds the capped repo tree with Organism paths marked editable, the eval summary as one line per dataset, the ten most severe open findings, the Wiki index, and the last three Run Records.

Source: spec section "State Bundle and Capability Inventory"; Testing Decisions seam 5; glossary entries Capability Inventory and State Bundle.

**Blocked by:** 08 (Wiki module and seed Wiki), 10 (Eval datasets: loading, reports, deltas, frontier ratios, append-only rule), 12 (Organism registry)

**Status:** ready-for-agent

- [ ] The seam is written in the seams-document format and confirmed by the user before the first red test
- [ ] Rendering is deterministic from a registry, Wiki pages, an eval summary, frontier ratios, findings, and Run Records; the same inputs give the same text
- [ ] Each agent is annotated proven or unproven from the eval summary of its dataset; a frontier capability shows its ratio and is available only when green equals total
- [ ] The tree shows top-level entries and the Organism tree only, Organism paths marked editable and Protected Paths read-only
- [ ] The cap holds: ten findings by severity, three Run Records, one line per dataset
- [ ] The inventory renders as a short markdown block that Triage can cite as the sole source of "available"
- [ ] All four checks exit 0
- [ ] The State Bundle opens with the Loop position: run id, Mode, Iteration number and limit, the phase and role this agent acts in, and the previous Iteration's Gate outcome when there is one (ADR 0010)
