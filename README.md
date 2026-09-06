# Recursive Application

A CLI agentic system, built on Pydantic AI, that works on itself. You give it a Task through `ra ask`. Triage decides whether to answer it, to iterate on a Task output, or to grow, which means changing its own code to close a Capability Gap. Every change runs through one closed Loop (Sense, Decide, Act, Gate, Learn). It lands as a git commit only when the tests, the evals, and a Reviewer on the Judge Model agree.

`CONTEXT.md` defines the vocabulary this file uses. The decisions behind the design are in `docs/adr/`. This file is a map to the files that hold each rule. When the two disagree, the code is right.

## Setup

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
uv sync
cp .env.example .env
```

Edit `.env` and set `OPENROUTER_API_KEY` to your OpenRouter key. `RA_MODEL` is the primary model. `RA_JUDGE_MODEL` is the Judge Model the Reviewer and the LLM-judge evaluators use. `.env.example` sets both to their defaults. `LOGFIRE_TOKEN` is optional. With it, traces also go to Logfire cloud. The Kernel reads settings from the environment first and from `.env` second, and never prints the key. `.env` is gitignored and a Protected Path.

The Loop's limits are settings too, each optional. Their defaults live in `src/recursive_application/kernel/settings.py`, and that file is the place to read them:

| Variable | Meaning |
| --- | --- |
| `RA_MAX_ITERATIONS` | Iterations per run |
| `RA_MAX_MINUTES` | minutes of wall time per run |
| `RA_BUDGET_USD` | USD per run |
| `RA_NO_PROGRESS_ITERATIONS` | Iterations without progress before the run stops |
| `RA_REQUEST_LIMIT` | model requests one agent run may make |
| `RA_CODER_REQUEST_LIMIT` | the same limit for the Test Writer and the Implementer |
| `RA_BREAKER_FAILURES` | consecutive failures that open an agent's circuit breaker |
| `RA_BREAKER_RESET_S` | seconds before an open breaker lets one call through again |

Check the install with `uv run ra --help`. The Gate runs the four checks named in `docs/coding-guide.md` on every diff that changes code, before any eval runs.

## Commands

`ra` has six commands. `ra <command> --help` prints the flags. The source is `src/recursive_application/kernel/cli.py`.

| Command | What it does |
| --- | --- |
| `ra ask TEXT [--yes] [--max-iterations N] [--budget USD]` | Answer a request or carry out a task. Triage picks the Mode. |
| `ra improve [--goal TEXT] [--yes] [--max-iterations N] [--budget USD]` | Run the Growth Loop. |
| `ra evals [--dataset NAME] [--repeat K] [--all]` | Run the eval datasets and save a report. |
| `ra status` | Show the runtime state. |
| `ra wiki ingest PATH` | Have the Librarian read a document, or every markdown file under a directory, into the Wiki. |
| `ra wiki lint` | List Wiki pages nothing links to and pages missing from the index. |

`--yes` (or `-y`) approves every Plan without asking. `--max-iterations` and `--budget` override `RA_MAX_ITERATIONS` and `RA_BUDGET_USD` for one run. `--goal` steers the Growth Loop. `--dataset` names one dataset, for instance `triage` or `frontier/<capability>`. `--repeat` runs each case K times. `--all` adds the `test-writer` and `implementer` datasets. They write code in a scratch checkout and cost the most, so `ra evals` skips them otherwise. `ra evals` exits 0 whenever it ran; the summary reports red cases, and they are not an error.

`ra ask` runs like this. Triage reflects on the Task against the Capability Inventory and picks a Mode. In Answer Mode the Worker answers and an LLM judge is the Gate. In a Task Loop the Planner writes Target Cases, you approve them unless `--yes`, and the Worker (or a Specialist the Plan names) iterates until they pass. A clarification gap prints Triage's questions and exits 2; nothing else runs. When Triage finds a Capability Gap, or a Task Loop hits one, a Growth Loop runs instead. A gap that needs your decision, such as network access, is recorded as a Sensor Finding for you instead. After its first accepted Improvement the Kernel runs Triage once more on the original Task and runs the Answer or Task Loop it now picks, within the same run's limits. When Triage picks Growth a second time, the run prints what was added and what is still missing and exits 1. At a terminal, and not under `--yes`, `ra ask` ends by asking whether the answer was useful. Type `n` and a comment, and the Kernel keeps both in the feedback file, where the feedback Sensor turns them into a Sensor Finding.

`ra improve` runs like this. It needs a clean working tree and takes the lock. Without `--goal` it takes the most severe open Sensor Finding and hands it to the Planner. With `--goal` the Planner receives the goal and the open Sensor Findings together. Each Iteration makes one Plan, which you approve unless `--yes`, and at most one Improvement. When the Plan changes Python, the Test Writer goes red first; then the Implementer goes green, the Gate judges, and the Kernel commits with a message beginning `ra:`. After an accepted Improvement it senses again and continues with the next Sensor Finding until a stop rule. The Kernel resets a rejected Iteration with git, and the Librarian records it as a lesson in the Wiki.

Stop rules apply to every run: the iteration limit, the wall time, the budget, `RA_NO_PROGRESS_ITERATIONS` Iterations without progress, an open breaker, and, for `ra improve`, no open Sensor Finding left. An Answer stopped by the iteration limit or by no progress comes back as best effort with exit 1. `ra improve` exits 0 when it made at least one Improvement and a limit ended it. A refused approval or an open breaker aborts any run with exit 2, and so does a limit reached before an Improvement.

| Code | Meaning |
| --- | --- |
| `0` | accepted |
| `1` | rejected or best effort; also `ra wiki lint` finding a page to fix |
| `2` | aborted or usage error: a clarification, a stop rule, a dirty tree, a held lock, a refused approval, a missing setting, a bad dataset name or path |
| `3` | internal error |

## Kernel and Organism

The code is split in two. Humans own the Kernel: the Loop runner, the Gate, the Sensors, the CLI, the Constitution, and the configuration and documentation files. The system reads it and never edits it. The system may change the Organism: its agents, prompts, tools, eval datasets, their tests, the Wiki, and this file. The rule lives in one place, `src/recursive_application/kernel/paths.py`: `PROTECTED_DIRS` and `PROTECTED_FILES` are the Protected Paths, `WRITABLE_DIRS` and `WRITABLE_FILES` the write scope. The Gate checks the git diff of every Iteration against it before any commit. The Kernel also limits file tools to the write scope, so everything outside it, gitignored paths included, is read-only for every tool. When a Plan needs a Kernel change, the Kernel records a Sensor Finding for you; the system cannot make the change itself. See `docs/adr/0001-kernel-organism-split.md`.

Every agent starts from the Constitution, `src/recursive_application/kernel/constitution.md`. The Planner, the Reviewer, and the coding agents also get `docs/coding-guide.md`. The Organism's agents and prompts live in `src/recursive_application/organism/agents.py` and `src/recursive_application/organism/prompts/`, their tool configurations in `src/recursive_application/organism/tools.py`. The Kernel checks each configuration against the Policy Ceiling in `src/recursive_application/kernel/policy.py` and refuses to build an agent that exceeds it.

## Where runtime data lives

Everything a run writes goes under `.ra` at the repo root. It is gitignored, the first command creates it, and nothing deletes it. The names come from `src/recursive_application/kernel/paths.py`, `src/recursive_application/kernel/sensors.py`, `src/recursive_application/kernel/cli.py`, and `src/recursive_application/kernel/loop.py`.

| Under `.ra` | Holds |
| --- | --- |
| `traces` | the Trace Store: one JSONL file of spans per run |
| `runs` | one Run Record per run, as JSON |
| `tasks` | per run, the Target Cases (`cases.yaml`) and the latest output (`output.md`) of an Answer or Task run |
| `evals` | one JSON report per eval run, and `latest.json` naming the newest |
| `scratch` | copies of the checkout the expensive eval datasets code in |
| `feedback.jsonl` | your negative answers to the feedback question, with the comments |
| `findings.jsonl` | the Sensor Findings the Kernel wrote while runs were going on |
| `breaker.json` | the circuit breaker state of every agent |
| `lock` | held while a Growth Loop runs, removed when it ends |

The lock is a plain file holding the run id. A run killed with `kill -9` leaves it behind, and the next `ra improve` then exits 2 with "lock held" until you delete it.

`ra status` reads all of this and prints seven sections, from the breakers to the Librarian's frontier proposals; `src/recursive_application/kernel/status.py` lists them.

Tracked state is git. Each accepted Improvement is one commit made by the Kernel, authored as `ra Kernel <ra@localhost>`, with a message beginning `ra:`. The system never pushes. Git tracks the Wiki (`wiki/`) and the eval datasets (`evals/`) because they are the system's knowledge and its specification. See `docs/adr/0002-git-as-state-store.md`.

## Reading traces and Run Records

A run's spans are in `.ra/traces/<run_id>.jsonl`, one JSON object per line. The exporter appends each span as it ends, so you can read the file during the run. Each line holds the span's ids, name, timing, status, and `attributes`. Agent spans carry Pydantic AI's attributes, including the name and arguments of each tool call. The schema is in `src/recursive_application/kernel/tracing.py`. The anomaly rules in `src/recursive_application/kernel/sensors.py` read it.

The Run Record is `.ra/runs/<run_id>.json`. It holds the run's Mode, Task, timestamps, outcome, and the Sensor Findings it addressed, then one entry per Iteration. An Iteration entry holds its Plan, the coders' reports, the output path, the Gate result with every check it ran, the Review, the outcome and its reason, the commit, and its usage. The fields are `RunRecord` and `IterationRecord` in `src/recursive_application/kernel/records.py`. A run id starts with its timestamp, so the newest file sorts last.

## Frontier Cases

The growth agenda is a directory of eval files a human writes: `evals/frontier/`, one file per capability. Each file is a ladder of three to five cases from easy to hard that the system cannot pass yet. Each case's `metadata` carries `tier: frontier`, `capability` (the file's name), `rung` (consecutive from 1), and `gap_kind` (`tool`, `knowledge`, `connection`, `skill`, or `clarification`). It carries `needs_human` when a human must grant something first, such as network access. The Kernel refuses a file whose rungs skip a number; the rule is `validate_frontier` in `src/recursive_application/kernel/evals.py`.

A red rung is a Sensor Finding, one per capability naming its lowest red rung. `ra improve` picks it, the Planner makes that rung a Target Case, and the Iteration climbs one rung. A capability counts as available to Triage only when its whole ladder is green; `ra status` shows the ratio and the next rung under "Frontier". No agent writes under `evals/`.

To add a rung, append a case to `evals/frontier/<capability>.yaml` with the next `rung` number and the other metadata keys as in the file, then commit it. To add a capability, create a new file there with the same shape. When a ladder turns green, the Librarian proposes harder cases in `wiki/pages/open-questions/next-frontier-<capability>.md`. The page holds a YAML block in the frontier format and one sentence per case on why it is harder than the last rung. `ra status` lists these under "Frontier proposals". Copy what you accept into the frontier file. The system never edits a frontier file itself. See `docs/adr/0009-frontier-cases-are-the-growth-agenda.md`.
