---
status: accepted
---

# Frontier Cases are the growth agenda; humans author the exam, the system proposes

A self-improving system needs a standing list of what it cannot do yet, and the eval datasets are already the specification (ADR 0005). So the growth agenda is a directory of Frontier Cases: eval files under `evals/frontier/`, one per capability, written by a human as a ladder of graded cases the system is expected to fail today. No new machinery is involved. A red Frontier Case is a Guard Case that the eval Sensor reports as a Finding, `ra improve` picks it, the Planner makes it a Target Case, and when the whole file is green the capability counts as proven in the Capability Inventory. The system may propose harder cases (when a file turns green the Librarian writes candidates as a Wiki open question) but never adds a Frontier Case itself. We rejected an Examiner agent and system-authored frontier files: an agent that writes its own exam is the eval-gaming risk the Reviewer exists to catch, and a human copying a YAML block is cheap.

## Consequences

- A capability is available to Triage only when its frontier file is fully green; the inventory shows the ratio so Triage can name the remaining rungs as the gap.
- Growth on a capability stalls when nobody has written its next rung; `ra status` surfaces the Librarian's proposals so the human sees it.
