# Recursive Application

A CLI agentic system, built on Pydantic AI, that works on itself. You give it a Task through `ra ask`. Triage decides whether to answer it, to iterate on a Task output, or to grow, which means changing its own code to close a Capability Gap. Every change runs through one closed Loop (Sense, Decide, Act, Gate, Learn). It lands as a git commit only when the tests, the evals, and a Reviewer on the Judge Model agree.

`CONTEXT.md` defines the vocabulary this file uses. The decisions behind the design are in `docs/adr/`. This file is a map to the files that hold each rule. When the two disagree, the code is right.

## The Loop

The idea is from control systems, by way of two Y Combinator talks whose notes are `docs/self-improving-loops.md`. An open loop decides, acts, and never measures what came of it. A closed loop measures its own output and feeds the measurement back into the next decision, so each pass corrects the last. Control engineers use closed loops for correctness and stability, not for speed, and that is the point here as well. A system that edits its own code in an open loop drifts, because nothing checks whether the last change helped before the next one. In a closed loop the system measures every change against evidence and keeps or undoes it.

The talks give a loop five layers: sensors, policy, tools, a quality gate, and a learning mechanism. Take away the fifth and what is left is an agent, not a loop. Here the five layers are the five phases of every run, in this order: Sense, Decide, Act, Gate, Learn. `ra ask` and `ra improve` run the same Loop, orchestrated by the Kernel, and the Modes differ in what Act produces and which checks the Gate runs. The runner is `LoopRunner` in `src/recursive_application/kernel/loop.py`; its methods are named after the phases.

**Sense.** Before anything else runs, the Kernel gathers every open Sensor Finding: the red cases and red frontier rungs of the latest eval report, trace anomalies, your negative feedback, open questions in the Wiki, and the findings the Kernel wrote during earlier runs. The trace anomalies are a span that ended in an error, one tool called again and again with the same arguments, repeated output-validation retries, a run slower than the median by a set factor, and a run that spent most of its budget. The Kernel ranks the findings by severity and then by age, and drops a finding a later run addressed unless newer evidence brought it back. Every Sensor is a pure function in `src/recursive_application/kernel/sensors.py`, with its threshold as a constant at the top of the file; `collect` is the one call that reads the runtime directory.

**Decide.** Triage reflects on the Task against the Capability Inventory and picks the Mode. In a Task or Growth Loop the Planner then turns the Task or the top Sensor Finding into one Plan: the evidence, the inferred cause, one change, its Target Cases, and the predicted impact including the cases at risk. You approve the Target Cases unless `--yes`; they are the Definition of Done. The policy this phase works under is the Policy Ceiling in `src/recursive_application/kernel/policy.py`, the Protected Paths in `src/recursive_application/kernel/paths.py`, and the items only you may grant, which a Plan has to name.

**Act.** The Actor makes the one change, with tools bounded by the Policy Ceiling. In a Growth Loop that is the Test Writer and then the Implementer, and between them the Kernel runs the changed tests and requires red (ADR 0008). In Answer and Task Loops it is the Worker, or the Specialist the Plan names. The tool configurations are `src/recursive_application/organism/tools.py`.

**Gate.** The Kernel judges the Iteration with deterministic checks, cheapest first, and stops gathering at the first failure, so the model call is the last thing an Iteration spends. For a Growth Iteration the order in `CHECK_ORDER` in `src/recursive_application/kernel/gate.py` is: no Protected Path in the diff, nothing outside the write scope, no existing eval case changed or deleted, the four checks of the Coding Guide, the Target Cases improved and no Guard Case regressed, no new trace anomaly, and the Reviewer on the Judge Model. An Answer or Task Iteration has no diff and runs the last three.

**Learn.** An accepted Improvement becomes a commit by the Kernel, and the Librarian records it in the Wiki with the commit and the dataset as breadcrumbs. A rejected Growth Iteration goes back to `HEAD` with git, and the Librarian records the lesson and the reason, which the next Planner reads in its prompt. A rejected Answer or Task Iteration hands the judge's reason to the next Worker. `_learn` and `_lesson` in `src/recursive_application/kernel/loop.py` hold this; the Wiki is `wiki/`.

What closes the loop is that Learn writes where Sense reads. An accepted Improvement changes the next eval report, and with it the Capability Inventory that Triage reflects against. A rejection leaves the Sensor Finding open and puts a lesson in the Wiki, which the next Planner gets in its State Bundle. Every Iteration lands in a Run Record and every agent call in the Trace Store, and the anomaly rules read both, so a run that got slow or expensive is itself a Sensor Finding for the next `ra improve`. Your `n` at the end of `ra ask` is one too.

The Kernel also refuses to run the loop open. An agent without an eval dataset never enters the Capability Inventory, so nothing senses it and Triage cannot pick it. The Kernel rejects a Plan without Target Cases before Act, and a Plan that changes Python without naming tests. Only the Kernel commits, and only after the Gate passes. Every capability the system adds to itself names all five layers before it writes any code; the table in `docs/coding-guide.md` says what each layer is for a new capability.

The Watcher, the second agent the talks say to build over the first, is the Kernel: the Sensors that turn failures into Sensor Findings, the Gate that judges each Iteration, and `ra improve` that fixes the causes. It is never an Organism agent, since a watcher the Organism could edit would stop watching. Growth may add sensors, tools, gates, and lessons, and never a watcher of its own. See `docs/adr/0010-every-agent-is-a-loop-element-and-the-kernel-is-the-watcher.md`.

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

## Providers

There are three ways to pay for model calls. An OpenRouter key: set `OPENROUTER_API_KEY`. This is the default. An OpenAI key: set `OPENAI_API_KEY`. A ChatGPT subscription: install the Codex CLI, run `codex login` once, and the Kernel reads the Sign-in it writes. The factory and the credential check are `src/recursive_application/kernel/providers.py`; the Sign-in reader and the backend adapter are `src/recursive_application/kernel/chatgpt.py`.

A model name is `<scheme>:<model>`. `RA_MODEL` names the primary model and `RA_JUDGE_MODEL` the Judge Model, and each may use a different Provider. `openrouter:<vendor>/<model>` calls through OpenRouter. `openai:<model>` calls OpenAI with the key. `chatgpt:<model>` calls the ChatGPT backend with the Sign-in; `.env.example` shows `gpt-5.5`. Before any command but `ra status` runs, the Kernel checks that each tier's key is set or its Sign-in loads, and exits 2 naming the variable or `codex login` otherwise. A model name pydantic-ai does not know also exits 2.

The Sign-in is the Codex CLI's `auth.json` under `CODEX_HOME`, by default the `.codex` directory in your home. The Kernel reads it before every request and never writes or refreshes it; when it has expired, run `codex login` again. A run is refused before it starts when the token would expire before `RA_MAX_MINUTES` ends. `ra status` reports whether the Sign-in loads and when its token expires, and lists the models the Codex CLI last saw the backend serve, so you can name a `chatgpt:` model that exists. The Kernel names itself to the backend as `recursive_application` in the `originator` header; `RA_CHATGPT_ORIGINATOR` changes that. A subscription run reports cost at the OpenAI list price for model ids the price data knows and 0 for the others, so for those the token limit is the budget rule.

OpenAI's Codex documentation neither permits nor forbids using the Sign-in outside Codex, and it calls API keys the right way to authenticate automation. Running on the subscription is your own risk. See `docs/adr/0011-model-access-is-a-kernel-seam-and-the-chatgpt-subscription-is-an-adapter.md`.

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
| `2` | aborted or usage error: a clarification, a stop rule, a dirty tree, a held lock, a refused approval, a missing setting, key, or Sign-in, a bad dataset name or path |
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

`ra status` reads all of this and prints eight sections, from the Providers and their credentials to the Librarian's frontier proposals; `src/recursive_application/kernel/status.py` lists them.

Tracked state is git. Each accepted Improvement is one commit made by the Kernel, authored as `ra Kernel <ra@localhost>`, with a message beginning `ra:`. The system never pushes. Git tracks the Wiki (`wiki/`) and the eval datasets (`evals/`) because they are the system's knowledge and its specification. See `docs/adr/0002-git-as-state-store.md`.

## Reading traces and Run Records

A run's spans are in `.ra/traces/<run_id>.jsonl`, one JSON object per line. The exporter appends each span as it ends, so you can read the file during the run. Each line holds the span's ids, name, timing, status, and `attributes`. Agent spans carry Pydantic AI's attributes, including the name and arguments of each tool call. The schema is in `src/recursive_application/kernel/tracing.py`. The anomaly rules in `src/recursive_application/kernel/sensors.py` read it.

The Run Record is `.ra/runs/<run_id>.json`. It holds the run's Mode, Task, timestamps, outcome, and the Sensor Findings it addressed, then one entry per Iteration. An Iteration entry holds its Plan, the coders' reports, the output path, the Gate result with every check it ran, the Review, the outcome and its reason, the commit, and its usage. The fields are `RunRecord` and `IterationRecord` in `src/recursive_application/kernel/records.py`. A run id starts with its timestamp, so the newest file sorts last.

## Frontier Cases

The growth agenda is a directory of eval files a human writes: `evals/frontier/`, one file per capability. Each file is a ladder of three to five cases from easy to hard that the system cannot pass yet. Each case's `metadata` carries `tier: frontier`, `capability` (the file's name), `rung` (consecutive from 1), and `gap_kind` (`tool`, `knowledge`, `connection`, `skill`, or `clarification`). It carries `needs_human` when a human must grant something first, such as network access. The Kernel refuses a file whose rungs skip a number; the rule is `validate_frontier` in `src/recursive_application/kernel/evals.py`.

A red rung is a Sensor Finding, one per capability naming its lowest red rung. `ra improve` picks it, the Planner makes that rung a Target Case, and the Iteration climbs one rung. A capability counts as available to Triage only when its whole ladder is green; `ra status` shows the ratio and the next rung under "Frontier". No agent writes under `evals/`.

To add a rung, append a case to `evals/frontier/<capability>.yaml` with the next `rung` number and the other metadata keys as in the file, then commit it. To add a capability, create a new file there with the same shape. When a ladder turns green, the Librarian proposes harder cases in `wiki/pages/open-questions/next-frontier-<capability>.md`. The page holds a YAML block in the frontier format and one sentence per case on why it is harder than the last rung. `ra status` lists these under "Frontier proposals". Copy what you accept into the frontier file. The system never edits a frontier file itself. See `docs/adr/0009-frontier-cases-are-the-growth-agenda.md`.
