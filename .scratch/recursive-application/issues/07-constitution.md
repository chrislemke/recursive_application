# 07: Constitution

**What to build:** Every agent's first instruction: a Kernel file under 80 lines in plain English that tells the system what it is, what it may change and how, when to grow, what it must never do, what only the human may grant, what counts as evidence, its budgets and approvals, and where the glossary and the three source documents are. A Kernel test enforces the line limit and the required vocabulary, so the charter cannot drift or bloat.

Source: spec section "The Constitution"; ADRs 0001, 0007, 0008, 0009, 0010; the glossary; the loop anatomy in the self-improving-loops source document.

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** ready-for-agent

- [ ] The seam (a loader returning the text, plus ordered tracer bullets) is written in the seams-document format and confirmed by the user before the first red test
- [ ] The eight required sections appear in the spec's order: identity, what it may change and how, when to grow, what it must never do, what only the human grants, evidence, budgets and approvals, pointers by name
- [ ] It says the Kernel orchestrates and agents never call each other, that growth happens only through a Growth Loop ending in a Kernel commit, and that a narrow new agent is preferred over widening an existing one
- [ ] It names the never-do list (Kernel, Protected Paths, dependencies, existing eval cases, Frontier Cases, push, sign) and routes such wishes to the human as Sensor Findings
- [ ] The Kernel test asserts fewer than 80 lines and that every glossary term the eight sections require (Kernel, Organism, Protected Path, Loop and its five phases, Iteration, Improvement, Growth Loop, Capability Gap, Capability Inventory, State Bundle, Specialist, Policy Ceiling, Frontier Case, Sensor Finding, Wiki, Run Record, Definition of Done, Watcher, and the five phase names) appears
- [ ] The file lives inside the Kernel package, a Protected Path
- [ ] All four checks exit 0
- [ ] Section 1 names the five phases as the five layers of a self-improving loop (sensors, policy, tools, quality gate, learning mechanism), says a loop without its learning layer is only an agent, and names the Kernel as the Watcher
- [ ] Section 2 says every addition is a loop element and that an agent without a dataset does not exist; section 6 says an action that left no trace, Run Record, or Wiki entry did not happen
