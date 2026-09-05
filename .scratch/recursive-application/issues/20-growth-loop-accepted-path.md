# 20: Growth Loop: accepted path

**What to build:** A Growth Loop that succeeds end to end. The Kernel refuses a dirty tree and holds a lock. The Planner writes a Plan naming its tests and Target Cases; the Kernel appends new Target Cases to the dataset the Plan names (nothing when the targets are existing Frontier Cases) and asks for approval unless skipped. When a target path is a Python file, the Test Writer runs first, the Kernel runs pytest on the changed test files and requires red by the spec's exit-code semantics, then the Implementer runs. The Kernel gathers the Gate inputs in order, running the four checks as subprocesses with a timeout, the evals over the Guard subset, the anomaly rules, and the Reviewer on the Judge Model with the Coding Guide. On acceptance the Librarian records the Improvement and the Kernel commits it, authored by the Kernel, unsigned, with a message beginning `ra:`.

Source: spec sections "Loop semantics" (Growth Loop) and "Gate"; ADRs 0002 and 0008; user stories 31, 32, 38, 52, 55, 57.

**Blocked by:** 19 (Task Loop with escalation and gap recording)

**Status:** ready-for-agent

- [ ] New runner cases are added to the seam list before their tests
- [ ] A dirty working tree is refused before anything runs; a held lock refuses a second run and is released afterwards
- [ ] New Target Cases are appended to the named dataset; existing Frontier Cases as targets append nothing
- [ ] With a Python target, the order is Test Writer, red check, Implementer; red is exit code 1 or a collection error naming a missing name
- [ ] The four checks run as subprocesses with a timeout and their results reach the Gate as check results with truncated output
- [ ] The Reviewer runs on the Judge Model with the Coding Guide in its instructions and its Review reaches the Gate
- [ ] Accepted: the Librarian is called, the commit exists with the Kernel author, no signature, and a message beginning `ra:`, and the Run Record holds the sha
- [ ] All four checks exit 0
