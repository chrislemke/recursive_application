---
status: accepted
---

# Every agent is a loop element and the Kernel is the watcher

The source document behind this system (`docs/self-improving-loops.md`) gives a loop five layers, sensors, policy, tools, quality gate, learning mechanism, says that deleting the fifth leaves an agent rather than a loop, and reduces to one instruction: build the watcher, a second agent whose only job is to see the first one fail and fix the cause. We decided to make that anatomy the invariant of the whole system rather than a design note. The five phases of every Loop are those five layers, and a capability exists only when all five are present for it: a registry entry must name the dataset that senses and gates it, its tools are bounded by the Policy Ceiling, and its failures become Sensor Findings and Wiki lessons. The watcher is the Kernel (Sensors, the Gate, `ra improve`), never an Organism agent, because a watcher the Organism could edit would stop watching. We rejected leaving the pattern as a pointer to the document: Triage has no file tools and nothing obliges the Worker to read, so the Constitution carries the anatomy inline and the State Bundle tells every agent which phase and Iteration it is in at every call.

## Consequences

- There is no agent without a loop in this system: a registry entry without a dataset never enters the Capability Inventory, and a Plan without Target Cases is rejected before Act.
- Every Plan reads as a loop: the evidence is the sensor reading, the change is the act, the Target Cases are the gate, the at-risk list and the Librarian's record are the learning.
- Growth may add sensors (eval cases), tools, gates, and lessons; it may never add a watcher of its own, and a wish to do so is a `policy` finding for the human.
- No Organism agent monitors another (ADR 0006, ADR 0007); the Constitution names the Kernel as the Watcher so agents know who watches them.
