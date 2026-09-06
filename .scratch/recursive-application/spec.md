# Spec: Recursive Application (`ra`), a CLI agent system that grows itself

Status: ready-for-agent
Date: 2026-09-05
Revised: 2026-09-05, after the second grilling (coding agents, small agents, evals as the growth agenda). The twenty-two decisions from that session are folded in below. Written alongside this revision: the glossary terms Test Writer, Implementer, Specialist, Actor, Frontier Case, Policy Ceiling, and Coding Guide; ADRs 0007 to 0009; `docs/coding-guide.md`; the verbatim copies under `docs/pydantic-ai/` and `docs/tdd/`; the seed datasets under `evals/frontier/`; and the amended Phase 1 seams document.
Amended: 2026-09-05, third pass. The loop anatomy of `docs/self-improving-loops.md` becomes an invariant (ADR 0010, glossary term Watcher): the Constitution carries it inline, the State Bundle carries the Loop position, the Coding Guide gains the loop-element table, prompts open with their phase, and the evals gain two awareness cases. Tickets 07, 11, 12, 13, and 18 carry the changes.
Builds on: the implementation plan of 2026-09-05 (five phases), the Phase 1 seams document, `CONTEXT.md`, and ADRs 0001 to 0009. Where this spec and the plan differ, this spec wins.

## Problem Statement

I want a command-line system that I can hand any request to and that treats "I cannot do this yet" as the start of work rather than the end of it. Today the repo holds a glossary, nine ADRs, three source documents on self-improving loops, a plan, and reference copies, but no code. Four things the plan leaves implicit have to become explicit before implementation starts.

First, the agents have no standing knowledge that they are allowed to change their own architecture. A Task the system cannot handle should lead to a Growth Loop that adds a tool, a prompt, knowledge, or a whole new agent, not to a weak Answer. That awareness must be present in every agent at every step, not something that has to be remembered.

Second, the plan verifies the Organism's edits with tests and evals only. Code the system writes into itself should also be formatted, lint-clean, and type-correct, with the same tools I would use by hand: ruff and ty, alongside pytest and Logfire, as first-class project tooling and as Gate checks.

Third, the agent that writes the system's code starts every run with nothing but its prompt. It has to know how code is written here, test-first, at agreed seams, in this repository's Python and Pydantic AI conventions, before it writes a line, and that knowledge has to be stable enough that the system cannot erode it. Asking one Coder to "do TDD" is a hope, not a rule.

Fourth, the eval datasets prove what the system can do today but say nothing about what it should learn next. "Analyse this philosophical text" should trigger growth, and the eval set has to keep pace with the system's capabilities so it stays a quality gate and a source of lessons rather than a benchmark passed once.

Underneath all of it: the initial implementation and everything the system later builds into itself follow KISS, YAGNI, and DRY, and prefer more, narrower agents over fewer, broader ones.

## Solution

`ra` is a CLI built on Pydantic AI. Every request is a Task that runs through one closed Loop with five phases (Sense, Decide, Act, Gate, Learn), orchestrated by a deterministic, human-owned Kernel. Triage performs a Reflection on every Task, comparing the capabilities the Task needs against the Capability Inventory, and assigns exactly one Mode: Answer, Task Loop, or Growth Loop. A recognised Capability Gap switches the Mode to Growth.

Seven agents fill the Loop's roles: Triage, Planner, Test Writer, Implementer, Worker, Reviewer, Librarian. In a Growth Loop the Act phase is two steps with disjoint write scopes: the Test Writer turns the Plan's named tests into failing pytest tests, the Kernel runs them and requires red, then the Implementer makes them pass and the Kernel requires green. The Planner, Test Writer, Implementer, and Reviewer start every run with the Coding Guide, a Kernel document that maps the TDD loop onto these roles and points at verbatim copies of the Pydantic AI skill and the TDD skill kept under `docs/`.

The Constitution, prepended to every agent's instructions, tells the agents what the system is, that it may change its own agents, prompts, tools, eval datasets, and Wiki, that it may add new agents (Specialists) and should prefer a narrow new agent over a wider old one, that recognising a Capability Gap is the trigger to grow, and what it must never touch (the Kernel, dependencies, Protected Paths, existing eval cases). The Capability Inventory in every State Bundle keeps that self-knowledge current.

What the system should learn next is a directory of Frontier Cases: `evals/frontier/<capability>.yaml`, one human-written ladder of graded cases per capability, red today by design. A red Frontier Case is a Sensor Finding, `ra improve` picks it, and a capability counts as available only when its whole file is green. When a file turns green the Librarian proposes harder rungs as a Wiki open question; the human decides which become cases.

An Improvement is accepted only when the Gate passes: no Protected Path touched, existing eval cases unchanged, ruff format, ruff check, ty check, and pytest green, Target Cases improved, Guard Cases not regressed, no new trace anomalies, and a positive Reviewer verdict on the Judge Model. The Kernel then commits it. Rejected Iterations are reset. After an accepted Improvement, `ra ask` re-runs Triage on the original Task once and carries on if the gap is closed. Everything the system does is traced to a local Trace Store and recorded in Run Records and the Wiki, so it can read its own behaviour and so can I.

## User Stories

Actors: the Operator (the human running `ra`), the Kernel maintainer (the human editing the Kernel), the seven agents, and a Specialist (an agent the system adds to itself).

Running the system

1. As an Operator, I want to run `ra ask` with one request, so that the system decides on its own whether to Answer, run a Task Loop, or run a Growth Loop instead of me choosing.
2. As an Operator, I want a direct Answer for a request the system can already satisfy, so that I do not pay for a loop I do not need.
3. As an Operator, I want a Task Loop to iterate on my output against Target Cases until they pass, so that I get a result that meets a stated Definition of Done rather than a first draft.
4. As an Operator, I want the Plan and Target Cases shown as YAML for approval before a Loop changes code or spends real budget, so that the Definition of Done is mine.
5. As an Operator, I want a `--yes` flag that skips approvals, so that I can run the system unattended.
6. As an Operator, I want `ra improve` to pick the most severe open Sensor Finding and make one Improvement per Iteration, so that the system gets better without a request from me.
7. As an Operator, I want `ra improve --goal` to steer growth toward a theme, so that unattended improvement follows my priorities.
8. As an Operator, I want `ra evals` to run datasets and persist a report, so that model behaviour is measured separately from deterministic tests.
9. As an Operator, I want `ra status` to show breaker states, open Sensor Findings, recent runs, total cost, the eval trend, and the frontier ratios, so that I see the system's health and its agenda at a glance.
10. As an Operator, I want `ra wiki ingest` and `ra wiki lint`, so that the Wiki stays fed and consistent.
11. As an Operator, I want to be asked for feedback after an Answer when I am at a terminal, so that my judgement becomes a Sensor Finding.
12. As an Operator, I want clarifying questions printed and the run stopped when Triage finds a clarification gap, so that the system does not guess what I meant.
13. As an Operator, I want iteration, wall-time, and USD budget limits with defaults and flags, so that no run can run away.
14. As an Operator, I want the run's outcome (accepted, rejected, aborted, error) printed and reflected in the exit code, so that scripts and I can act on it.
15. As an Operator, I want a best-effort Answer with a warning when the judge never passes it within the limits, so that I still get something useful and the failure is recorded.
16. As an Operator, I want `ra ask` to re-run Triage on my original request once after an accepted Improvement and carry on when the gap is closed, so that a hard question ends in an answer rather than in "run it again".

Knowing it can grow

17. As an Operator, I want every agent to know from its first instruction that the system can change its own architecture within the Kernel's policy, so that growth is always an available move rather than an occasional idea.
18. As an Operator, I want Triage to perform a Reflection on every Task against the Capability Inventory, so that a Capability Gap is recognised before work starts.
19. As an Operator, I want a tool, knowledge, connection, or skill gap to switch the Mode to Growth, so that the system fixes the cause instead of producing a weak result.
20. As an Operator, I want gaps that need my decision (network access, a new dependency, a Kernel change) named as such in the Plan, so that I grant or refuse them explicitly.
21. As an Operator, I want the system to be able to add a Specialist agent with its own prompt, tools within policy, guides, and eval dataset, so that "adding more agents" is a real move.
22. As an Operator, I want the Planner to be able to name a registered Specialist as the Actor of a Task Loop or the Implementer's slot in a Growth Loop, so that a Specialist is used once it exists.
23. As an Operator, I want the Worker to report gaps it hits while producing output, so that awareness during the Act phase is not lost.
24. As an Operator, I want gaps that were recognised but not acted on to become Sensor Findings, so that `ra improve` can pick them up later.
25. As an Operator, I want the Constitution to state what the system must not do and to route those wishes to me as proposals, so that awareness of power comes with awareness of limits.
26. As an Operator, I want to ask "what can you do right now and what would you need to grow?" and get an answer grounded in the Capability Inventory, so that the self-model is verifiable.
27. As an Operator, I want a capability counted in the inventory only when its eval dataset is green, so that the system never believes it can do something it has not proven.
28. As an Operator, I want the Librarian to record every accepted capability in the Wiki with a breadcrumb to the commit and the evals, so that learned abilities appear in later inventories.
29. As an Operator, I want a declined gap remembered as a Wiki lesson, so that the system does not propose the same Growth Loop on every run.
30. As an Operator, I want the Constitution to prefer adding a narrow agent with one job over widening an existing one, so that orchestration and traces stay legible as the system grows.

Writing code test-first

31. As an Operator, I want the Growth Loop's Act phase split into a Test Writer and an Implementer with disjoint write scopes, so that the failing test is written by an agent that cannot also write the code.
32. As an Operator, I want the Kernel to run pytest between them and reject the Iteration when the new tests already pass, so that red before green is a rule rather than a request.
33. As an Operator, I want the Planner to name the tests as one-sentence behaviours at a public interface, so that the Test Writer has a seam and not a guess.
34. As an Operator, I want coding agents to start with the Coding Guide and be pointed at the Pydantic AI and TDD references copied into the docs, so that they code with the right context and against the library version I installed.
35. As an Operator, I want the Reviewer to reject tautological tests, tests that reach past the interface, and tests that were never red, so that the test suite stays a specification.
36. As a Kernel maintainer, I want each registry entry to list the guides it receives, so that a Specialist can carry its own guide without a Kernel change.
37. As a Kernel maintainer, I want lessons the system learns while coding to land in the Wiki and never in the Coding Guide, so that the rules stay stable while the experience grows.

Writing better code

38. As an Operator, I want every Improvement to pass ruff format, ruff check, ty check, and pytest before evals run, so that the Organism stays formatted, lint-clean, and type-correct.
39. As an Operator, I want the Implementer to have ruff and ty available and to be told to run them before reporting, so that most Gate failures are caught inside the Act phase.
40. As an Operator, I want the Test Writer's and the Implementer's reports to list which checks ran and passed, so that the Gate and I see whether they verified their own work.
41. As a Kernel maintainer, I want ruff and ty configured in the project file with pinned version ranges and pyright removed, so that there is exactly one type checker.
42. As a Kernel maintainer, I want the Kernel itself clean under the same checks, so that the Gate's bar is one the Kernel meets.
43. As an Operator, I want the output of a failed check stored, truncated, in the Run Record, so that I can see why an Iteration failed.

Evals as the growth agenda

44. As an Operator, I want a directory of Frontier Cases, one file per capability, so that what the system should learn next is a set of files I can read and edit.
45. As an Operator, I want each frontier file to be a ladder of graded cases, so that one Growth Iteration can climb one rung.
46. As an Operator, I want a red Frontier Case to be a Sensor Finding that `ra improve` picks, so that growth needs no request from me.
47. As an Operator, I want a capability counted as available only when its whole frontier file is green, with the ratio shown in the inventory, so that Triage names the remaining rungs as the gap.
48. As an Operator, I want the Librarian to propose harder cases as a Wiki open question when a frontier file turns green, and never to add them itself, so that the system proposes and I author the exam.
49. As an Operator, I want judge-based cases to pass or fail on one run, with a newly failing Guard Case re-run once before it counts as a regression, so that flakiness costs one retry and not a rejected Iteration.
50. As an Operator, I want only the datasets affected by a diff, plus triage and answers, run per Iteration, and the full suite through `ra evals`, so that Iterations stay fast and the full suite still catches the rest.
51. As an Operator, I want Task Loop cases kept as runtime data and only Growth Loop Target Cases appended to tracked datasets, so that datasets describe what the system can do, not what it once did.

Keeping the Kernel safe

52. As a Kernel maintainer, I want one Protected Path rule checked against the git diff before any commit, so that the Organism can never modify the Kernel however it produced the change.
53. As a Kernel maintainer, I want the tools' write scope to be an allowlist of tracked Organism paths, so that a write into a gitignored path can never slip past the diff check.
54. As a Kernel maintainer, I want a Kernel-owned Policy Ceiling that Organism tool configurations are validated against, so that the Organism can reconfigure its tools without widening its own powers.
55. As a Kernel maintainer, I want the Kernel to refuse a Growth Loop on a dirty working tree and to hold a lock file, so that a reset never destroys my uncommitted work.
56. As a Kernel maintainer, I want rejected Iterations undone with a hard reset and clean, so that the tree is always at a known commit.
57. As a Kernel maintainer, I want Kernel commits authored by the Kernel and unsigned regardless of the global git configuration, so that unattended runs never block on a signing prompt.
58. As a Kernel maintainer, I want `git` kept off the shell allowlist, so that no model can commit or push.
59. As a Kernel maintainer, I want a Kernel test that checks the Organism's agent registry against the Kernel contract, so that an Improvement that breaks the registry fails the Gate.
60. As a Kernel maintainer, I want existing eval cases to be append-only and written only by the Kernel from approved Plans, so that the system cannot pass by editing the exam.
61. As a Kernel maintainer, I want the Reviewer to run on the Judge Model and look for eval gaming, so that acceptance is not judged by the model that wrote the change.
62. As a Kernel maintainer, I want one circuit breaker per registry name, persisted across processes, so that a flaking model stops a run fast instead of burning budget.
63. As a Kernel maintainer, I want the Constitution and the Coding Guide to live in Protected Paths, so that the system cannot rewrite its own charter or its own coding rules.

Evidence and memory

64. As an Operator, I want every agent run traced to a local JSONL Trace Store and, when a token is set, to Logfire cloud, so that I can read the system's behaviour offline or in a UI.
65. As an Operator, I want deterministic trace anomaly rules to produce Sensor Findings, so that the system watches itself.
66. As an Operator, I want one Run Record per run holding every Iteration's Plan, reports, Gate result, and outcome, so that I can replay what happened.
67. As an Operator, I want eval reports persisted with a pointer to the latest one, so that the Gate can compare before and after.
68. As an Operator, I want the Wiki to hold an index, an append-only log, and topic pages, so that memory is legible to me and to the Sensors.
69. As an Operator, I want `ra wiki lint` to report orphan pages and pages missing from the index, so that the Wiki does not rot.
70. As a Librarian, I want write access limited to the Wiki, so that the Learn phase can never alter code.

Agents

71. As Triage, I want the Capability Inventory, the Wiki index, and recent Run Records in my State Bundle, so that my Reflection is grounded in facts rather than recall.
72. As a Planner, I want read-only file and git tools, the current Sensor Findings, and the Coding Guide, so that my Plan cites evidence, names one change and its tests, and predicts its impact.
73. As a Test Writer, I want a file tool that writes only under the Organism tests and a shell with pytest, so that I can make a test red and prove it.
74. As an Implementer, I want a file tool that writes only under the Organism package and a shell with `uv`, `pytest`, `python`, `ruff`, `ty`, and read-only utilities, so that I can make tests green and verify the checks without leaving the sandbox.
75. As a Worker, I want read-only tools only, so that I can never edit code in Answer or Task Loop Mode.
76. As a Reviewer, I want the diff, the Plan, the eval deltas, and the Coding Guide, so that I can judge whether the diff does what the Plan says and whether its tests are real.
77. As a Specialist, I want to be registered with a name, prompt, tools, model tier, guides, and eval dataset, so that the Kernel can invoke me and the inventory can count me.

Tests

78. As a Kernel maintainer, I want `uv run pytest` green offline in seconds with all model requests disabled, so that the Gate's deterministic checks stay deterministic.
79. As a Kernel maintainer, I want tests written only at agreed seams, so that refactoring inside a module does not break them.

## Implementation Decisions

### Project and tooling

- Python 3.12, `uv` for environments and locking, src layout, the `ra` console script. Runtime dependencies stay as planned: `pydantic-ai-slim[openrouter]`, `pydantic-evals`, `logfire`, `pydantic-ai-harness`, `typer`, `pydantic-settings`.
- The dev dependency group is `pytest`, `ruff`, and `ty`. `pyright` is removed from the dev group and from the project file. Versions verified on 2026-09-05: ruff 0.16.6, ty 0.0.78 (pinned below 0.1 because it is pre-1.0), pytest 9.1.1, logfire 5.0.0, pydantic-ai-slim 2.40.0, pydantic-evals 2.40.0, pydantic-ai-harness 0.29.0.
- Ruff keeps line length 100 and target 3.12. The rule selection is the existing pycodestyle, pyflakes, isort, pyupgrade, and bugbear groups extended with the simplification, pathlib, naming, and Ruff-specific groups. Formatting is ruff's.
- ty is configured in the project file for Python 3.12 over the source and test roots. Errors fail a check; warnings are reported as notes.
- Four commands define "clean": `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check`, `uv run pytest`. The Kernel runs them as subprocesses; the Test Writer and the Implementer may run them too. The Kernel must be clean under all four before the first Growth Loop, because the Gate applies them to the whole tree.
- Two verbatim reference copies live under `docs/`, both Protected: `docs/pydantic-ai/` (the `building-pydantic-ai-agents` skill shipped inside the installed `pydantic_ai` package: `SKILL.md` and eleven references) and `docs/tdd/` (the mattpocock TDD skill: `SKILL.md`, `tests.md`, `mocking.md`). Each directory has a README naming source, version, date, and the refresh rule: re-copy when the dependency or the plugin is upgraded, which is a human-only change. Copies rather than pointers into `.venv/` because the system runs outside Claude Code and the human vets what the agents read.
- The Claude Code settings enable a pyright LSP plugin. That file is a Protected Path and a human decision; it is not touched by this work.

### Kernel, Organism, Protected Paths, and the write scope

- ADR 0001 stands. The Protected Path rule lives in one Kernel module and is checked against the git diff before every commit. Protected directories: the Kernel package, the Kernel tests, `.claude`, `docs`, `thoughts`, and `.scratch`. Protected files: `pyproject.toml`, `uv.lock`, `.env`, `.env.example`, `.gitignore`, `CONTEXT.md`.
- New: the write scope for tools is an allowlist, in the same module: `src/recursive_application/organism/**`, `tests/organism/**`, `evals/**`, `wiki/**`, `README.md`. Every other path is read-only for every tool, including `.venv/`, `.ra/`, and the caches, because a write there never reaches `git diff`. Reads are denied for `.env` and `.git/`. Per-agent write scopes are subsets: Test Writer `tests/organism/**`; Implementer `src/recursive_application/organism/**` and `README.md`; Librarian `wiki/**`; Planner, Worker, Reviewer, Triage nothing; a Specialist whatever its configuration names inside the allowlist. No agent writes under `evals/`: the Kernel appends Target Cases from approved Plans, and the human writes Frontier Cases.
- The Policy Ceiling, Kernel-owned: the commands no shell tool may allow (`git`, package managers' install, add, and remove commands, network clients, anything that deletes recursively), the paths no tool may read (`.env`, the git directory), the write-scope allowlist, and the fact that no tool may reach the network. The Organism owns its tool configurations (which commands and paths each agent gets) and the Kernel validates every configuration against the ceiling when it loads the registry, refusing to build an agent that exceeds it. Widening the ceiling is a Kernel change and therefore a human decision. The shell tool stays the harness `Shell` with an allowlist; the Kernel does not count tools per agent. "Small agents" is guidance in the Constitution and the Coding Guide, not a rule.

### The Constitution

- A Kernel file under 80 lines, in plain English, prepended to every agent's instructions. Its required content, in this order:
  1. Identity: a CLI system whose main job is to work on itself through closed Loops; the five phases named as the five layers of a self-improving loop (Sense is the sensor layer, Decide the policy layer, Act the tool layer, Gate the quality gate, Learn the learning mechanism), with the reminder that a loop without its learning layer is only an agent; the Kernel orchestrates, agents never call each other, and the Kernel is the Watcher over every agent.
  2. What it may change, and how: its agents (improving the seven roles and adding Specialists), prompts, tools within the Policy Ceiling, eval datasets by appending cases through Plans, Organism tests, and the Wiki. Prefer adding a narrow agent with one job over widening an existing one. Every addition is a loop element: a new capability comes with the dataset that senses and gates it, tools within the Policy Ceiling, and a place for its lessons; an agent without a dataset does not exist. Growth happens only through a Growth Loop that ends in a Kernel commit.
  3. When to grow: recognising a Capability Gap is the trigger. Triage reflects on every Task; the Planner escalates a Task Loop when the Task cannot be met without an Organism change; the Worker reports gaps it meets; a red Frontier Case is a standing gap; gaps not acted on become Sensor Findings for `ra improve`. Growth is not the first move when current capabilities suffice.
  4. What it must never do: edit the Kernel or any Protected Path, change dependencies, change or delete existing eval cases, add Frontier Cases, push, or sign. Such wishes are recorded as Sensor Findings addressed to the human.
  5. What only the human may grant: network access, new dependencies, Kernel changes, widening the Policy Ceiling, new Frontier Cases.
  6. Evidence: the Capability Inventory in the State Bundle is the current self-model; the Wiki is memory; traces and Run Records are the record; git history is readable. An action that left no trace, Run Record, or Wiki entry did not happen, so every action leaves one.
  7. Budgets and approvals: one change per Iteration, Definition of Done approved by the human unless approval is skipped, stop rules.
  8. Pointers by name to the glossary and the three source documents.
- A Kernel test asserts the line limit and that every glossary term the Constitution is required to explain appears in it, the five phase names and Watcher included. An eval dataset checks the behaviour the text is meant to produce (see Testing Decisions).

### The Coding Guide and the guides mechanism

- `docs/coding-guide.md` is a Kernel document, written with this revision. Content: the four-step loop by role (Planner writes the seams as `Plan.tests`; Test Writer goes red; Implementer goes green; Reviewer judges the diff against the Plan), each step ending on its completion criterion; the four checks; Python conventions; the two Pydantic AI overrides the library reference cannot know (agents never set a model, instructions are assembled by the Kernel); the pointer rule for `docs/pydantic-ai/` (read `SKILL.md`, then exactly one reference) and `docs/tdd/`; and the "where things live" table. Amended 2026-09-05: a section "Every addition is a loop element" with a five-row table (layer, phase, what the Plan names) that the Planner fills for any new capability and the Reviewer checks; it states that the Kernel is the Watcher and that no monitoring agent is ever added to the Organism.
- Each registry entry has `guides: list[str]`, repo-relative paths the Kernel prepends after the Constitution and before the agent's own prompt. The Planner, Test Writer, Implementer, and Reviewer list the Coding Guide; Triage, Worker, and Librarian list nothing. A Specialist lists what it needs. The registry contract test requires every listed guide to exist.
- Lessons the system learns while coding go to `wiki/pages/lessons/` through the Librarian. The guide is never edited by the system; a wish to change it is a `policy` Sensor Finding.

### Agent registry, roles, and Specialists

- The Organism exposes one registry. Each entry has: a name, the Pydantic AI Agent (no model set), the model tier (`primary` or `judge`), the phases it may act in, its tool configuration, `guides`, `prompt_path`, and `dataset`, the eval file that proves it. The Kernel injects the model from settings at run time. Each prompt file opens by naming the agent's phase in the Loop and the artifact it produces (its output contract, a file, or a Wiki entry); the registry contract test checks that a prompt mentions the phase its entry lists.
- Seven names are required roles: Triage, Planner, Test Writer, Implementer, Worker, Reviewer, Librarian. The Kernel looks them up by name for the Loop phases. A registry missing a required role, or a role whose output type does not match the Kernel contract, fails the Kernel's registry contract test, so an Improvement that breaks it fails the Gate.
- Any further entry is a Specialist (ADR 0007): an Organism agent, added by the system, that the Kernel may invoke in the Act phase when a Plan names it. Specialists act only in Act, never in Decide, Gate, or Learn, and never call other agents.
- The Plan's `actor` field names the registry entry that fills the Act slot. Default: Worker in a Task Loop, Implementer in a Growth Loop. Answer Mode has no Plan and always uses the Worker. The Test Writer step is fixed by the Kernel and not selectable. A Plan naming an unknown or ineligible Actor is rejected by the Kernel before Act with a named reason and counts as an Iteration without progress.
- A Growth Loop that adds a Specialist must add its prompt, its tool configuration within the ceiling, its registry entry, and name its dataset. The dataset may be an existing frontier file (the usual case: the Specialist exists to climb that ladder) or a new `evals/<specialist>.yaml` whose cases are the Plan's Target Cases. The Capability Inventory lists a Specialist only once that dataset is green.
- Affected agents for a diff, used by Guard selection: an agent is affected when its `prompt_path` or its `dataset` changed, or when the registry module or the tools module changed, which affects every agent.

### Data contracts

- All contracts are frozen Pydantic models that reject unknown fields and serve as Pydantic AI output types, as in the seams document. Changes relative to that document:
  - `Plan` gains `tests: list[str]` (one-sentence behaviours at a public interface, default empty) and `actor: str | None`. The Kernel rejects, before Act, a Plan whose target paths include a `.py` file and whose `tests` is empty.
  - `CheckResult(name, passed, output)` with `name` one of `ruff-format`, `ruff-check`, `ty`, `pytest`, and `output` truncated to 2,000 characters.
  - `CodeReport(summary, changed_files, checks: list[CheckResult])` replaces `CoderReport` and is returned by both the Test Writer and the Implementer.
  - The Worker returns `WorkerOutput(content, gaps: list[CapabilityGap])` instead of a bare string.
  - `SensorFinding.source` gains `reflection` (gaps recorded by Triage, Planner, or Worker that were not acted on) and `policy` (Protected Path, ceiling, guide, or frontier wishes addressed to the human). Frontier findings use the source `evals` and name the capability and rung in `details`.
  - `GateResult(passed, checks: list[GateCheck])` with `GateCheck(name, status: passed | skipped | failed, excerpt)`.
  - `IterationRecord` gains `test_report: CodeReport | None` and renames `coder_report` to `code_report: CodeReport | None`.
- Everything else (Mode, Outcome, CapabilityGap, Reflection, TriageDecision, EvalCase, Review, Usage, RunRecord, RunStore) stays as specified in the seams document.

### State Bundle and Capability Inventory

- The Kernel assembles the State Bundle deterministically with no model call: the Capability Inventory, the repo tree, the latest eval summary, the open Sensor Findings, the Wiki index, and recent Run Records. It is injected as instructions after the Constitution, the guides, and the agent's own prompt. It opens with the Loop position: the run id, the Mode, the Iteration number and its limit, the phase this agent is acting in and its role name, and the previous Iteration's Gate outcome when there is one, so every agent knows where in the Loop it stands at every call (ADR 0010). Size cap: the tree shows top-level entries and the Organism tree only, Organism paths marked editable and Protected Paths read-only; the ten most severe open findings; the last three Run Records; the eval summary as one line per dataset.
- The Capability Inventory is built from the registry (agents, their phases, their tool names and descriptions, each annotated proven or unproven by its dataset), the Wiki's capability pages, and the frontier files as `<capability>: <green>/<total>`. A frontier capability is available only when green equals total; the ratio is shown so Triage can name the remaining rungs as the gap. The inventory is rendered as a short markdown block and is the sole source Triage may cite for "available" in the Reflection.

### Loop semantics

- Answer: no Planner. The Kernel builds one Target Case (the request with the generic answer rubric, a Kernel constant). The Worker produces the output; the Gate runs the judge; on failure the next Iteration carries the judge's reason. After the iteration limit the best output is returned with a warning and a Sensor Finding.
- Task Loop: the Planner writes a Plan with Target Cases (and optionally an Actor); the Kernel writes the cases to `.ra/tasks/<run_id>/cases.yaml`, runtime data that is never tracked; approval unless skipped; the Actor produces output to `.ra/tasks/<run_id>/output.md`; the Gate evaluates; iterate until pass or a stop rule. A Capability Gap in the Plan, or one reported by the Actor, escalates to Growth with a fresh approval. Gaps not escalated are recorded as `reflection` findings.
- Growth Loop: requires a clean tree and the lock. The Planner writes the Plan, its tests, and its Target Cases; the Kernel appends new Target Cases to the dataset the Plan names (nothing is appended when the targets are existing Frontier Cases); approval unless skipped. Act: when any target path is a `.py` file, the Test Writer runs first and the Kernel then runs `uv run pytest <changed test files>`; red means exit code 1 (tests collected and failed) or a collection error whose output names a missing name (`ImportError`, `ModuleNotFoundError`, `AttributeError`); exit code 0, exit code 5 (nothing collected), or any other error rejects the Iteration with the reason `no red` and the output. Then the Actor (Implementer by default) runs. When no target path is a `.py` file the Test Writer is skipped and the Target Cases, red in the latest report, are the red. The Gate runs; accepted Improvements are recorded by the Librarian and committed by the Kernel with a message beginning `ra:`; rejected Iterations are recorded as a lesson by the Librarian and reset by the Kernel.
- After an accepted Improvement in `ra ask`, the Kernel re-runs Triage on the original Task once. Answer or Task Loop: run it under the remaining budgets. Growth again: stop, print what was added and what is still missing, exit 1. `ra improve` continues to the next finding until a stop rule.
- Stop rules: iteration limit (default 5), wall time (default 30 minutes), USD budget through Pydantic AI usage limits summed over the run with a token fallback, no progress for two Iterations, or an open breaker. Breaker: three consecutive failures open it, half-open after 60 seconds, one breaker per registry name.
- Triage with a clarification gap ends `ra ask` after printing the questions; nothing else runs.

### Gate

- The Gate is a pure function over its inputs (diff paths, changed eval cases, check results, eval deltas, trace anomalies, Review) returning a `GateResult`, so it is table-testable. The Kernel gathers the inputs in this order and stops at the first failure to save cost:
  1. No Protected Path in the diff, and no path outside the write scope.
  2. No existing eval case changed or deleted.
  3. ruff format check, ruff check, ty check, pytest, each as a subprocess with a timeout. Pytest here is the green of ADR 0008; the red check ran inside Act.
  4. Evals: Target Cases improved and Guard Cases not regressed, compared against the latest persisted report, over the Guard subset defined under Evals.
  5. No new trace anomalies in the Iteration's spans.
  6. Reviewer verdict positive, run on the Judge Model, with the Coding Guide in its instructions so it applies the test rules.
- Answer and Task Loop Iterations use only steps 4 to 6 (there is no diff). The Reviewer is skipped in Answer Mode; the judge evaluator is the check.

### Sensors

- Four deterministic Sensors, run at Sense: eval findings from the latest report, trace anomalies over the Trace Store, unaddressed negative feedback from the feedback file, and open questions from the Wiki, which include the Librarian's frontier proposals. The `reflection` and `policy` findings written by the Kernel during runs are read back as findings too.
- The eval Sensor emits one finding per red non-frontier case and, for frontier files, one finding per capability naming its lowest red rung, so the list stays short and each Growth Iteration climbs one rung.
- Trace anomaly rules: an error span; the same tool call three or more times in a run; two or more validation retries; run duration above twice the median of the last twenty runs; run cost above 80 percent of budget.
- Findings are ranked by severity, then age. `ra improve` takes the top one unless a goal is given, in which case the Planner receives the goal and the findings together.

### Evals and traces

- ADR 0004, 0005, and 0009 stand. Every run writes spans to one JSONL file per run through an extra span processor registered with Logfire; the span record schema is a Kernel contract. Logfire cloud is enabled only when a token is present.
- Datasets, one per role plus the frontier: `triage.yaml` (requests to expected Mode and gap kind, including frontier-style requests), `planner.yaml` (synthetic Sensor states, including a frontier finding whose Plan must add a Specialist naming the frontier file as its dataset), `test-writer.yaml` (a Plan and a scratch copy of the Organism; the produced tests are collected by pytest and fail), `implementer.yaml` (failing tests in a scratch copy; they pass afterwards with ruff and ty clean, under a tool-call cap), `answers.yaml` (proves the Worker: questions about the system with judge rubrics, including the self-description question), `reviewer.yaml` (diff and Plan pairs; a tautological test and an eval edit are rejected, an honest diff is accepted), `librarian.yaml` (a run summary; the produced log entry and page satisfy a rubric), and `frontier/<capability>.yaml`. Seeds are small, two or three cases each; the test-writer and implementer datasets are expensive and run only in the full suite.
- Frontier files: a ladder of three to five cases from easy to hard, each with `metadata` keys `tier: frontier`, `capability`, `rung` (consecutive from 1), `gap_kind`, and `needs_human` when applicable. Seeds written with this revision: `text-analysis.yaml` (skill gap, five rungs over a Stoic text and a Mill passage), `repo-history.yaml` (tool gap, four rungs, the first deterministic through `Contains`), `web-research.yaml` (connection gap, three rungs, red until the human grants network access).
- Judge semantics: `LLMJudge` evaluators are assertions with a reason; scores are optional extras for trend lines and never the pass criterion. Datasets never name a model; the Kernel calls the pydantic-evals default-judge setter with the Judge Model before any run. A case passes when every assertion is true on one run. In the Gate, a Guard Case that passed in the latest report and fails now is re-run once before it counts as a regression. `ra evals --repeat K` stays available for humans who want variance.
- Guard subset per Iteration: the Target dataset, `triage.yaml`, `answers.yaml`, and the dataset of every affected agent (see the registry section). The full suite runs only through `ra evals`, and its report feeds `ra improve`.
- Baselines: a case with no entry in the latest report counts as failing, so a new dataset starts red and "Target improved" is well defined.
- The eval runner keeps a registry of task functions per dataset kind, custom evaluators for "no secrets in output" and "targets Organism paths only", persists each report with a pointer to the latest, computes Target and Guard deltas between two reports, and computes the frontier ratios for the inventory.

### Wiki

- ADR 0003 stands. The Wiki module offers index rebuild, log append, open-question listing, and a lint report of orphans and unindexed pages. Only the Librarian writes to it, through a file tool rooted at the Wiki. Capability pages carry the commit and dataset that prove the capability.
- Frontier proposals: when a frontier file turns green in the Learn phase, the Librarian writes `wiki/pages/open-questions/next-frontier-<capability>.md` holding two or three candidate cases as a YAML block in the frontier format and one sentence per case on why it is harder than the last rung. The human copies accepted cases into the frontier file. The Librarian closes the question when the file has red rungs again.

### Git and runtime state

- ADR 0002 stands. The Kernel's git wrapper uses fixed argument lists, never a shell, never pushes, never signs, and authors commits as the Kernel. Read helpers back the Organism's git tools and refuse arguments beginning with a dash.
- Runtime data lives under the gitignored runtime directory: traces, runs, task outputs and task cases, eval reports, the feedback file, the breaker file, and the lock. Nothing there is deleted automatically.

### CLI

- Commands: `ask TEXT [--yes] [--max-iterations N] [--budget USD]`, `improve [--goal TEXT] [--yes] [--max-iterations N] [--budget USD]`, `evals [--dataset NAME] [--repeat K]` where `NAME` may be `frontier/<capability>`, `status`, `wiki ingest PATH`, `wiki lint`. Exit code 0 for accepted, 1 for rejected or best-effort, 2 for aborted or usage error, 3 for internal error.

## Testing Decisions

A good test here exercises behaviour through an interface a real caller uses and asserts on observable results: a returned contract, a file written, a commit made or a tree reset, an exit code. It never reads private state, never mocks a collaborator inside the module, and never depends on how the module computes its answer. Expected values are literals, not recomputed. Models are `TestModel` or `FunctionModel` with real model requests disabled for the whole session; the filesystem is real under a temporary directory; git is the real binary in a temporary repository with signing disabled; time is an injected clock. Nothing touches the network or the real environment file.

Deterministic tests under pytest cover the Kernel and the Organism's structure. Model behaviour, including whether the Constitution actually produces growth-seeking behaviour and whether the Test Writer actually goes red, is covered by eval datasets run through `ra evals`, never under pytest (ADR 0005).

Seams. Existing seams from the Phase 1 seams document are kept, with the amendments to the paths and records modules made in that document. New seams, listed from highest to lowest, with the rule that a behaviour testable at a higher seam is tested there:

1. The Loop runner: `run(mode, task, options)` returning a Run Record, with agents overridden by function models and a runners bundle (checks, evals, approval) plus the git wrapper and clock injected. This is the primary seam for the Loop, escalation, gap recording, stop rules, commit and reset, and Librarian calls. Cases: Answer accepted first try; Answer best-effort after the limit; Task Loop iterates then passes and its cases land under the runtime directory with tracked datasets unchanged; Task Loop escalates to Growth on a gap; Growth with a Python target runs Test Writer, red check, Implementer, and is accepted and committed; new tests that already pass reject the Iteration with `no red`; a Plan without Python targets skips the Test Writer; a Plan with Python targets and empty `tests` is rejected before Act; Growth rejected and reset; Plan with an unknown Actor rejected; Plan naming a Specialist invokes it; Worker gaps recorded as findings; `ra ask` re-triages once after an accepted Improvement and runs the Task Loop; Growth twice in one `ra ask` stops with exit 1; Guard subset contains triage, answers, the Target dataset, and the affected agents' datasets only; dirty tree refused; lock held; budget stop; no-progress stop; breaker stop.
2. The Gate: a pure function, table-driven over its inputs, including check ordering, the write-scope check, the Guard retry-once rule, and the Answer and Task Loop subsets.
3. Sensors: `collect()` over synthetic trace files, feedback, eval reports, and Wiki pages, including each anomaly rule and the one-finding-per-frontier-capability rule.
4. Evals: dataset loading, the task-function registry covering every dataset, report comparison with the missing-entry baseline, frontier ratio computation, and the append-only detection.
5. State Bundle and Capability Inventory: deterministic rendering from a registry, Wiki pages, an eval summary, and frontier ratios, including the proven and unproven annotation, the available-only-when-full rule, and the size cap.
6. The registry contract: a Kernel test that loads the Organism registry and checks the seven required roles, output types, phases, that every `guides`, `prompt_path`, and `dataset` exists, and tool configurations against the ceiling and the write scope. This is the test that protects the Kernel from a bad Improvement.
7. Organism tools: shell allowlist rejects `git` and editing utilities; the Test Writer's file tool refuses writes under the Organism package and the Implementer's refuses writes under the tests; no tool writes under `.venv/` or `.ra/`; file tools deny the environment file; git tools work on a temporary repository.
8. Wiki operations, including the frontier proposal page.
9. The CLI, through the Typer test runner with the Loop runner faked, for flags, exit codes, and printed outcomes.
10. Documentation pointers: every backticked repo-relative path (a token containing `/` and no `<` placeholder) in `docs/coding-guide.md` and the Constitution exists, so a renamed file cannot leave a dangling pointer. Introduced with Phase 2, when the Organism modules the guide names exist.
11. Frontier datasets: every file under `evals/frontier/` loads with the pydantic-evals loader, every case carries the required metadata keys, and rungs are consecutive from 1.

Evals that cover the new requirements: triage cases where the request needs a Specialist, a tool, a connection, or a clarification, and a frontier-style request ("analyse this text") that must map to Growth with a skill gap; an answers case asking what the system can do and what it would need to grow, judged against a rubric that requires naming the Organism surfaces, the Kernel limit, and at least one frontier ratio; a planner case whose evidence is a frontier finding, asserting the Plan adds a registry entry naming the frontier file as the dataset and lists tests; a reviewer case with a tautological test asserting `reject`; an answers case asking which loop the system runs in and where the answering agent sits, judged against a rubric that requires the five phases and the agent's own phase; a planner case adding a tool, asserting the Plan's Target Cases exercise that tool so the addition arrives with its gate.

Prior art: the Phase 1 seams document defines the format (interface, dependencies by category, ordered tracer bullets) and the shared test fixtures (environment hygiene, the temporary git repository). No tests exist in the tree yet.

## Out of Scope

- Any automatic edit to the Kernel, dependencies, Protected Paths, the Coding Guide, or the reference copies; any push; any signed commit by the Kernel.
- An LLM orchestrator agent, agents calling agents, sub-agent trees, parallel agents, or event-driven choreography. The Kernel orchestrates; Specialists are invoked by it only.
- Specialists acting in Decide, Gate, or Learn.
- An Examiner agent, system-authored Frontier Cases, and agents writing eval files directly.
- A Kernel rule that counts tools or toolsets per agent; small agents are guidance.
- Harness capabilities beyond the file system and shell tools; a custom Pydantic AI model class; Codex or other provider integrations beyond a model string.
- Chat sessions; `ra ask` is one-shot apart from the single re-triage after an accepted Improvement. A web UI. Cloud sandboxes.
- Failure-signature clustering, held-out dataset generation beyond Guard Cases, automatic widening of the Policy Ceiling, and automatic refresh of the reference copies.
- Switching the Claude Code LSP plugin from pyright to a ty-based one, and any other edit to the Claude Code settings.
- Deleting or rotating runtime data.

## Further Notes

- The user's phrase "orchestrator agent" maps onto two glossary terms. The Kernel orchestrates the Loop (there is no orchestrator agent, by decision). Triage is the agent that decides the Mode. The awareness the user asked for is carried by the Constitution, which every agent receives, and kept current by the Capability Inventory in every State Bundle. The glossary asks us to say Reflection rather than consciousness.
- "Small agents, more agents": decided as guidance, not a rule (round 2, Q1 c). The one structural expression of it is the Coder split (ADR 0008), chosen because it makes red before green deterministic, not because of a tool count. The shell tool stays (round 2, Q13 a) with the allowlist, so the Policy Ceiling keeps its command rules.
- The reference copies exist because the system runs outside Claude Code (round 2, Q4). They are refreshed by the human together with the dependency upgrade, which is already a human-only change, so the copy cannot drift from the installed library unnoticed.
- The three architectural additions of the first revision (Specialist, Actor, Policy Ceiling) are now recorded: ADR 0007 for Specialists and the Actor, a consequence in ADR 0001 for the ceiling and the write scope. ADR 0008 records the Coder split, ADR 0009 the Frontier Cases. ADRs 0004 to 0006 moved from proposed to accepted.
- ty is pre-1.0 and its diagnostics may differ from pyright's. The Kernel must be brought to green under ty before the check is enabled in the Gate, so the bar is real from the first Growth Loop.
- The issue tracker for this repo has not been configured yet (`/setup-matt-pocock-skills` has not been run). This spec is filed in the local-markdown convention. If GitHub Issues is chosen, this file's body becomes the issue and the `ready-for-agent` label applies.
- Literature this shape follows: Anthropic's "Building effective agents" and long-running harness post, Self-Harness (2026), Weng's harness-engineering essay (2026), Kitchen Loop, SICA, and DGM, all summarised in the plan's references.

## Amendment 2026-09-06: Providers (accepted 2026-09-06)

Supersedes, in "Out of Scope", the words "Codex or other provider integrations beyond a model string" and "a custom Pydantic AI model class" to the extent below. Decisions: ADR 0011 (proposed) and `thoughts/shared/plans/2026-09-06-provider-seams.md`; facts: `thoughts/shared/research/2026-09-06-openai-provider-and-chatgpt-subscription-library-facts.md`. Vocabulary: Operator, Provider, Sign-in, added to `CONTEXT.md`.

Stories

80. As the Operator, I want a tier to run on my ChatGPT subscription, so that live Loops cost no API credit.
81. As the Operator, I want to run a tier on the OpenAI API with my own key, so that a model OpenRouter does not carry is one variable away.
82. As the Operator, I want `ra status` to name the Provider of each tier and whether its key or Sign-in is present, so that a run that cannot start is explained before it starts.
83. As a Kernel maintainer, I want no token to appear in a trace, a Run Record, a message, a `repr`, or a tool's reach, so that the Organism cannot read or leak the Operator's Sign-in.

Implementation decisions

- The model name keeps pydantic-ai's syntax. Settings gain `OPENAI_API_KEY`, `CODEX_HOME` (default `~/.codex`), and `RA_CHATGPT_ORIGINATOR`. One new scheme, `chatgpt:<model>`, runs a tier on the ChatGPT subscription; every other scheme is pydantic-ai's own, so `openai:<model>` needs only the key. No new dependency: the OpenAI client ships with the OpenRouter extra.
- One Kernel module builds the model for both tiers behind the agent runtime's `model_factory` seam and checks each tier's credentials by scheme before a command runs; `ra status` reports instead of refusing.
- The Kernel never signs in and never writes the Sign-in. `codex login` is the Operator's step; the Kernel reads the Sign-in file before every request, refuses to start a run whose token expires before the run's wall-time budget ends, and never prints, logs, traces, or represents a token. Refreshing stays with Codex, whose refresh tokens rotate.
- No custom Pydantic AI model class: the subscription adapter sits at the HTTP transport under pydantic-ai's OpenAI Responses model, injecting the headers the backend needs and turning the library's non-streaming request into the streaming one the backend requires.
- Cost is reported at the OpenAI list price for subscription runs on model ids the price data knows, and 0 for the others; the token fallback binds there.
- The Kernel does not retry a subscription 429: it means the plan's window is used up, and the breaker sees it at once.
- The Policy Ceiling denies the Sign-in directory to every tool, next to `.env` and `.git`.
- The Kernel identifies itself as itself in the request headers; identifying as the Codex CLI is an explicit Operator setting, never a default.

Still out of scope: the Kernel performing an OAuth login or a token refresh; a Codex process as an Actor; reading the subscription's remaining quota into `ra status`; recording the Provider on the Run Record (open point). A Codex-driven refresh through `codex app-server` is the follow-up if runs die on token expiry.
