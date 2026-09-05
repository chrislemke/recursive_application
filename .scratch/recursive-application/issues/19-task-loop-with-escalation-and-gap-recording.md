# 19: Task Loop with escalation and gap recording

**What to build:** A Task that needs iteration runs the Task Loop: the Planner writes a Plan with Target Cases and optionally an Actor, the Kernel writes the cases as runtime data for that run and never into a tracked dataset, shows Plan and cases as YAML for approval unless skipped, the Actor (Worker by default) writes its output under the run's task directory, the Gate evaluates, and the Loop iterates until pass or a stop rule. A Capability Gap in the Plan or reported by the Actor escalates to a Growth Loop with a fresh approval; gaps not escalated are recorded as reflection findings.

Source: spec section "Loop semantics" (Task Loop); user stories 3, 4, 19, 23, 24; glossary entries Task Loop, Definition of Done, Actor.

**Blocked by:** 18 (Loop, Answer Mode, and `ra ask`)

**Status:** ready-for-agent

- [ ] New runner cases are added to the seam list before their tests
- [ ] A Task Loop that fails once then passes has two Iterations, its cases under the runtime directory for that run, and every tracked dataset unchanged
- [ ] The approval shows Plan and Target Cases as YAML and a refusal ends the run as aborted; `--yes` skips it
- [ ] The Actor's output lands under the run's task directory and is referenced from the Iteration record
- [ ] A gap in the Plan escalates to Growth with a fresh approval; a gap reported in the Worker output does the same
- [ ] Gaps that were recognised but not acted on are recorded as reflection findings and show up in the next Sense
- [ ] All four checks exit 0
