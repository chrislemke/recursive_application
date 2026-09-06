# Recursive Application

A CLI agentic system, built on Pydantic AI, whose main job is to work on itself: it takes a user request, decides how to handle it, and runs closed self-improving loops guarded by evals, traces, and deterministic tests.

## Language

### The system

**Kernel**:
The human-owned part of the codebase: loop runner, Gate, circuit breaker, Sensors, provider setup, CLI entry, and the Constitution. The system may read it but never edits it.
_Avoid_: core, framework, runtime, harness

**Organism**:
The self-editable part of the codebase: agents, prompts, tools, eval datasets, their tests, and the Wiki. Growth happens only here.
_Avoid_: app code, userland, workspace

**Protected Path**:
A path the Organism may never modify: the Kernel plus the configuration, docs, and glossary files listed in the Kernel's single path rule.
_Avoid_: read-only files, locked files

**Constitution**:
The stable first prompt, part of the Kernel, that tells every agent what the system is, what it may do, and that it must improve itself through closed loops.
_Avoid_: system prompt, master prompt, instructions

**Policy Ceiling**:
The Kernel-owned limits that no tool configuration may exceed.
_Avoid_: sandbox, permissions, allowlist

**Coding Guide**:
The Kernel document that tells coding agents how code is written here.
_Avoid_: style guide, handbook, CLAUDE.md

**Operator**:
The human who runs `ra`, approves Definitions of Done, holds the credentials, and owns the Kernel.
_Avoid_: user, admin, human-in-the-loop

### Requests

**Task**:
A single user request entered through the CLI. Triage assigns every Task exactly one Mode.
_Avoid_: query, prompt, job, ticket

**Mode**:
The way a Task is handled: Answer, Task Loop, or Growth Loop.
_Avoid_: strategy, route, path

**Answer**:
The Mode for a Task the system can satisfy in one Iteration without changing its code.
_Avoid_: question, chat, direct reply

**Task Loop**:
The Mode that iterates on a Task's output against Target Cases until they pass, without changing code.
_Avoid_: work loop, job loop

**Growth Loop**:
The Mode that changes the Organism through Improvements because of a Capability Gap.
_Avoid_: self-improvement loop, upgrade, evolution

**Capability Inventory**:
The deterministic list, built by the Kernel, of what the system can do right now: its agents, their tools, the Wiki's capability pages, and the eval datasets that are green.
_Avoid_: feature list, skills list, self-model

**Reflection**:
The self-assessment Triage performs on every Task: which capabilities the Task requires, which the Capability Inventory covers, and which are Capability Gaps.
_Avoid_: consciousness, self-awareness, introspection

**Capability Gap**:
Something the Organism cannot yet do that a Task requires, typed as tool, knowledge, connection, skill, or clarification, with the Organism change that would close it. Recognising one is the trigger for a Growth Loop.
_Avoid_: missing feature, limitation, blocker

### The loop

**Loop**:
One closed-loop run with five phases in order: Sense, Decide, Act, Gate, Learn, which are the five layers of a self-improving loop (sensors, policy, tools, quality gate, learning mechanism). Every Mode uses the same Loop, orchestrated by the Kernel; agents never call each other.
_Avoid_: pipeline, workflow, cycle

**Watcher**:
The Kernel's monitoring of every agent: the Sensors that turn failures into Sensor Findings, the Gate that judges each Iteration, and `ra improve` that fixes the causes. It is never an agent and never part of the Organism.
_Avoid_: monitoring agent, supervisor, meta-agent, observer

**Iteration**:
One pass through the five phases producing exactly one candidate: an answer, a task output, or an Improvement.
_Avoid_: round, step, attempt

**Improvement**:
One accepted change to the Organism, recorded as a git commit.
_Avoid_: patch, PR, change set

**Plan**:
The Planner's output for one Iteration: the evidence, the inferred cause, the one change to make, its Target Cases, and the predicted impact including at-risk regressions.
_Avoid_: proposal, ticket, spec

**Definition of Done**:
The Target Cases a Task or Improvement must pass, drafted by the Planner and approved by the human unless approval is skipped.
_Avoid_: acceptance criteria, requirements

**Target Cases**:
The eval cases an Iteration is meant to make pass.
_Avoid_: held-in set, new tests

**Guard Cases**:
Every other eval case. They must not regress for an Iteration to pass the Gate.
_Avoid_: held-out set, regression suite

**Frontier Case**:
A human-written eval case the system is expected to fail today. Its failure is a standing Sensor Finding and, file by file, the growth agenda.
_Avoid_: aspirational case, stretch goal, benchmark

**Sensor**:
A deterministic source of evidence that feeds Sense: eval results, trace anomalies, user feedback, and open questions recorded in the Wiki.
_Avoid_: signal, monitor, input

**Sensor Finding**:
One item of evidence produced by a Sensor, such as a failing eval case, a trace anomaly, or negative feedback, that the Planner may turn into a Plan.
_Avoid_: issue, bug, alert, ticket

**Gate**:
The deterministic quality check an Iteration must pass: tests green, Target Cases improved, Guard Cases not regressed, no Protected Path touched, no new trace anomalies, Reviewer verdict positive.
_Avoid_: review, validation, check, guardrail

**State Bundle**:
The deterministic context the Kernel assembles for a decider: repo tree, latest eval report, Sensor Findings, Wiki index, and recent Run Records.
_Avoid_: context, prompt context, snapshot

### Agents

**Triage**:
The agent that performs the Reflection and assigns a Mode to a Task. Cheap, runs on every `ra ask`.
_Avoid_: router, classifier

**Planner**:
The agent that turns Sensor Findings or a Task into one Plan.
_Avoid_: architect, orchestrator, manager

**Test Writer**:
The Act-phase agent that writes the failing tests a Plan names, in Organism test paths only.
_Avoid_: coder, tester, QA

**Implementer**:
The Act-phase agent that makes the Plan's tests pass, in the Organism package only.
_Avoid_: coder, developer, engineer

**Worker**:
The agent that produces a Task's output in Answer and Task Loop Modes. It never edits code.
_Avoid_: assistant, executor, solver

**Reviewer**:
The agent, on the Judge Model, that checks whether a diff does what its Plan says and looks for eval gaming.
_Avoid_: critic, auditor, QA

**Librarian**:
The agent that maintains the Wiki in the Learn phase. Its write access is limited to the Wiki.
_Avoid_: memory agent, archivist

**Specialist**:
An Organism agent, added by the system, that the Kernel may invoke in the Act phase when a Plan names it.
_Avoid_: sub-agent, helper agent, plugin

**Actor**:
The registry entry a Plan names to perform the Act phase.
_Avoid_: performer, executor, assignee

**Judge Model**:
The second model, separate from the primary one, used by the Reviewer and by LLM-judge evaluators.
_Avoid_: grader, evaluator model

### Providers

**Provider**:
The Kernel adapter that turns a model name into a client that calls that model with the Operator's credentials. Three exist: OpenRouter, OpenAI, and ChatGPT.
_Avoid_: vendor, gateway, backend, model host

**Sign-in**:
The Operator's ChatGPT login, made with the Codex CLI, whose tokens the Kernel reads and refreshes but never creates.
_Avoid_: OAuth, login, session, credentials file

### Memory and evidence

**Wiki**:
The system's persistent memory: LLM-maintained markdown with an index, an append-only log, and topic pages, kept in the repo.
_Avoid_: memory, knowledge base, notes, context store

**Trace Store**:
The local, append-only record of spans from every agent run, kept on disk so the system can read its own behaviour.
_Avoid_: logs, telemetry, Logfire

**Run Record**:
The append-only record of one Loop run, one file under the runtime directory, holding every Iteration's Plan, reports, Gate result, and outcome.
_Avoid_: history, session, audit log
