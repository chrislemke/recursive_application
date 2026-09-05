# 21: Growth Loop: rejections, Actors, and Guard subset

**What to build:** Every way a Growth Iteration is refused or redirected, and the Specialist path. New tests that already pass reject the Iteration with the reason `no red`; a Plan with Python targets and no tests is rejected before Act; a Plan without Python targets skips the Test Writer and uses its red Target Cases as the red; a rejected Iteration is recorded as a lesson by the Librarian and undone with a hard reset and clean; a Plan naming an unknown or ineligible Actor is rejected before Act and counts as no progress; a Plan naming a registered Specialist invokes it in the Act slot; the Guard subset per Iteration is exactly the Target dataset, triage, answers, and the affected agents' datasets; wishes the system may not fulfil become policy findings.

Source: spec sections "Loop semantics", "Agent registry, roles, and Specialists", "Evals and traces" (Guard subset); ADRs 0007 and 0008; user stories 20, 21, 22, 25, 50, 56.

**Blocked by:** 20 (Growth Loop: accepted path)

**Status:** ready-for-agent

- [ ] New runner cases are added to the seam list before their tests
- [ ] New tests that already pass, exit code 5, or any other error reject the Iteration with `no red` and the output in the record
- [ ] A Plan with a Python target and empty tests is rejected before Act with a named reason
- [ ] A Plan without Python targets skips the Test Writer; its red Target Cases in the latest report count as the red
- [ ] A rejected Iteration leaves the tree at the previous commit, runtime data intact, and a lesson recorded by the Librarian
- [ ] An unknown or ineligible Actor is rejected before Act with a named reason and counts toward the no-progress stop
- [ ] A Plan naming a registered Specialist invokes that Specialist in the Act slot and nowhere else
- [ ] The Guard subset contains the Target dataset, triage, answers, and the datasets of affected agents only
- [ ] A Plan whose change would touch a Protected Path, the ceiling, the Coding Guide, or a frontier file is recorded as a policy finding addressed to the human instead of running
- [ ] All four checks exit 0
