# 07: Constitution

**What to build:** Every agent's first instruction: a Kernel file under 80 lines in plain English that tells the system what it is, what it may change and how, when to grow, what it must never do, what only the human may grant, what counts as evidence, its budgets and approvals, and where the glossary and the three source documents are. A Kernel test enforces the line limit and the required vocabulary, so the charter cannot drift or bloat.

Source: spec section "The Constitution"; ADRs 0001, 0007, 0008, 0009, 0010; the glossary; the loop anatomy in the self-improving-loops source document.

**Blocked by:** 01 (Project skeleton, test harness, and the `ra` command stub)

**Status:** done

- [ ] The seam (a loader returning the text, plus ordered tracer bullets) is written in the seams-document format and confirmed by the user before the first red test
- [x] The eight required sections appear in the spec's order: identity, what it may change and how, when to grow, what it must never do, what only the human grants, evidence, budgets and approvals, pointers by name
- [x] It says the Kernel orchestrates and agents never call each other, that growth happens only through a Growth Loop ending in a Kernel commit, and that a narrow new agent is preferred over widening an existing one
- [x] It names the never-do list (Kernel, Protected Paths, dependencies, existing eval cases, Frontier Cases, push, sign) and routes such wishes to the human as Sensor Findings
- [x] The Kernel test asserts fewer than 80 lines and that every glossary term the eight sections require (Kernel, Organism, Protected Path, Loop and its five phases, Iteration, Improvement, Growth Loop, Capability Gap, Capability Inventory, State Bundle, Specialist, Policy Ceiling, Frontier Case, Sensor Finding, Wiki, Run Record, Definition of Done, Watcher, and the five phase names) appears
- [x] The file lives inside the Kernel package, a Protected Path
- [x] All four checks exit 0
- [x] Section 1 names the five phases as the five layers of a self-improving loop (sensors, policy, tools, quality gate, learning mechanism), says a loop without its learning layer is only an agent, and names the Kernel as the Watcher
- [x] Section 2 says every addition is a loop element and that an agent without a dataset does not exist; section 6 says an action that left no trace, Run Record, or Wiki entry did not happen

## Comments

**2026-09-05, implemented.** Red to green through the five tracer bullets of the Phase 2 seams document (`thoughts/shared/plans/2026-09-05-phase2-seams.md`): five tests in `tests/kernel/test_constitution.py`, importing only `CONSTITUTION_PATH` and `load_constitution` from `src/recursive_application/kernel/constitution.py`, plus `is_protected` from the paths module. The charter is `src/recursive_application/kernel/constitution.md`: 45 lines, eight `##` sections in the spec's order, one paragraph per line as the other Kernel documents do it. Section 1 names the five phases as the five layers, says a loop without its learning layer is only an agent, and names the Kernel as the Watcher; section 2 says every addition is a loop element and that an agent without a dataset does not exist; section 4 lists the never-do items and routes wishes to the human as Sensor Findings; section 6 says an action without trace, Run Record, or Wiki entry did not happen; section 8 points by backticked path at the glossary, the three source documents, the ADR directory, and the Coding Guide, so the documentation pointer test of ticket 12 can check them. The test holds the headings, the twenty-three required terms, and six load-bearing sentences as literals.

Deviations and judgement calls for the human to confirm:

- **The seams document is proposed, not confirmed.** The user asked for the tickets to continue unattended, so the seam was written in the agreed format and implementation went ahead against it; the first checkbox stays open until the user has read the section.
- **Two tests were green on their first run.** Bullet 2 (fewer than 80 lines) passed on the one-line stub that made bullet 1 green, and bullet 5 (the six verbatim sentences) passed because the full text was written to make bullet 4 green and already carried them. The document is one artifact; splitting its prose into three increments would have been theatre.
- **The line limit is measured on paragraphs-as-lines.** The file is 45 physical lines and about 950 words. Wrapped at 100 columns it would be roughly 110 lines, so the limit is a size bound only under the repo's one-paragraph-per-line convention. If the user wants the bound to bite on words, the test can count words instead.
- **The runtime directory is not backticked** in the text ("the Trace Store", "the Run Record") because `.ra/` is gitignored and would fail the pointer test on a fresh checkout.
- **The Constitution's location is `kernel/constitution.md`**, next to its loader, as the plan says; the Phase 1 seams document used `kernel/prompts/constitution.md` only as an example of a nested Protected Path.

The "All four checks exit 0" box is left for the orchestrator's whole-tree run; ruff format, ruff check, ty check, and the file's own pytest run all exit 0.

**2026-09-05, reviewed.** Two-axis review (standards, spec), applied: section 4 now names every Protected Path group (`thoughts/`, `.scratch/`, `CONTEXT.md`, the environment and ignore files), because the Constitution is the agents' only prose source for the rule and the answers rubric expects them to name it; `LINE_LIMIT` was deleted, since nothing read it and the test holds the literal; the section indices in the test are named. Kept, for the human: the line limit is measured on the repo's paragraph-per-line convention (45 lines, about 950 words, about 110 lines if wrapped), so the test bounds size only under that convention. Kept: "does not exist" and "did not happen" are generic phrases, but the test holds four more specific sentences beside them. All four checks exit 0 on the whole tree.
