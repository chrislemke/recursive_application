# Recursive Application Implementation Plan

Status: DRAFT, pending confirmation of the shared understanding reached in the grilling session on 2026-09-05.

## Overview

Build `ra`, a CLI agentic system on Pydantic AI 2.x whose main job is to work on itself. Every request runs through one closed Loop (Sense, Decide, Act, Gate, Learn) orchestrated by a deterministic Kernel. The self-editable Organism (agents, prompts, tools, eval datasets, Wiki) grows through Improvements that must pass tests, evals, a diff boundary check, and an independent Reviewer before the Kernel commits them. Vocabulary is defined in `CONTEXT.md`; the three load-bearing decisions are in `docs/adr/`.

## Current State Analysis

- Empty repo: `pyproject.toml` with no dependencies, empty `README.md`, `.python-version` = 3.12, `.gitignore` containing only `.DS_Store`, no commits yet (staged files on `main`).
- `docs/` holds three source documents the system must follow: `self-improving-loops.md` (five-layer loop anatomy, "build the watcher"), `multi-agent-orchestration-patterns.md` (orchestration over choreography, immutable versioned state, data contracts, circuit breaker, compensation), `production-ai-playbook.md` (evals as spec, three eval layers, tracing, prompt versioning, incident playbook).
- Environment: uv 0.10, git. The user has created `.env` from `.env.example` with all four keys set. The global git config signs every commit through 1Password (`commit.gpgsign=true`, `gpg.format=ssh`), so any unattended `git commit`, in tests included, must disable signing explicitly or it blocks on a GUI prompt.
- Verified library facts (2026-09-05): pydantic-ai 2.40.0, pydantic-evals 2.40.0, logfire 5.0.0, pydantic-ai-harness 0.29.0, typer 0.27.2, pytest 9.1.1. OpenRouter slugs `anthropic/claude-sonnet-5` and `openai/gpt-5.4-mini` exist.

## Desired End State

Running `uv run ra ask "..."` triages the request into Answer, Task Loop, or Growth Loop and runs the Loop with approval of the Definition of Done. `uv run ra improve` picks a Sensor Finding and makes one Improvement per Iteration, committing accepted ones. `uv run ra evals` prints and persists an eval report. `uv run ra status` shows loop metrics, breaker state, and open findings. `uv run ra wiki ingest docs/` and `uv run ra wiki lint` maintain the Wiki. `uv run pytest` is green without network access. Every agent run is traced to `.ra/traces/` and, when `LOGFIRE_TOKEN` is set, to Logfire cloud.

### Key Discoveries:
- Pydantic AI 2.x: `Agent(capabilities=[...])` replaces `instrument=`/`history_processors=`; `UsageLimits(cost_limit=..., request_limit=50)` exists; `Agent.override(model=TestModel())` for tests; `InstrumentationSettings(include_content=...)`; custom `Model.request(messages, model_settings, model_request_parameters)` is not needed since we use OpenRouter natively.
- pydantic-evals: `Dataset.from_file(yaml, custom_evaluator_types=...)`, `Dataset.evaluate_sync(task, repeat=...)`, evaluators `EqualsExpected`, `Contains`, `LLMJudge(rubric, model, score, assertion)`, `HasMatchingSpan(query)`, `MaxToolCalls`, `MaxModelRequests`; span evaluators need `logfire.configure(send_to_logfire='if-token-present')`, not the cloud.
- logfire 5.0: `logfire.configure(send_to_logfire='if-token-present', console=False, additional_span_processors=[...])`, `logfire.instrument_pydantic_ai()`.
- pydantic-ai-harness 0.29: `FileSystem(root_dir, allowed_patterns, denied_patterns, protected_patterns, read_only)`, `Shell(cwd, allowed_commands, denied_commands, default_timeout, max_output_chars, denied_env_patterns)`. Shell validates only the first token of a command.
- Literature check (Anthropic "Building effective agents", Anthropic long-running harness post, Self-Harness 2026, Weng 2026, Kitchen Loop 2026, SICA, DGM): the recommended shape is a fixed supervisor with a propose-evaluate-accept loop over bounded edit surfaces, non-regressive acceptance on target and guard sets, traces as evidence, an independent critic against reward hacking, and one change per iteration with a commit each. This plan is that shape.

## What We're NOT Doing

- No Codex integration and no custom `Model` class. The model is a Pydantic AI model string; switching providers is an env var.
- No LLM orchestrator agent, no `pydantic_graph`, no sub-agent trees, no parallel agents, no choreography.
- No harness `Coder`, `Planning`, `SubAgents`, or `Memory` capabilities; only `FileSystem` and `Shell`.
- No chat sessions; `ra ask` is one-shot.
- No automatic Kernel edits, dependency changes, or pushes. Ever.
- No cloud sandboxes, no web UI, no failure-signature clustering, no held-out dataset generation beyond Guard Cases.

## Implementation Approach

Kernel first, deterministic and fully unit-tested with fakes. Then the Organism v0 with the six agents and the Constitution. Then evals, then the Loop and CLI, then the first live runs. Synchronous code throughout (`run_sync`, `evaluate_sync`); async only where a library demands it. One improvement per Iteration, one commit per Improvement.

Process (added 2026-09-05 after the first implementation attempt was cancelled for not being test-first): every module is built red → green at the seams written down beforehand in `thoughts/shared/plans/2026-09-05-phase1-seams.md` (one behaviour per cycle, tests only through the listed interfaces); library facts are verified against the installed sources and recorded under `thoughts/shared/research/`; the decisions behind the Trace Store, the eval/test split, and synchronous execution are recorded as ADRs 0004 to 0006.

Repository layout:

```
src/recursive_application/
  kernel/            human-only
    cli.py           typer app: ask, improve, evals, status, wiki ingest|lint
    settings.py      pydantic-settings from .env: keys, models, budgets, breaker thresholds
    paths.py         repo root, .ra/ dirs, PROTECTED rule, is_protected(path)
    records.py       data contracts: TriageDecision, Plan, CoderReport, Review, SensorFinding, IterationRecord, RunRecord, GateResult
    constitution.md  the stable first prompt
    tracing.py       logfire config, JSONL span exporter, trace reading
    breaker.py       circuit breaker per agent role, persisted to .ra/breaker.json
    git.py           is_clean, head_sha, diff_paths, changed_eval_cases, commit, reset_hard_clean
    sensors.py       eval findings, trace anomaly rules, feedback findings, wiki open questions
    evals.py         dataset loading, task-function registry per dataset kind, evaluators, report persistence
    gate.py          GateResult from tests, eval deltas, diff paths, anomalies, Review
    loop.py          LoopRunner: five phases, approvals, budgets, lock, run records
    agents_runtime.py  run_agent(role, agent, prompt, deps): breaker + UsageLimits + model injection + tracing
  organism/          self-editable
    agents.py        six Agent objects without a model; output types from kernel.records
    tools.py         FileSystem/Shell configs, git read tools, wiki tools
    prompts/         triage.md planner.md coder.md worker.md reviewer.md librarian.md
    wiki.py          index/log/pages helpers, deterministic index rebuild, lint scan
evals/               datasets, append-only for existing cases
  triage.yaml answers.yaml planner.yaml coder.yaml tasks/
tests/
  kernel/            human-only
  organism/
wiki/
  index.md log.md pages/{capabilities,lessons,open-questions,tasks}/
.ra/                 gitignored runtime data: traces/ runs/ tasks/ evals/ feedback.jsonl breaker.json lock
```

Protected rule (single source in `kernel/paths.py`): `src/recursive_application/kernel/**`, `tests/kernel/**`, `pyproject.toml`, `uv.lock`, `.env`, `.env.example`, `.gitignore`, `.claude/**`, `docs/**`, `CONTEXT.md`. `.env` and `.git/**` are also denied for reading by file tools.

Agent roster and contracts (all in `kernel/records.py`):

| Agent | Model | Tools | Output |
|---|---|---|---|
| Triage | RA_MODEL | none | `TriageDecision(mode, reasoning, reflection: Reflection(required_capabilities, available, gaps: [CapabilityGap(kind, description, how_to_acquire, needs_human)]), clarifying_questions)` |
| Planner | RA_MODEL | FileSystem read-only, git read | `Plan(title, evidence, cause, change, target_paths, target_cases, predicted_impact, at_risk)` |
| Coder | RA_MODEL | FileSystem, Shell, git read | `CoderReport(summary, changed_files, tests_run, tests_passed)` |
| Worker | RA_MODEL | FileSystem read-only, git read | markdown `str` |
| Reviewer | RA_JUDGE_MODEL | FileSystem read-only, git read | `Review(matches_plan, gaming_suspected, notes, verdict)` |
| Librarian | RA_MODEL | FileSystem rooted at `wiki/` | `str` summary of edits |

Every agent gets: Constitution + its prompt file + the State Bundle (Capability Inventory, repo tree, latest eval summary, Sensor Findings, Wiki index, last Run Records) as instructions, injected by the Kernel.

Self-reflection (added 2026-09-05 on the user's request): the Kernel builds a deterministic Capability Inventory (`kernel/inventory.py`: agents and their tool names and descriptions from the Organism registry, Wiki `capabilities/` pages, eval datasets currently green). Triage performs a Reflection on every Task: required capabilities, which the inventory covers, and typed Capability Gaps (tool, knowledge, connection, skill, clarification) each with the Organism change that would close it and any policy items only a human may grant (network access, new dependency). Any gap makes the Mode Growth; a `clarification` gap makes Triage return clarifying questions that `ra ask` prints before exiting. The Constitution states that recognising a gap is the trigger for growth and that the system can acquire tools, knowledge, and connections by changing the Organism within policy. The Librarian records every accepted capability in `wiki/pages/capabilities/` so the inventory includes learned abilities with a breadcrumb to the commit and the evals that prove them.

Loop semantics per Mode:

- Answer: no Planner call. Kernel builds one Target Case (the request with the generic answer rubric). Worker produces the answer, Gate runs the judge, on failure iterate with the judge's reason, after max iterations return the best answer with a warning and record a Sensor Finding.
- Task Loop: Planner writes Target Cases to `evals/tasks/<slug>.yaml` (Kernel writes the file from the Plan), approval unless `--yes`, Worker produces output to `.ra/tasks/<id>/output.md`, Gate evaluates, iterate until pass or budget. A Capability Gap in the Plan escalates to Growth with a new approval.
- Growth Loop: requires clean tree and lock. Planner writes Plan and Target Cases, approval unless `--yes`, Coder implements, Gate: `uv run pytest` in subprocess, `uv run ra evals` in subprocess for Target and Guard Cases, diff paths not protected, existing eval cases unchanged, no new trace anomalies, Reviewer verdict. Accepted: Librarian updates Wiki, Kernel commits `ra: <title>`. Rejected: Librarian records the lesson, Kernel resets. `ra ask` stops after one Improvement; `ra improve` continues to the next finding until `--max-iterations` or `--budget`.

Stop rules: max iterations (5), wall time (30 min), USD budget via `UsageLimits(cost_limit)` summed over the run with token fallback, no progress for 2 Iterations, breaker open. Breaker: 3 consecutive failures open it, half-open after 60 s, one breaker per agent role.

Trace anomaly rules (deterministic): error span; identical tool call 3+ times in a run; 2+ validation retries; run duration above 2x the median of the last 20 runs; run cost above 80% of budget.

## Phase 1: Project Skeleton and Kernel Primitives

### Overview
Installable package, settings, tracing, breaker, git wrapper, protected-path rule, and data contracts, all unit-tested without network.

### Changes Required:

#### 1. Packaging
**File**: `pyproject.toml`
**Changes**: src layout, `[project.scripts] ra = "recursive_application.kernel.cli:app"`, dependencies `pydantic-ai-slim[openrouter]`, `pydantic-evals`, `logfire`, `pydantic-ai-harness`, `typer`, `pydantic-settings`; dev group `pytest`, `ruff`, `pyright`; ruff and pyright config; pytest `pythonpath`/markers.

**File**: `.gitignore`
**Changes**: Python, `.venv/`, `.ra/`, `.env`, `.logfire/`, caches, `.DS_Store`.

**File**: `.env.example`
**Changes**: the four keys with placeholder values.

#### 2. Settings and paths
**File**: `src/recursive_application/kernel/settings.py`
**Changes**: `Settings(BaseSettings)` with `openrouter_api_key`, `ra_model`, `ra_judge_model`, `logfire_token: str | None`, budgets, breaker thresholds, `env_file='.env'`.

**File**: `src/recursive_application/kernel/paths.py`
**Changes**: `REPO_ROOT`, `RA_DIR`, `PROTECTED` patterns, `is_protected(path) -> bool`, `ensure_ra_dirs()`.

#### 3. Contracts
**File**: `src/recursive_application/kernel/records.py`
**Changes**: frozen Pydantic models listed above; `RunStore(runs_dir)` persists Run Records as `.ra/runs/<run_id>.json` and appends Iterations (append-only in spirit: iterations are only added). Interfaces: see the Phase 1 seams document.

#### 4. Tracing
**File**: `src/recursive_application/kernel/tracing.py`
**Changes**: `configure_tracing(run_id, verbose)` calling `logfire.configure(send_to_logfire='if-token-present', console=... , additional_span_processors=[SimpleSpanProcessor(JsonlSpanExporter(path))])` and `logfire.instrument_pydantic_ai()`; `read_spans(run_id)`.

#### 5. Breaker and git
**File**: `src/recursive_application/kernel/breaker.py`
**Changes**: `BreakerStore` persisting `.ra/breaker.json`: one breaker per agent role with CLOSED/OPEN/HALF_OPEN semantics and an injectable clock; the per-role breaker object is internal to the module.

**File**: `src/recursive_application/kernel/git.py`
**Changes**: `Repo(root)`, a thin subprocess wrapper with fixed argument lists: `is_clean`, `head_sha`, `changed_paths`, `diff_text`, `commit_all(message)` (authored as the Kernel, unsigned), `reset_hard_clean`, and the `log/show/blame/status/diff` read helpers used by Organism tools.

#### 6. Tests
**Files**: `tests/kernel/test_paths.py`, `test_settings.py`, `test_records.py`, `test_tracing.py`, `test_breaker.py`, `test_git.py` (uses a temporary real git repo), `test_cli.py`; `tests/conftest.py` sets `ALLOW_MODEL_REQUESTS=False` via `pydantic_ai.models`, strips provider keys and `RA_*` variables from the environment for every test, and provides the `git_repo` fixture with commit signing disabled.

### Success Criteria:

#### Automated Verification:
- [ ] `uv sync` succeeds and `uv run ra --help` prints the command list (stub commands allowed)
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check . && uv run ruff format --check .` pass
- [ ] `uv run pyright` passes

#### Manual Verification:
- [ ] `.env` created by the user from `.env.example`; `uv run python -c "from recursive_application.kernel.settings import Settings; Settings()"` loads it
- [ ] A dummy span written through `configure_tracing` appears in `.ra/traces/<run_id>.jsonl`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 2: Organism v0

### Overview
The Constitution, the six agents with prompts, the tool configurations, and the Wiki module. No Loop yet; agents are exercised with `TestModel`.

### Changes Required:

#### 1. Constitution
**File**: `src/recursive_application/kernel/constitution.md`
**Changes**: under 80 lines, plain English: identity and purpose; the five-phase Loop as the default way to work; Kernel/Organism rule and Protected Paths; git awareness (history is readable, commits are made by the Kernel); Wiki usage; policy boundaries (unattended vs human-required actions); budgets; pointers to `docs/*.md` and `CONTEXT.md` by path.

#### 2. Agents and prompts
**File**: `src/recursive_application/organism/agents.py`
**Changes**: six `Agent` objects, no model set, `name=`, `output_type` from `kernel.records`, `retries=2`, instructions assembled by a Kernel helper: Constitution + `prompts/<agent>.md` + State Bundle via `@agent.instructions` reading `ctx.deps`.

**Files**: `src/recursive_application/organism/prompts/{triage,planner,coder,worker,reviewer,librarian}.md`

#### 3. Tools
**File**: `src/recursive_application/organism/tools.py`
**Changes**: `filesystem(read_only: bool)` returning harness `FileSystem(REPO_ROOT, denied_patterns=['.env', '.git/**'], protected_patterns=PROTECTED, read_only=...)`; `shell()` returning harness `Shell(cwd=REPO_ROOT, allowed_commands=['uv','pytest','python','ruff','rg','ls','cat','head','tail','wc','diff'], default_timeout=600)`; `git_tools` as a `FunctionToolset` with `git_log`, `git_diff`, `git_show`, `git_blame`, `git_status` calling `kernel.git` read helpers; `wiki_filesystem()` rooted at `wiki/`.

#### 3b. Capability Inventory
**File**: `src/recursive_application/kernel/inventory.py`
**Changes**: `build_inventory(agents, wiki, latest_eval_summary) -> Inventory` rendered as a short markdown block for the State Bundle; deterministic, no model call.

#### 4. Wiki
**File**: `src/recursive_application/organism/wiki.py`
**Changes**: `Wiki(root)`: `rebuild_index()` from page titles and first paragraphs, `append_log(entry)`, `list_open_questions()`, `lint_report()` returning orphans and pages missing from the index (the Librarian handles contradictions and stale claims). Seed files: `wiki/index.md`, `wiki/log.md`, empty category folders with a `.gitkeep`.

#### 5. Agent runtime
**File**: `src/recursive_application/kernel/agents_runtime.py`
**Changes**: `run_agent(role, agent, prompt, deps, *, model, usage_limits)` wrapping `agent.run_sync` in the role's breaker with `UsageLimits(request_limit=50 or 100 for coder, cost_limit=...)`.

#### 6. Tests
**Files**: `tests/organism/test_agents.py` (each agent produces a valid contract with `TestModel`, prompts exist and are non-empty, Constitution under 80 lines), `test_tools.py` (git tools on a temp repo, shell allowlist rejects `git` and `sed`, filesystem denies `.env` and refuses writes to Protected Paths), `test_wiki.py`.

### Success Criteria:

#### Automated Verification:
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check . && uv run pyright` pass

#### Manual Verification:
- [ ] Read `constitution.md` and the six prompts for tone and length
- [ ] `uv run python -m recursive_application.organism.smoke` (temporary script, deleted after) runs Triage once against OpenRouter and prints a `TriageDecision`

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 3: Evals

### Overview
Datasets, evaluator registry, eval runner, report persistence, and the eval Sensor.

### Changes Required:

#### 1. Datasets
**Files**: `evals/triage.yaml` (requests to expected mode, seeded with the three examples), plus cases asserting the Reflection names the right gap kind for requests that need a tool, a connection, or a clarification, `evals/answers.yaml` (questions about the system with `LLMJudge` rubric and `Contains`), `evals/planner.yaml` (synthetic Sensor states, assertions: one change, Organism paths only, non-empty target cases, plus judge), `evals/coder.yaml` (one seeded bug in a scratch copy of the Organism, `MaxToolCalls`, `HasMatchingSpan` on a pytest run, tests pass afterwards), `evals/tasks/` (empty, generated later).

#### 2. Runner
**File**: `src/recursive_application/kernel/evals.py`
**Changes**: `load_dataset(path)`, task-function registry by dataset kind (triage, answers, planner, coder, tasks), custom evaluators `NoSecrets`, `TargetsOrganismOnly`, `run(datasets, repeat) -> EvalSummary` persisted to `.ra/evals/<ts>.json` and `latest.json`, `compare(before, after)` giving Target and Guard deltas, `changed_or_deleted_cases(diff)` for the append-only rule.

#### 3. CLI
**File**: `src/recursive_application/kernel/cli.py`
**Changes**: `ra evals [--dataset NAME] [--repeat K]` printing `report.print()` and the persisted path.

#### 4. Tests
**Files**: `tests/kernel/test_evals.py`: datasets load, registry maps every dataset, `compare` logic, append-only detection on a temp repo; evaluators unit-tested; no model calls (task functions faked with `TestModel`).

### Success Criteria:

#### Automated Verification:
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check . && uv run pyright` pass

#### Manual Verification:
- [ ] `uv run ra evals --dataset triage` runs against OpenRouter and persists a report
- [ ] `uv run ra evals --dataset answers --repeat 3` shows variance across repeats

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 4: Loop, Gate, Sensors, and CLI

### Overview
The five-phase LoopRunner for all three Modes, the Gate, the Sensors, and the remaining CLI commands, tested end-to-end with fakes.

### Changes Required:

#### 1. Sensors
**File**: `src/recursive_application/kernel/sensors.py`
**Changes**: `collect() -> list[SensorFinding]` from latest eval summary, trace anomaly rules over `.ra/traces/`, unaddressed negatives in `.ra/feedback.jsonl`, and `wiki/pages/open-questions/`.

#### 2. Gate
**File**: `src/recursive_application/kernel/gate.py`
**Changes**: `evaluate(iteration_inputs) -> GateResult` with named reasons; pure function over inputs so it is table-testable.

#### 3. Loop
**File**: `src/recursive_application/kernel/loop.py`
**Changes**: `LoopRunner(settings, agents, runners)` where `runners` bundles `run_tests`, `run_evals`, `git`, `approve` so tests can inject fakes; `run(mode, task, opts) -> RunRecord`; lock file; clean-tree precondition; approval prompt showing Plan and Target Cases as YAML; budgets and stop rules; Librarian call in Learn; commit or reset.

#### 4. CLI
**File**: `src/recursive_application/kernel/cli.py`
**Changes**: `ra ask TEXT [--yes] [--max-iterations N] [--budget USD]` with the feedback prompt when stdin is a TTY; `ra improve [--goal TEXT] [--yes] [--max-iterations N] [--budget USD]`; `ra status`; `ra wiki ingest PATH`; `ra wiki lint`.

#### 5. Tests
**Files**: `tests/kernel/test_loop.py` (FunctionModel agents and fake runners: Answer accepted first try, Answer best-effort after max, Task Loop iterates then passes, Growth accepted and committed, Growth rejected and reset, dirty tree refused, lock held, budget stop, no-progress stop, breaker open stop), `test_gate.py` (table-driven), `test_sensors.py` (synthetic traces and feedback), `test_cli.py` (typer `CliRunner` with the loop faked).

### Success Criteria:

#### Automated Verification:
- [ ] `uv run pytest` passes
- [ ] `uv run ruff check . && uv run pyright` pass

#### Manual Verification:
- [ ] `uv run ra status` on a fresh `.ra/` prints an empty but well-formed status
- [ ] `uv run ra ask "What can you do right now, and what would you need to grow?"` produces an Answer, records a trace, and asks for feedback

**Implementation Note**: After completing this phase and all automated verification passes, pause here for manual confirmation from the human that the manual testing was successful before proceeding to the next phase.

---

## Phase 5: First Live Loops and README

### Overview
Exercise the system on itself, tune prompts from what the traces show, and document usage.

### Changes Required:

#### 1. Live runs (no code changes expected unless traces reveal defects)
- `uv run ra wiki ingest docs/`
- `uv run ra ask "Summarize docs/self-improving-loops.md into five bullet points for a new engineer."` (Task Loop)
- `uv run ra ask "Learn to answer questions about this repo's git history, e.g. who changed the gate last and why."` (Growth Loop, approve the Target Cases)
- `uv run ra evals`
- `uv run ra improve --max-iterations 2`
- `uv run ra wiki lint`

#### 2. README
**File**: `README.md`
**Changes**: what it is, setup (`uv sync`, `.env`), the five commands, the Kernel/Organism rule, where data lives, how to read traces and run records.

### Success Criteria:

#### Automated Verification:
- [ ] `uv run pytest` passes on the Organism after the system's own commits
- [ ] `uv run ra evals` shows no regression versus the report before the Growth Loop

#### Manual Verification:
- [ ] The Growth Loop produced exactly one commit authored by the Kernel and touched no Protected Path
- [ ] `ra status` shows the accepted Improvement, cost, and eval trend
- [ ] The Wiki index and log reflect the runs

---

## Testing Strategy

### Unit Tests:
- Kernel: paths rule, contracts, breaker transitions with a fake clock, git wrapper on a temp repo, JSONL exporter and trace reader, anomaly rules, eval comparison and append-only rule, Gate table, LoopRunner with fakes, CLI with `CliRunner`.
- Organism: agents produce valid contracts under `TestModel`, tool allowlists and denials, Wiki operations.
- `tests/conftest.py` disables real model requests globally.

### Integration Tests:
- Evals are the integration tests and run only through `ra evals` or inside a Loop, never in plain `pytest`.

### Manual Testing Steps:
1. Phase 2 smoke call to OpenRouter.
2. Phase 3 `ra evals` on the small datasets.
3. Phase 5 live loops listed above.

## Performance Considerations

- The coder eval (`evals/coder.yaml`) is expensive; it runs only in the full suite before acceptance, never per Iteration.
- Judge calls use `RA_JUDGE_MODEL`, a cheaper model, and `repeat=1` by default.
- Shell timeout for the coder is 600 s so `uv run pytest` can finish inside a tool call.

## Migration Notes

- The user's currently staged files need one commit before the first Growth Loop, because the Kernel refuses a dirty working tree.
- Existing eval cases are append-only from the first commit onward; changing one is a human decision.

## References

- `docs/self-improving-loops.md`, `docs/multi-agent-orchestration-patterns.md`, `docs/production-ai-playbook.md`
- `CONTEXT.md`, `docs/adr/0001-kernel-organism-split.md`, `docs/adr/0002-git-as-state-store.md`, `docs/adr/0003-own-wiki-over-harness-memory.md`
- Anthropic, "Building effective agents"; Anthropic, "Effective harnesses for long-running agents"; Self-Harness (arXiv 2606.09498); Weng, "Harness Engineering for Self-Improvement" (2026); Kitchen Loop (arXiv 2603.25697); SICA (arXiv 2504.15228); DGM (arXiv 2505.22954)
