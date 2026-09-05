# Phase 1 Seams: Kernel Primitives

Status: proposed on 2026-09-05 for the user's confirmation. Derived from `2026-09-05-recursive-application.md` (Phase 1 and Testing Strategy) and the grilling session behind it. Amended 2026-09-05 from the revised spec (`.scratch/recursive-application/spec.md`): the paths module gains the write scope and two protected directories; the records module gains `Plan.tests`, `Plan.actor`, `CheckResult`, `CodeReport`, `WorkerOutput`, `GateCheck`, and two Sensor sources. Where this document and the spec differ, the spec wins. Tests are written at these seams only; a behaviour not listed here is not tested until this list is amended.

Vocabulary: **module, interface, seam, adapter** as in the `codebase-design` skill; domain terms as in `CONTEXT.md`.

## Rules that apply to every module

- **The interface is the test surface.** Tests import only the names listed under *Interface*. Anything under *Internal* may change freely.
- **Vertical slices.** One tracer bullet at a time: write the failing test, make it pass with the least code, move to the next bullet. The bullets are ordered.
- **Expected values are literals** taken from this document or the plan, never recomputed the way the code computes them.
- **Dependencies by category.** In-process logic is tested directly. The filesystem is real under `tmp_path`. Git is the real binary in a temporary repository (the `git_repo` fixture in `tests/conftest.py`). Time is an injected clock. Models are `TestModel`, with `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` set in `tests/conftest.py`. Nothing touches the network or the real `.env`.
- **Environment hygiene.** `tests/conftest.py` removes provider and Logfire keys and every `RA_*` variable before each test and restores the environment afterwards. A test that sets variables uses `monkeypatch`.
- **Machine fact that shapes two seams.** This machine's global git config sets `commit.gpgsign=true` with 1Password as the SSH signer, so an unattended `git commit` blocks on a GUI prompt. The `git_repo` fixture disables signing in the temporary repo, and `Repo.commit_all` disables it explicitly for Kernel commits.
- **Off limits during the red → green loop:** `tests/conftest.py`, `pyproject.toml`, other modules' files, refactoring for its own sake (that belongs to review), commits.

## Module: `kernel/paths.py`, the Protected Path rule and repo layout

**Interface**
- `REPO_ROOT: Path`. Resolved once at import: `RA_REPO_ROOT` if set, else the checkout containing this package (the ancestor holding `pyproject.toml` and `src/`).
- `is_protected(path, root=REPO_ROOT) -> bool`. True when the Organism may never modify `path`. Accepts a path relative to `root` or an absolute path; absolute paths are resolved (symlinks included) before comparison; a path outside `root` counts as protected.
- `protected_globs() -> list[str]`. The same rule as glob patterns for tools that take patterns: directories as `<dir>/**`, files verbatim.
- `is_writable(path, root=REPO_ROOT) -> bool`. True only when `path` is inside the write-scope allowlist (below). Same path handling as `is_protected`; a path outside `root` is never writable.
- `writable_globs() -> list[str]`. The allowlist as glob patterns, for tools that take patterns.
- `ensure_ra_dirs(root=REPO_ROOT) -> Path`. Creates `.ra/` with `traces/`, `runs/`, `tasks/`, `evals/`; idempotent; returns the `.ra` path.
- `RA_DIRNAME = ".ra"`.

**The rule** (single source of truth; ADR 0001 plus `.env.example`, which documents Kernel settings):
- Protected directories: `src/recursive_application/kernel`, `tests/kernel`, `.claude`, `docs`, `thoughts`, `.scratch`.
- Protected files: `pyproject.toml`, `uv.lock`, `.env`, `.env.example`, `.gitignore`, `CONTEXT.md`.
- Everything else is Organism for the diff check, including `src/recursive_application/organism/**`, `tests/organism/**`, `evals/**`, `wiki/**`, `README.md`.
- Write scope (ADR 0001, consequence added 2026-09-05): tools may write only under `src/recursive_application/organism`, `tests/organism`, `evals`, `wiki`, and to `README.md`. Everything else, gitignored paths such as `.venv/` and `.ra/` included, is read-only, because a write there never reaches `git diff`.

**Dependencies**: in-process; `ensure_ra_dirs` uses the filesystem (`tmp_path`).

**Tracer bullets**
1. A Kernel file is protected; an Organism file is not.
2. Every entry of the rule is protected, including nested paths (`docs/adr/0001-kernel-organism-split.md`, `src/recursive_application/kernel/prompts/constitution.md`, `tests/kernel/test_loop.py`) and `./`-prefixed spellings.
3. The Organism paths listed above are not protected.
4. An absolute path inside the repo follows the rule; an absolute path outside the repo is protected.
5. `protected_globs()` contains `docs/**`, `src/recursive_application/kernel/**` and `uv.lock`.
6. `ensure_ra_dirs(tmp_path)` creates the four subdirectories and can be called twice.
7. `REPO_ROOT` holds `pyproject.toml` and `src/recursive_application`.
8. `thoughts/shared/plans/x.md` and `.scratch/x/spec.md` are protected.
9. `is_writable`: `wiki/index.md`, `evals/frontier/a.yaml`, `tests/organism/test_x.py`, `src/recursive_application/organism/agents.py`, and `README.md` are writable; `.venv/lib/x.py`, `.ra/runs/x.json`, `pyproject.toml`, `docs/coding-guide.md`, and a path outside the repo are not. `writable_globs()` contains `wiki/**` and `README.md`.

## Module: `kernel/settings.py`

**Interface**
- `Settings` (pydantic-settings `BaseSettings`) with these fields and defaults: `openrouter_api_key=""`, `ra_model="openrouter:anthropic/claude-sonnet-5"`, `ra_judge_model="openrouter:openai/gpt-5.4-mini"`, `logfire_token=None` (a blank value reads as `None`), `ra_max_iterations=5`, `ra_max_minutes=30`, `ra_budget_usd=Decimal("5")`, `ra_no_progress_iterations=2`, `ra_request_limit=50`, `ra_coder_request_limit=100`, `ra_breaker_failures=3`, `ra_breaker_reset_s=60`. Values come from environment variables (upper-cased field names) and, below them in precedence, the `.env` file at `REPO_ROOT`. Unknown keys in the file are ignored. The key is stripped of surrounding whitespace.
- `Settings.require_api_key() -> None`. Raises `SettingsError` naming `OPENROUTER_API_KEY` when the key is blank.
- `load_settings(env_file: Path | None = None) -> Settings`. Loads `Settings` from `env_file` (default `REPO_ROOT/.env`) and exports `OPENROUTER_API_KEY` and `LOGFIRE_TOKEN` into `os.environ` without overwriting values already there, so Pydantic AI's OpenRouter provider and Logfire find them.
- `SettingsError(RuntimeError)`.

**Invariants**: the key is never printed or logged; tests never read the real `.env` (always pass an explicit file).

**Dependencies**: process environment and one file, both substituted with `tmp_path` and `monkeypatch`.

**Tracer bullets**
1. With no file and no variables, the defaults are exactly the literals above.
2. A file holding `OPENROUTER_API_KEY= sk-or-test `, `RA_MODEL=openrouter:x/y`, `LOGFIRE_TOKEN=`, `RA_MAX_ITERATIONS=7` yields `"sk-or-test"`, `"openrouter:x/y"`, `None`, `7`, and untouched defaults elsewhere.
3. An environment variable wins over the file for the same key.
4. `require_api_key()` raises `SettingsError` for a blank key and passes for a set key.
5. `load_settings(file)` makes `os.environ["OPENROUTER_API_KEY"]` and `os.environ["LOGFIRE_TOKEN"]` visible and leaves an already-set variable alone.

## Module: `kernel/records.py`, data contracts and the Run Record

**Interface** (contract models are frozen, reject unknown fields, and are valid Pydantic AI `output_type`s):
- `Mode` (`StrEnum`): `answer`, `task`, `growth`. `Outcome = Literal["accepted", "rejected", "error", "aborted"]`.
- `CapabilityGap(kind: Literal["tool", "knowledge", "connection", "skill", "clarification"], description: str, how_to_acquire: str, needs_human: list[str] = [])`.
- `Reflection(required_capabilities: list[str], available: list[str] = [], gaps: list[CapabilityGap] = [])`.
- `TriageDecision(mode: Mode, reasoning: str, reflection: Reflection, clarifying_questions: list[str] = [])`.
- `EvalCase(name: str, inputs: str, expected_output: str | None = None, rubric: str | None = None, must_contain: list[str] = [])`.
- `Plan(title: str, evidence: str, cause: str, change: str, target_paths: list[str] = [], tests: list[str] = [], target_cases: list[EvalCase], predicted_impact: str, at_risk: list[str] = [], gaps: list[CapabilityGap] = [], actor: str | None = None)`. `tests` holds one-sentence behaviours at a public interface (ADR 0008); whether it may be empty depends on `target_paths` and is enforced by the Loop runner, not by the contract.
- `CheckResult(name: Literal["ruff-format", "ruff-check", "ty", "pytest"], passed: bool, output: str = "")`; `output` is truncated to 2,000 characters on construction.
- `CodeReport(summary: str, changed_files: list[str] = [], checks: list[CheckResult] = [])`, returned by the Test Writer and the Implementer.
- `WorkerOutput(content: str, gaps: list[CapabilityGap] = [])`.
- `Review(matches_plan: bool, gaming_suspected: bool, notes: str, verdict: Literal["accept", "reject"])`.
- `SensorFinding(id: str, source: Literal["evals", "traces", "feedback", "wiki", "reflection", "policy"], summary: str, details: str = "", severity: Literal["low", "medium", "high"] = "medium")`.
- `GateCheck(name: str, status: Literal["passed", "skipped", "failed"], excerpt: str = "")`; `GateResult(passed: bool, checks: list[GateCheck] = [])` with a `failed_checks: list[str]` property listing the names with status `failed`.
- `Usage(requests: int = 0, input_tokens: int = 0, output_tokens: int = 0, cost_usd: Decimal = Decimal("0"))`; `Usage + Usage` adds every field.
- `IterationRecord(number: int, started_at: datetime = now (UTC), finished_at: datetime | None = None, plan: Plan | None = None, test_report: CodeReport | None = None, code_report: CodeReport | None = None, output_path: str | None = None, gate: GateResult | None = None, review: Review | None = None, outcome: Outcome | None = None, commit_sha: str | None = None, usage: Usage = Usage())`.
- `RunRecord(run_id: str = generated, mode: Mode, task: str | None = None, started_at: datetime = now (UTC), finished_at: datetime | None = None, iterations: list[IterationRecord] = [], outcome: Outcome | None = None, findings_addressed: list[str] = [])` with a `total_usage: Usage` property. Not frozen (iterations are appended); unknown fields rejected. A generated `run_id` looks like `20260905-141500-a1b2c3` (UTC timestamp plus six hex characters).
- `RunStore(runs_dir: Path)`: `save(record) -> Path` writes `<runs_dir>/<run_id>.json`; `append_iteration(record, iteration) -> Path` appends and saves; `load(run_id) -> RunRecord`; `list_all() -> list[RunRecord]` ordered by `started_at`, `[]` when the directory is missing.

**Dependencies**: in-process; `RunStore` uses the filesystem (`tmp_path`).

**Tracer bullets**
1. Assigning a field on a contract raises `ValidationError`; an unknown field raises `ValidationError`.
2. A `TriageDecision` built from a plain dict (as an agent would return it) with a `connection` gap whose `needs_human == ["network access"]` validates, `mode == Mode.GROWTH`, `clarifying_questions == []`.
3. A `Plan` with two `tests` sentences and `actor="implementer"` round-trips through JSON (`model_dump_json` then `model_validate_json`) unchanged; a `Plan` built without `tests` and `actor` has `tests == []` and `actor is None`.
3b. `CheckResult(name="pytest", passed=False, output="x" * 5000).output` has length 2,000; `GateResult(passed=False, checks=[GateCheck("pytest", "failed"), GateCheck("ty", "skipped")]).failed_checks == ["pytest"]`.
4. `Usage(requests=1, cost_usd=Decimal("0.5")) + Usage(requests=2, input_tokens=3)` equals `Usage(requests=3, input_tokens=3, cost_usd=Decimal("0.5"))`.
5. `RunStore.append_iteration` then `load` returns an equal record whose file is named `<run_id>.json`; `total_usage.cost_usd == Decimal("0.01")` for one iteration costing `0.01`.
6. `list_all()` returns records in `started_at` order; a missing directory gives `[]`.

## Module: `kernel/tracing.py`, the Trace Store

**Interface**
- `configure_tracing(*, run_id: str, traces_dir: Path, token: str | None = None, verbose: bool = False) -> Path`. Configures Logfire for this process (`send_to_logfire="if-token-present"`, console output only when `verbose`), registers the Trace Store exporter for `<traces_dir>/<run_id>.jsonl`, instruments Pydantic AI, and returns that path. One call per process is the supported use.
- `read_spans(path: Path) -> list[dict]`. One dict per line; `[]` for a missing file; blank lines skipped.
- Span record schema, a Kernel contract the Sensors' anomaly rules depend on: `trace_id` (32 hex chars), `span_id` (16 hex chars), `parent_span_id` (16 hex chars or `null`), `name`, `start_ns`, `end_ns`, `duration_ms`, `status` (`"UNSET"`, `"OK"` or `"ERROR"`), `status_description`, `attributes` (flat object; values that are not JSON types are rendered as strings).

**Internal**: the exporter class and the span-to-dict conversion.

**Dependencies**: Logfire and OpenTelemetry in-process. Sending is off in tests because no token is passed and `LOGFIRE_TOKEN` is absent (conftest). Agent runs use `TestModel`.

**Tracer bullets**
1. After `configure_tracing`, `Agent(TestModel(), name="probe_agent").run_sync("hello")` leaves spans in the returned file: `read_spans` shows at least two, every one carrying all schema keys, and the text `probe_agent` appears in the file.
2. Spans of that run share one `trace_id`, and a child span's `parent_span_id` equals its parent's `span_id`.
3. A span opened with `logfire.span("kernel.probe", k="v")` is recorded with `attributes["k"] == "v"`, `status == "UNSET"` and `duration_ms >= 0`.
4. An exception raised inside a span records `status == "ERROR"`.
5. `read_spans` on a missing file returns `[]`.

Logfire's configuration is process-global, so the tests share one `configure_tracing` call (a module-scoped fixture) and tell their spans apart by name.

## Module: `kernel/breaker.py`, the circuit breaker

**Interface**
- `BreakerState` (`StrEnum`): `closed`, `open`, `half_open`. `CircuitOpenError(RuntimeError)`.
- `BreakerStore(path: Path, *, failure_threshold: int = 3, reset_timeout_s: float = 60.0, clock: Callable[[], float] = time.time)`:
  - `call(name: str, fn: Callable[[], T]) -> T`. Runs `fn` under the breaker named `name` (one per agent role). While open, raises `CircuitOpenError` without calling `fn`. Otherwise calls `fn`, records success or failure, persists to `path`, and returns the result or re-raises `fn`'s exception.
  - `states() -> dict[str, BreakerState]`. Current state of every known breaker, timeouts applied.
- Semantics: `failure_threshold` consecutive failures open the breaker at `clock()`; after `reset_timeout_s` it is half-open; a half-open success closes it and clears the count; a half-open failure re-opens it with a fresh timestamp; a success while closed resets the count. State survives across `BreakerStore` instances through the JSON file at `path`.

**Internal**: the per-name breaker object and the file format.

**Dependencies**: injected clock; filesystem (`tmp_path`).

**Tracer bullets**
1. Two failing calls still reach `fn`; the third opens the breaker: the next `call` raises `CircuitOpenError` and does not invoke `fn`.
2. After the clock advances by `reset_timeout_s`, a successful call goes through and `states()[name]` is `closed`.
3. A failure during the half-open trial re-opens: the following `call` raises `CircuitOpenError`.
4. A success after two failures resets the count: two further failures leave it closed.
5. A new `BreakerStore(path)` sees the open state from the file, recovers after the timeout, and a third instance then reports `closed`.
6. Breakers are independent: `planner` open leaves `coder` callable. A fresh store reports `{}`.

## Module: `kernel/git.py`, git as the state store

**Interface**: `class Repo(root: Path)` and `GitError(RuntimeError)` (its message carries git's stderr).
- Kernel operations: `is_repo() -> bool`, `has_commits() -> bool`, `head_sha() -> str`, `is_clean() -> bool` (ignored files do not count), `changed_paths() -> list[str]` (modified, staged, deleted, renamed with both names, untracked; sorted; repo-relative posix), `diff_text(max_chars=20_000) -> str` (working tree against HEAD with untracked files as additions; truncated with a marker), `commit_all(message: str) -> str` (stages everything, commits authored `ra Kernel <ra@localhost>`, unsigned regardless of the global git config, returns the new sha), `reset_hard_clean() -> None` (`reset --hard HEAD` then `clean -fd`; ignored files such as `.ra/` survive).
- Read helpers behind the Organism's git tools, each with a fixed argument list and output truncated to 20,000 characters: `log(n=20, path=None)` (one line per commit), `show(ref="HEAD")` (stat and patch), `blame(path)`, `status()` (short form), `diff(ref="HEAD", path=None)`. A `ref` or `path` that starts with `-` raises `GitError` before git runs.
- Invariants: argv is fixed and no shell is involved; nothing pushes; nothing signs; `git` itself is never exposed to a model (ADR 0002).

**Dependencies**: the real git binary in the temporary repository from the `git_repo` fixture.

**Tracer bullets**
1. The fixture repo is a repo, has commits, and is clean. After editing `README.md`, adding `new.txt` and writing under ignored `.ra/`, it is not clean and `changed_paths() == ["README.md", "new.txt"]`.
2. `diff_text()` contains `+changed` for the edit and shows `new.txt` with its content as an addition.
3. `commit_all("ra: add a")` returns a sha different from the previous head, leaves the tree clean, `log(n=1)` contains the message and `show("HEAD")` contains `ra Kernel`. This still holds when the repo's own config sets `commit.gpgsign=true` with an unusable `gpg.program`.
4. `reset_hard_clean()` restores `README.md`, removes `junk.txt`, keeps `.ra/keep`.
5. `blame("README.md")` contains the file's text; `status()` is empty when clean and names `README.md` after an edit; `diff(path="README.md")` contains `-# test` after replacing the content.
6. `show("--output=/tmp/x")`, `blame("-x")`, `log(path="--all")` and `diff(ref="-p")` raise `GitError`.
7. A freshly initialised repo without commits: `is_repo()` True, `has_commits()` False, `head_sha()` raises `GitError`; a plain directory: `is_repo()` False.

## Module: `kernel/cli.py`, the `ra` entry point (stub in this phase)

**Interface**: `app`, a Typer application that `pyproject.toml` maps to the `ra` script, with commands `ask TEXT [--yes/-y] [--max-iterations N] [--budget USD]`, `improve [--goal TEXT] [--yes/-y] [--max-iterations N] [--budget USD]`, `evals [--dataset NAME] [--repeat K]`, `status`, `wiki ingest PATH`, `wiki lint`. In this phase every command prints that it is not implemented yet and exits with code 2.

**Dependencies**: Typer only; tests use `typer.testing.CliRunner`.

**Tracer bullets**
1. `--help` exits 0 and lists `ask`, `improve`, `evals`, `status`, `wiki`.
2. `ask hello` and `wiki lint` exit 2 and mention "not implemented".

## Open points for the user

- Closed 2026-09-05: `thoughts/**` and `.scratch/**` are protected (spec, round 1).
- Kernel commits are unsigned by design. Signed Kernel commits would need a dedicated signing identity, not the user's 1Password key.
