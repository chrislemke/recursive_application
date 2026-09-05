# pydantic-ai-harness / pydantic-evals / pydantic-ai library facts for the agent runtime and eval harness (2026-09-05)

Research against primary sources only: the installed package source under `.venv/lib/python3.12/site-packages/` (abbreviated `SP/` below; every path is relative to it), the READMEs shipped inside `pydantic_ai_harness`, and probe scripts run locally with `uv run --no-sync python` from the repo root. No network model was ever called: every probe sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` before importing and uses `TestModel`/`FunctionModel` only. Probe scripts live in `scratchpad/research/`; no repo file was modified except this one. Installed versions checked from `SP/*.dist-info`: pydantic-ai-harness 0.29.0, pydantic-ai-slim 2.40.0, pydantic-evals 2.40.0, pydantic-graph 2.40.0, pydantic 2.13.5, genai-prices 0.1.6, logfire 5.0.0, opentelemetry-sdk/api 1.44.0, anyio 4.15.1, pyyaml 6.0.3.

Summary: the harness's `FileSystem` matches its three glob lists with **`fnmatch`, whose `*` already spans `/`**, so `**` is nearly always unnecessary and `*.py` matches `src/main.py`; patterns are matched against the canonicalised path relative to `root_dir`, so `..`, `./`, absolute paths and symlinks are all resolved before the check and anything escaping the root is rejected. The three lists split cleanly by operation: `protected_patterns` gates **writes only** (so the default `.env`/`.git/*` protection does *not* stop a read), `denied_patterns` gates reads and writes, `allowed_patterns` gates reads and writes plus per-entry walker filtering — and `read_only=True` is not a pattern at all but a `FilteredToolset` that removes `write_file`/`edit_file`/`create_directory`. All three walkers (`list_directory`, `search_files`, `find_files`) skip dotfiles unconditionally, and a walk root is never gated by `allowed_patterns`, which is why `allowed_patterns=['tests/organism/**']` makes `list_directory('.')` return `(empty directory)` while `find_files` still works. A denied write reaches the model as a `RetryPromptPart`, not an exception, and only becomes `UnexpectedModelBehavior` after the tool's `max_retries` (default **1**) is exhausted. `Shell` is `shell=True` in practice — the command string goes to `anyio.open_process`, which routes a `str` to `loop.subprocess_shell` — and `_check_command` validates **only `shlex.split(command)[0]`** by exact equality, so `uv add` cannot be denied while `uv run` is allowed and `echo ok && cat /etc/hosts` walks straight through an allowlist; `denied_operators` is a raw substring scan and the subprocess inherits the full parent environment unless `env` or `denied_env_patterns` is set (and `cat .env` leaks regardless). Capabilities attach as `Agent(model, capabilities=[...])`; two `FileSystem`s on one agent raise `UserError` on the clashing tool name unless one is wrapped in `PrefixTools`. On the evals side, **`Dataset.evaluate_sync(task, repeat=N)` does exist** (`repeat: int = 1`, renaming cases to `name [i/N]` with `source_case_name` as the aggregation key), sync task callables are supported and run on an anyio worker thread, `ReportCase` has **no `.error`** (a raising task produces a `ReportCaseFailure` in `report.failures` and no `ReportCase` at all), and there is no built-in `passed` — the idiom is "present in `report.cases` and every assertion true". `LLMJudge` defaults to one boolean assertion with a reason and no score, and its default judge model is the module global `'openai:gpt-5.2'`, settable only via `from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model` (not re-exported anywhere else). On the pydantic-ai side, `run_sync` **does** take a per-run `instructions=` (additive) and `Agent.override(instructions=...)` replaces everything; `UsageLimits.request_limit` already defaults to **50**; `UsageLimitExceeded` carries **no usage**, which is only recoverable through `agent.iter(...)`'s `AgentRun.usage`; `AgentRunResult.usage` is a **property, not a method**, and `RunUsage.cost` is a `Decimal | None` **attribute** that is `None` for unpriceable models; `infer_model('openrouter:...')` raises `UserError` for a missing `OPENROUTER_API_KEY` at construction time. Finally, under the default instrumentation version 5 the spans are `invoke_agent {name}`, `chat {model}` and **`execute_tool {tool}`** (`running tool` is the version-2 name and survives only as `logfire.msg`); an in-tool `ModelRetry` and a bad-arguments retry both mark the tool span `ERROR` (the latter adding `pydantic_ai.tool.failure_stage='validation'`), but an output-schema or output-validator retry emits **no span at all** and is visible only as a `tool_call_response` message part whose text ends `Fix the errors and try again.`

## A. pydantic-ai-harness 0.29.0 (`pydantic_ai_harness`)

Package name and version from the dist-info directory `SP/pydantic_ai_harness-0.29.0.dist-info/`; the import name is `pydantic_ai_harness` and the two capabilities live at `pydantic_ai_harness.filesystem` / `pydantic_ai_harness.shell`, both re-exported from the top-level package (`SP/pydantic_ai_harness/__init__.py:27, 49`).

### A1. `FileSystem` constructor and the three pattern lists

- Full signature (a `@dataclass`, so all fields are keyword-or-positional with these defaults):

  ```python
  FileSystem(
      root_dir: str | Path = '.',
      allowed_patterns: Sequence[str] = [],
      denied_patterns: Sequence[str] = [],
      protected_patterns: Sequence[str] = ['.git/*', '.env', '.env.*', '*.pem', '*.key', '**/secrets*'],
      max_read_lines: int = 2000,
      max_list_results: int = 1000,
      max_search_results: int = 1000,
      max_find_results: int = 1000,
      read_only: bool = False,
  )
  ```
  Source: `SP/pydantic_ai_harness/filesystem/_capability.py:16-23` (`_DEFAULT_PROTECTED`), `:26-63` (the dataclass fields and their docstrings). `__post_init__` rejects a non-positive or non-`int` value for any of the four `max_*` fields with `ValueError` (`:65-76`).

- **What each list does, and where it applies.** One method decides everything: `_check_access(path, *, write=False, check_allowed=True)` at `SP/pydantic_ai_harness/filesystem/_toolset.py:253-275`.
  - `protected_patterns` — consulted **only when `write=True`** (`if write and self._protected_patterns:` `:263-266`). Reads of a protected path succeed. The read-side predicate used by the walkers explicitly does not consult them ("Protected patterns are not consulted: they gate writes, and the walkers only read", `:277-288`).
  - `denied_patterns` — consulted on **every** access, read or write (`:268-271`), and also inside `_is_accessible` for walker entries (`:283-285`).
  - `allowed_patterns` — when non-empty, the path must match at least one, on reads and writes (`:273-275`), and per-entry inside the walkers (`:286-287`).
  - `read_only` is not a pattern at all: it swaps the toolset for `FilteredToolset(toolset, lambda ctx, tool: tool.name in READ_ONLY_TOOL_NAMES)`, i.e. it *removes the writing tools* rather than rejecting their calls (`SP/pydantic_ai_harness/filesystem/_capability.py:90-92`).
  - `root_dir` is resolved once at construction: `self._root = root_dir.resolve()` and `self._real_root = Path(os.path.realpath(self._root))` (`_toolset.py:192-193`).

- **Direct access vs walkers.** `read_file`, `write_file`, `edit_file`, `create_directory`, `file_info` pass `check_allowed=True` (the default). `list_directory`, `search_files`, `find_files` call `self._safe_resolve(path, check_allowed=False)` so the *walk root* is gated by denied patterns only — a root like `.` would never match a file pattern — and then filter every entry through `_resolve_walk_entry` → `_is_accessible` (`_toolset.py:253-261, 290-304, 496, 546, 606`). Shipped docs say the same: `SP/pydantic_ai_harness/filesystem/README.md:97-113`.

- **Patterns are matched against the path relative to `root_dir`, after canonicalisation.** `_safe_resolve` resolves first, then matches: "Resolution happens first so the access check matches patterns against the canonical path relative to the root, collapsing `.`/`..`/`//` segments that would otherwise slip past a literal pattern" (`_toolset.py:310-320`), with `_relative_to_root(resolved) = str(resolved.relative_to(self._real_root))` (`:306-308`). Probe: with `denied_patterns=['.env']`, all of `.env`, `./.env`, `src/../.env` and a symlink `link_env.txt → .env` are rejected with the same message.

- **`**` is not a recursive glob — matching is `fnmatch`, whose `*` already spans `/`.** `_matches` is `fnmatch.fnmatch(path, pattern)`, with one special case: a pattern starting with `**/` is retried with the `**/` stripped so `**/secrets*` also matches a root-level `secrets.yaml` (`_toolset.py:211-222`). The README states it outright: "Patterns are matched with `fnmatch`, whose `*` spans `/`, so `*.py` matches `src/main.py` and you rarely need `**`" (`SP/pydantic_ai_harness/filesystem/README.md:84-86`). Probe confirmation: `allowed_patterns=['*.py']` permits `read_file('src/x.py')`; `allowed_patterns=['tests/organism/*']` permits `tests/organism/t.py`. Consequence: `'.git/**/*'` does *not* match `.git/config` (there is no middle segment), while `.git/*` matches `.git/objects/deep.txt`.

- **`.env` is deniable for reading with `denied_patterns=['.env']`** — yes. Probe: `read_file('.env')` → `ModelRetry: Path '.env' is denied by pattern '.env'.` Note the *default* `protected_patterns` do **not** stop a read of `.env`; they only stop writes. Probe with the shipped defaults: `read_file('.env')` succeeded, `write_file('.env', ...)` → `ModelRetry: Path '.env' is protected (matches '.env').`

- **`.git/**` is deniable** — and so is the simpler `.git/*`, because `*` spans `/`. Probe: both `'.git/**'` and `'.git/*'` reject `.git/config` **and** `.git/objects/deep.txt`; a bare `'.git'` rejects neither; `'.git/**/*'` rejects only the nested file. Note the dotfile rule below makes this mostly moot for the walkers.

- **Dotfiles are invisible to all three walkers regardless of patterns.** `if any(part.startswith('.') for part in rel_path.parts): continue` in `list_directory` (`_toolset.py:506-509`), `search_files` (`:564-565`) and `find_files` (`:632-633`). `read_file`/`file_info` can still read them by name unless denied. Documented at `SP/pydantic_ai_harness/filesystem/README.md:120-122`.

- **`..`, absolute paths and escaping symlinks.** `_resolve_path` resolves `(self._root / path).resolve()`, then `real = Path(os.path.realpath(candidate))`, and raises `PermissionError(f'Path {path!r} resolves outside the root directory.')` unless `real.is_relative_to(self._real_root)` (`_toolset.py:228-251`). Symlink loops become `ModelRetry` (`:235-237, 240-246`). Walk entries get the same treatment via `_resolve_walk_entry`, which resolves the entry and matches patterns against the *resolved* location, so "a symlink can neither escape the root nor alias a file past a rule its own name would trip" (`:290-304`). Probe: `../outside.txt`, `/etc/hosts`, a symlink pointing outside, and `list_directory('..')` all produce `ModelRetry: Path '...' resolves outside the root directory.`

- Probe output (`scratchpad/research/probe_a1_patterns.py`, run 2026-09-05):

  ```
  --- defaults (no allowed/denied, DEFAULT protected) ---
   _DEFAULT_PROTECTED = ['.git/*', '.env', '.env.*', '*.pem', '*.key', '**/secrets*']
   read .env          : OK: [.env | 1 lines | hash:dad100f9affb]
   write .env         : ModelRetry: Path '.env' is protected (matches '.env').
   write .git/config  : ModelRetry: Path '.git/config' is protected (matches '.git/*').
   write .git/objects/deep.txt: ModelRetry: Path '.git/objects/deep.txt' is protected (matches '.git/*').
   read .git/config   : OK: [.git/config | 1 lines | hash:74d92d2fc80f]
  --- denied_patterns=[".env"] ---
   read .env          : ModelRetry: Path '.env' is denied by pattern '.env'.
   read ./.env        : ModelRetry: Path '.env' is denied by pattern '.env'.
   read src/../.env   : ModelRetry: Path '.env' is denied by pattern '.env'.
   read link_env.txt (symlink to .env): ModelRetry: Path '.env' is denied by pattern '.env'.
   list_directory .   : src/|tests/
  --- denied_patterns=[".git/**"] vs [".git/*"] ---
   pattern '.git/**':   .git/config -> denied      .git/objects/deep.txt -> denied
   pattern '.git/*':    .git/config -> denied      .git/objects/deep.txt -> denied
   pattern '.git':      .git/config -> OK          .git/objects/deep.txt -> OK
   pattern '.git/**/*': .git/config -> OK          .git/objects/deep.txt -> denied
  --- allowed_patterns=["tests/organism/**"] ---
   read tests/organism/t.py: OK
   read src/x.py           : ModelRetry: Path 'src/x.py' does not match any allowed pattern.
   write src/x.py          : ModelRetry: Path 'src/x.py' does not match any allowed pattern.
   write tests/organism/n.py: OK: Wrote 1 chars (1 lines) to tests/organism/n.py. [hash:a1fce4363854]
   list_directory .        : (empty directory)
   find_files **/*.py      : tests/organism/n.py|tests/organism/t.py
   search_files print      : tests/organism/t.py:1:print(2)
  --- fnmatch star crosses "/" ? ---
   allowed=["*.py"] read src/x.py: OK
   allowed=["tests/organism/*"] read tests/organism/t.py: OK
  --- traversal / symlink escape ---
   read ../outside.txt : ModelRetry: Path '../outside.txt' resolves outside the root directory.
   read /etc/hosts     : ModelRetry: Path '/etc/hosts' resolves outside the root directory.
   read link_out.txt   : ModelRetry: Path 'link_out.txt' resolves outside the root directory.
   list_directory ..   : ModelRetry: Path '..' resolves outside the root directory.
  ```

  The trap worth naming: `allowed_patterns=['tests/organism/**']` makes `list_directory('.')` return `(empty directory)`, because the top-level entries `src` and `tests` are matched against the file pattern per-entry and fail. `find_files`/`search_files` still find the permitted files because they walk recursively. If the agent is meant to browse, add the directory patterns too (e.g. `['tests', 'tests/organism', 'tests/organism/**']`).

### A2. Tools registered by `FileSystem`

- Registration is explicit in `FileSystemToolset.__init__` (`SP/pydantic_ai_harness/filesystem/_toolset.py:202-209`). Eight tools; the write set is `write_file`, `edit_file`, `create_directory`:

  | Tool | One-line description (from its docstring) | Writes? |
  |---|---|---|
  | `read_file` | Read a text file with line numbers. | no |
  | `write_file` | Create or overwrite a file with conflict detection. | **yes** |
  | `edit_file` | Edit a file by exact string replacement with conflict detection. | **yes** |
  | `list_directory` | List the contents of a directory. | no |
  | `search_files` | Search file contents using a regular expression. | no |
  | `find_files` | Find files by glob pattern (name matching, not content search). | no |
  | `create_directory` | Create a directory and any missing parents. | **yes** |
  | `file_info` | Get metadata about a file or directory. | no |

  Docstrings at `:323-333, 355-366, 440-455, 484-492, 533-543, 590-600, 650-658, 672-680`. The three writers are exactly the ones that call `_safe_resolve(path, write=True)` (`:367, 456, 659`).

- `READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset({'read_file', 'list_directory', 'search_files', 'find_files', 'file_info'})` — `_toolset.py:22-25`, exported from `pydantic_ai_harness` and `pydantic_ai_harness.filesystem`.

- **Selecting a subset:** the only built-in option is `read_only=True`, which yields the five read-only tools (`_capability.py:90-92`). Probe: `read_only=True` offered exactly `['file_info', 'find_files', 'list_directory', 'read_file', 'search_files']`. There is no `include_tools`/`exclude_tools` field. For a finer subset, call `FileSystem(...).get_toolset()` yourself and wrap it in `pydantic_ai.toolsets.FilteredToolset` (`SP/pydantic_ai/toolsets/filtered.py:14`), which is what the capability does internally.

### A3. `Shell` constructor, command validation, environment

- Full signature (`@dataclass`, `SP/pydantic_ai_harness/shell/_capability.py:50-105`):

  ```python
  Shell(
      cwd: str | Path = '.',
      allowed_commands: Sequence[str] = [],
      denied_commands: Sequence[str] = ('rm','rmdir','mkfs','dd','format','shutdown','reboot','halt','poweroff','init'),
      denied_operators: Sequence[str] = [],
      default_timeout: float = 30.0,
      max_output_chars: int = 50_000,
      persist_cwd: bool = False,
      allow_interactive: bool = False,
      env: Mapping[str, str] | None = None,
      denied_env_patterns: Sequence[str] = [],
  )
  ```
  `_DEFAULT_DENIED_COMMANDS` at `:14-25`. `__post_init__` drops the built-in denylist when an allowlist is given (`if self.denied_commands is _DEFAULT_DENIED_COMMANDS: self.denied_commands = [] if self.allowed_commands else list(_DEFAULT_DENIED_COMMANDS)`, `:107-110`), because `ShellToolset.__init__` raises `ValueError('Specify allowed_commands or denied_commands, not both.')` when both are non-empty (`SP/pydantic_ai_harness/shell/_toolset.py:150-151`). `max_output_chars <= 0` also raises (`:152-153`).

- **Yes: only the first token is validated.** The validating function is `ShellToolset._check_command` (`SP/pydantic_ai_harness/shell/_toolset.py:246-288`). After NUL/encoding checks, the interactive-command regex and the `denied_operators` substring scan, it does:

  ```python
  try:
      tokens = shlex.split(command)
  except ValueError:
      return                      # unparseable -> NO command-name check at all
  if not tokens:
      return
  executable = tokens[0]
  if self._denied_commands and executable in self._denied_commands:
      raise PermissionError(f'Command {executable!r} is denied.')
  if self._allowed_commands and executable not in self._allowed_commands:
      raise PermissionError(f'Command {executable!r} is not in the allowed list.')
  ```
  (`:277-288`). Matching is exact string equality against `tokens[0]` — not a prefix, not a path-normalised executable name. The shipped README says the same: "Validation checks only the first token, and allowlisted commands such as `python`, `git`, `uv`, and `make` can spawn arbitrary processes" (`SP/pydantic_ai_harness/shell/README.md:78-83`). Note the `except ValueError: return` branch: a command with an unbalanced quote skips the allow/deny check entirely and is still executed.

- **A subcommand such as `uv add` cannot be denied while `uv run` is allowed.** `denied_commands=['uv add']` never matches, because the comparison is `tokens[0] == 'uv add'`. Probe: with `denied_commands=['uv add']`, `uv add ruff` ran (it reached uv itself and failed on a missing `pyproject.toml`); with `denied_commands=['uv']`, `uv run x` was rejected; with `allowed_commands=['uv']`, `uv add ruff` ran. Subcommand-level policy has to be built outside this capability (a wrapper toolset, a `wrap_tool_execute` capability hook, or a shim executable).

- **Pipes, `&&`, `;`, redirections: executed by a real shell, and not inspected.** `run_command` passes the command **string** to `anyio.open_process(actual_command, cwd=..., stdout=PIPE, stderr=PIPE, start_new_session=True, env=self._resolve_env())` (`_toolset.py:392-399`); anyio documents "either a string to pass to the shell, or an iterable of strings" (`SP/anyio/_core/_subprocesses.py:144-145`) and the asyncio backend dispatches a `str`/`bytes` command to `loop.subprocess_shell(...)` (`SP/anyio/_backends/_asyncio.py:2800-2808`). So it is effectively `shell=True` (`/bin/sh -c`), **not** argv. The only defence against operators is `denied_operators`, a plain substring scan: `_first_denied_operator` = `next((op for op in self._denied_operators if op in command), None)` (`:242-244`), checked at `:273-275`. It is a substring test, so `echo "1 > 2"` trips `denied_operators=['>']`.
  Probe: `echo ok && cat /etc/hosts` **bypassed** `allowed_commands=['uv','echo']` and printed `/etc/hosts`, as did `echo hi | cat /etc/hosts`; `sh -c "cat /etc/hosts"` was rejected (first token `sh`). Backticks, `$HOME`, and `>` redirection all work.

- **`default_timeout` = 30.0 s**, overridable per call via `run_command(command, timeout_seconds=...)` (`_capability.py:74-75`; `_toolset.py:377, 388`). On timeout the process group is SIGTERM'd then SIGKILL'd after a 2 s grace period and the tool returns the literal string `[Command timed out after {timeout}s]` (`:416-426`, `_KILL_GRACE_PERIOD` at `:29`). Probe: `sleep 5` with `timeout_seconds=0.5` → `[Command timed out after 0.5s]`.

- **`max_output_chars` = 50 000**, enforced at the toolset dispatch seam in `ShellToolset.call_tool` via `truncate_tail(result, self._max_output_chars)` — the **tail** is kept so `[stderr]` and `[exit code: N]` survive (`_toolset.py:190-208`; `SP/pydantic_ai_harness/_output.py:17-36`; README `:43-47`).

- **Output shape**: `[stdout]\n...` and `[stderr]\n...` sections joined by a newline, `(no output)` when both are empty, plus `\n[exit code: N]` on non-zero exit (`_toolset.py:433-447`). Probe: `exit 3` → `(no output)\n[exit code: 3]`.

- **Environment.** By default `env=None` and `denied_env_patterns=[]`, and `_resolve_env()` returns `None`, meaning the subprocess **inherits the parent process's full environment** (`_toolset.py:210-229`). So yes — `printenv OPENROUTER_API_KEY` in the subprocess prints whatever the agent process has loaded. `denied_env_patterns` are `fnmatch.fnmatchcase` globs on variable **names**, applied to whichever base applies (`os.environ`, or an explicit `env`), and matching names are removed (`:220-229`). `LLM_API_KEY_ENV_PATTERNS = ('ANTHROPIC_*','GATEWAY_*','GEMINI_*','GOOGLE_*','OPENAI_*','OPENROUTER_*','PYDANTIC_AI_GATEWAY_API_KEY')` is a ready-made denylist, explicitly **not** a default (`SP/pydantic_ai_harness/shell/_capability.py:28-47`).
  Reading a `.env` **file** is a different matter: `Shell` has no path sandbox at all, so `cat .env` works regardless of `denied_env_patterns` or of any `FileSystem` patterns on the same agent. Probe:

  ```
  default env inherited, printenv OPENROUTER_API_KEY -> [stdout] | sk-or-from-parent-env
  cat .env -> [stdout] | OPENROUTER_API_KEY=sk-or-secret
  denied_env_patterns=LLM_API_KEY_ENV_PATTERNS, printenv OPENROUTER_API_KEY -> (no output) | [exit code: 1]
  ... MY_OTHER still there -> [stdout] | keepme
  ... but `cat .env` still leaks -> [stdout] | OPENROUTER_API_KEY=sk-or-secret
  env={"FOO":"bar"} -> printenv FOO: [stdout] | bar
  env={"FOO":"bar"} -> printenv OPENROUTER_API_KEY: (no output) | [exit code: 1]
  ```
  Both the docstring and the README label this "not a security boundary" (`_capability.py:88-94`; README `:124-133`).

- **Interactive commands** are blocked unless `allow_interactive=True`: regexes `^(vi|vim|nano|emacs|less|more|top|htop|man)\b`, `^sudo\s`, `^passwd\b`, `^ssh\b`, `^telnet\b`, `^ftp\b` (`_toolset.py:79-89`, checked at `:270-271`). Probe: `sudo ls`, `ssh x`, `less f` all rejected.

- **Every rejection is a `ModelRetry`, not a hard failure.** `_check_command` raises `PermissionError`/`ModelRetry`, and `run_command`/`start_command` are wrapped in `@_recoverable`, which converts `PermissionError, FileNotFoundError, NotADirectoryError, IsADirectoryError, ValueError` into `ModelRetry` (`_toolset.py:45-77` and the `_RECOVERABLE_ERRORS` tuple in the filesystem module `:31`). Same for the four tools registered: `run_command`, `start_command`, `check_command`, `stop_command` (`:155-166`).

- `persist_cwd=False` by default; when on, `cd` is tracked out-of-band by appending `pwd > <random temp file>` to the command rather than parsing stdout, so command output cannot spoof the cwd (`:290-325`). `for_run` returns a **fresh `ShellToolset` per run** so `_cwd` and background processes are not shared between concurrent runs (`:168-188`).

### A4. Attaching a capability to an `Agent`

- Both `capabilities=` and `toolsets=` exist on `Agent.__init__`; the harness capabilities are `AbstractCapability` subclasses (`SP/pydantic_ai_harness/filesystem/_capability.py:27`, `SP/pydantic_ai_harness/shell/_capability.py:51`) and the documented spelling is `Agent(model, capabilities=[FileSystem(...), Shell(...)])` (`SP/pydantic_ai_harness/filesystem/README.md:24-28`, `SP/pydantic_ai_harness/shell/README.md:25-29`). `FileSystem(...).get_toolset()` returns the plain toolset, so `Agent(model, toolsets=[FileSystem(...).get_toolset()])` also works (probe below) — but that route skips any non-toolset capability hooks.
- **Two `FileSystem` instances on one agent clash.** Probe: `Agent(TestModel(), capabilities=[FileSystem(root_dir=a), FileSystem(root_dir=b)])` → `pydantic_ai.exceptions.UserError: FileSystemToolset defines a tool whose name conflicts with existing tool from FileSystemToolset: 'read_file'. Rename the tool or wrap the toolset in a 'PrefixedToolset' to avoid name conflicts.`
- **Tool names can be prefixed** with the `PrefixTools` capability (`SP/pydantic_ai/capabilities/prefix_tools.py:15-67`), which wraps another capability's toolset in `PrefixedToolset` — its own docstring shows `PrefixTools(wrapped=Toolset(toolset), prefix='ns')` (`:21-37`). Probe: `capabilities=[FileSystem(root_dir=a), PrefixTools(wrapped=FileSystem(root_dir=b), prefix='src')]` yields both sets, the second as `src_read_file`, `src_write_file`, ….
- Probe (`scratchpad/research/probe_a4_attach.py`, run 2026-09-05):

  ```
  READ_ONLY_TOOL_NAMES = ['file_info', 'find_files', 'list_directory', 'read_file', 'search_files']
  Agent.__init__ has capabilities=: True | toolsets=: True
  run_sync output: 'done'
  tools offered to model: ['check_command', 'create_directory', 'edit_file', 'file_info', 'find_files',
    'list_directory', 'read_file', 'run_command', 'search_files', 'start_command', 'stop_command', 'write_file']
  two FileSystems -> UserError : FileSystemToolset defines a tool whose name conflicts with existing tool
    from FileSystemToolset: 'read_file'. Rename the tool or wrap the toolset in a `PrefixedToolset` ...
  PrefixTools: tools = [... 'read_file', 'search_files', 'src_create_directory', 'src_edit_file',
    'src_file_info', 'src_find_files', 'src_list_directory', 'src_read_file', 'src_search_files',
    'src_write_file', 'write_file']
  read_only=True tools: ['file_info', 'find_files', 'list_directory', 'read_file', 'search_files']
  toolsets= route tools: ['create_directory', 'edit_file', 'file_info', 'find_files', 'list_directory',
    'read_file', 'search_files', 'write_file']
  ```
  (The `run_sync` used `TestModel(call_tools=[], custom_output_text='done')`. With the default `TestModel()`, which calls every tool with synthesised arguments, the run aborts with `UnexpectedModelBehavior: Tool 'create_directory' exceeded max retries count of 1` — worth knowing before writing a smoke test.)

### A5. A denied write is a `ModelRetry` the model sees, not a raised exception

- `_check_access` raises `PermissionError` (`_toolset.py:263-275`), and every tool is wrapped in `@_recoverable`, which re-raises it as `ModelRetry(_sanitize_recoverable_error(e, real_root))` (`:94-115`, `_RECOVERABLE_ERRORS` at `:31`). pydantic-ai turns a `ModelRetry` from a tool into a `RetryPromptPart` fed back to the model. The error message is path-sanitised: absolute host paths are rewritten relative to the root, or replaced with `<outside-workspace>` / `<not-a-path>` (`:50-91`).
- Probe (`scratchpad/research/probe_a5_write_denied.py`, `FileSystem(root_dir=tmp, read_only=False, allowed_patterns=['tests/organism/**'])`, a `FunctionModel` that calls `write_file('src/x.py', 'hacked')` then gives up):

  ```
     model saw part: RetryPromptPart -> "Path 'src/x.py' does not match any allowed pattern." | tool_name= write_file
  final output: 'gave up'
  file unchanged: 'print(1)\n'
  persistent retry -> pydantic_ai.exceptions.UnexpectedModelBehavior : Tool 'write_file' exceeded max retries
    count of 1. Consider raising the retry limit, ...
  ```
- So: the model sees the refusal as a retry prompt and can correct itself; if it keeps retrying the same denied write, the run aborts with `UnexpectedModelBehavior` after the tool's `max_retries` (default 1) is exceeded. Nothing is written either way.
## B. pydantic-evals 2.40.0

### B1. `Dataset.from_file`, the YAML shape, and the evaluator registry

- Signature (`SP/pydantic_evals/dataset.py:556-563`):

  ```python
  @classmethod
  def from_file(
      cls,
      path: Path | str,
      fmt: Literal['yaml', 'json'] | None = None,
      custom_evaluator_types: Sequence[type[Evaluator[InputsT, OutputT, MetadataT]]] = (),
      custom_report_evaluator_types: Sequence[type[ReportEvaluator[InputsT, OutputT, MetadataT]]] = (),
  ) -> Self
  ```
  `fmt=None` infers from the suffix: `.yaml`/`.yml` → yaml, `.json` → json, anything else → `ValueError` (`:868-887`). `from_file` delegates to `from_text(..., default_name=path.stem)` (`:582-591`), so a file without a `name:` key takes the filename stem; with neither, `ValueError('Dataset name is required: ...')` (`:741-743`). Chain: `from_file` → `from_text` → `yaml.safe_load` → `from_dict` → `_serialization_type().model_validate(data)` → `_from_dataset_model` (`:598, 637, 663`).

- YAML shape, enforced by `_DatasetModel` / `_CaseModel`, both `extra='forbid'` (`SP/pydantic_evals/dataset.py:89-107`):

  ```python
  class _CaseModel(BaseModel, extra='forbid'):
      name: str | None = None
      inputs: InputsT
      metadata: MetadataT | None = None
      expected_output: OutputT | None = None
      evaluators: list[EvaluatorSpec] = []

  class _DatasetModel(BaseModel, extra='forbid'):
      json_schema_path: str | None = Field(default=None, alias='$schema')
      name: str | None = None
      cases: list[_CaseModel]
      evaluators: list[EvaluatorSpec] = []
      report_evaluators: list[EvaluatorSpec] = []
  ```
  So top level: `name`, `cases`, `evaluators`, `report_evaluators`, `$schema`. Per case: `name`, `inputs`, `metadata`, `expected_output`, `evaluators`. An unknown key is rejected — probe: `cases.0.bogus → Extra inputs are not permitted`.

- Default registry — `DEFAULT_EVALUATORS` at `SP/pydantic_evals/evaluators/common.py:358-372`:

  ```python
  DEFAULT_EVALUATORS = (Equals, EqualsExpected, Contains, IsInstance, MaxDuration, LLMJudge,
                        HasMatchingSpan, ToolCorrectness, TrajectoryMatch, ArgumentCorrectness,
                        MaxToolCalls, MaxModelRequests, GEval)
  ```
  All seven names asked about are present (`Contains`, `EqualsExpected`, `LLMJudge`, `MaxDuration`, `HasMatchingSpan`, `IsInstance`, `MaxToolCalls`), plus `Equals`, `ToolCorrectness`, `TrajectoryMatch`, `ArgumentCorrectness`, `MaxModelRequests`, `GEval`. Separately, `DEFAULT_REPORT_EVALUATORS` (for the `report_evaluators:` key) = `ConfusionMatrixEvaluator, KolmogorovSmirnovEvaluator, PrecisionRecallEvaluator, ROCAUCEvaluator` (`SP/pydantic_evals/evaluators/report_common.py:399-404`). The registry takes `custom_evaluator_types` first, then `setdefault`s the built-ins, so a custom class may shadow a default name without error (`SP/pydantic_ai/_spec.py:179-197`, called from `SP/pydantic_evals/dataset.py:686`).

- YAML spelling. `EvaluatorSpec` aliases `pydantic_ai._spec.NamedSpec` (`SP/pydantic_evals/evaluators/spec.py:6-8`, docstring `:14-17`). The wrap-validator `NamedSpec.deserialize` (`SP/pydantic_ai/_spec.py:82-93`) falls back to `_SerializedNamedSpec` (`:113-148`): `enforce_one_key` requires exactly one key in a mapping (`:116-124`); `_args` (`:132-145`) maps a bare string → no arguments, a mapping with all-string keys → kwargs, anything else → a single positional argument. Instantiation is `cls(*spec.args, **spec.kwargs)` (`:229-236`). Probe, loading real YAML:

  ```
  - EqualsExpected                                  -> EqualsExpected()
  - Contains: nope                                  -> Contains(value='nope')
  - Contains: {value: hello, case_sensitive: false} -> Contains(value='hello', case_sensitive=False)
  - LLMJudge: {rubric: polite, include_input: true} -> LLMJudge(rubric='polite', include_input=True,
                                                                assertion={'include_reason': True})
  - MaxDuration: 10                                 -> MaxDuration(seconds=10)
  - IsInstance: str                                 -> IsInstance(type_name='str')
  ```
  A bare `- EqualsExpected` builds `EqualsExpected()`, which returns `ctx.output == ctx.expected_output` as a bool assertion — except that it returns `{}` (no assertion at all) when `expected_output is None` (`SP/pydantic_evals/evaluators/common.py:50-56`). An unknown evaluator name raises `ExceptionGroup('1 error(s) loading evaluators from registry', ...)` from `_from_dataset_model` (`SP/pydantic_evals/dataset.py:738`).

### B2. `Case` fields, and `metadata` typing

- `@dataclass(init=False)` with an explicit keyword-only `__init__` (`SP/pydantic_evals/dataset.py:110-173`):

  | field | type | default | line |
  |---|---|---|---|
  | `name` | `str \| None` | `None` | `:132` |
  | `inputs` | `InputsT` | required | `:134` |
  | `metadata` | `MetadataT \| None` | `None` | `:136` |
  | `expected_output` | `OutputT \| None` | `None` | `:141` |
  | `evaluators` | `list[Evaluator[...]]` on the dataclass, but the `__init__` parameter is a **tuple** `= ()` | `()` | `:143-145`, `:153, :167-168` |

  `InputsT`/`OutputT`/`MetadataT` are `TypeVar(..., default=Any)` (`:70-75`). All `__init__` parameters are keyword-only (`*` at `:149`).

- **`from_file` does not validate `metadata` on an un-parameterised `Dataset`.** `_params()` walks the MRO for `__pydantic_generic_metadata__` and falls back to `(Any, Any, Any)` **with a `UserWarning`** (`:545-554`). Probe:

  ```
  WARNINGS on from_file: ["Could not determine the generic parameters for <class 'pydantic_evals.dataset.Dataset'>;
    using `Any` for each. You should explicitly set the generic parameters via
    `Dataset[MyInputs, MyOutput, MyMetadata]` when serializing or deserializing."]
    metadata: {'k': 'v', 'n': 3} <class 'dict'>
    _params(): (typing.Any, typing.Any, typing.Any)

  Dataset[str, str, Meta]._params(): (<class 'str'>, <class 'str'>, <class '__main__.Meta'>)
    typed metadata: Meta(difficulty='easy')
    typed metadata mismatch REJECTED: ValueError ... cases.0.metadata.difficulty
  ```
  So parameterise the class (`Dataset[Inputs, Output, Metadata]`) if you want metadata validated — and to silence the warning.

### B3. `evaluate_sync` / `evaluate` — `repeat` **does** exist

The plan's claim is **confirmed, not refuted**. `repeat` appears throughout `SP/pydantic_evals/dataset.py` (`:269-278, 292, 317, 325-326, 333, 342-343, 414, 428, 452, 470, 1049-1053`).

- `evaluate_sync` (`:417-434`) and `evaluate` (`:281-298`) have identical parameter lists; `evaluate_sync` is `run_until_complete(self.evaluate(...))` (`:462-475`, helper at `SP/pydantic_evals/_utils.py:94`). Verbatim from `inspect.signature`:

  ```python
  evaluate_sync(self,
      task: Callable[[InputsT], Awaitable[OutputT]] | Callable[[InputsT], OutputT], *,
      name: str | None = None,
      max_concurrency: int | None = None,
      progress: bool = True,
      retry_task: RetryConfig | None = None,
      retry_evaluators: RetryConfig | None = None,
      task_name: str | None = None,
      metadata: dict[str, Any] | None = None,
      repeat: int = 1,
      lifecycle: type[CaseLifecycle] | Callable[[Case], CaseLifecycle] | None = None,
  ) -> EvaluationReport[InputsT, OutputT, MetadataT]
  ```
  Everything after `task` is keyword-only.
- `name` is the experiment name; it falls back to `task_name`, which falls back to `get_unwrapped_function_name(task)` (`:330-331`) — that is why the default report title reads `Evaluation Summary: task`.
- `max_concurrency=None` means unbounded (`anyio.Semaphore` vs `AsyncExitStack`, `:336`); `< 1` raises `ValueError` (`:327-328`). `progress=True` renders a rich progress bar (`:335`).
- `repeat` semantics (`_build_tasks_to_run`, `:269-278`): each case runs `repeat` times, report case names become `f'{case_name} [{run_idx}/{repeat}]'`, and `ReportCase.source_case_name` keeps the original name as the aggregation key. `repeat < 1` raises. Probe:

  ```
  case names: ['a [1/2]', 'a [2/2]']
  source_case_name: ['a', 'a']
  case_groups: [('a', 2)]
  repeat=0 -> ValueError repeat must be >= 1, got 0
  ```
- `metadata` here is *experiment* metadata (lands on the span and on `report.experiment_metadata`), unrelated to case metadata. `retry_task`/`retry_evaluators` take a tenacity-backed `RetryConfig` (`:990-993`).

### B4. `EvaluationReport` and `ReportCase`

- `EvaluationReport` — `@dataclass(kw_only=True)`, `SP/pydantic_evals/reporting/__init__.py:316-341`: `name: str`, `cases: list[ReportCase]`, `failures: list[ReportCaseFailure] = []`, `analyses: list[ReportAnalysis] = []`, `report_evaluator_failures: list[EvaluatorFailure] = []`, `experiment_metadata: dict[str, Any] | None = None`, `trace_id: str | None`, `span_id: str | None`.

- `ReportCase` — `@dataclass(kw_only=True)`, `SP/pydantic_evals/reporting/__init__.py:86-120`:

  | field | type | line |
  |---|---|---|
  | `name` | `str` | `:90` |
  | `inputs` | `InputsT` | `:92` |
  | `metadata` | `MetadataT \| None` | `:94` |
  | `expected_output` | `OutputT \| None` | `:96` |
  | `output` | `OutputT` | `:98` |
  | `metrics` | `dict[str, float \| int]` | `:101` |
  | `attributes` | `dict[str, Any]` | `:102` |
  | `scores` | `dict[str, EvaluationResult[int \| float]]` | `:104` |
  | `labels` | `dict[str, EvaluationResult[str]]` | `:105` |
  | `assertions` | `dict[str, EvaluationResult[bool]]` | `:106` |
  | `task_duration` | `float` | `:108` |
  | `total_duration` | `float` (task + evaluators) | `:109` |
  | `source_case_name` | `str \| None = None` | `:111` |
  | `trace_id` / `span_id` | `str \| None = None` | `:115, :117` |
  | `evaluator_failures` | `list[EvaluatorFailure] = []` | `:119` |

- **There is no `ReportCase.error` — not found** (probe: `has .error attr: False`). A task that raises produces a `ReportCaseFailure` appended to `report.failures` and **excluded** from `report.cases` (built at `SP/pydantic_evals/dataset.py:1189-1201`, sorted at `:388-393`). `ReportCaseFailure` (`SP/pydantic_evals/reporting/__init__.py:123-148`) has `name, inputs, metadata, expected_output, error_message: str, error_stacktrace: str, source_case_name, trace_id, span_id` — no `output`, no `assertions`. Probe:

  ```
  cases: []
  failures: [('a', 'ValueError: kaboom')]
  averages(): None
  ```

- `assertions` values are `EvaluationResult` — `@dataclass(kw_only=True)` at `SP/pydantic_evals/evaluators/evaluator.py:59-81` with `name: str`, `value: EvaluationScalarT`, `reason: str | None`, `source: EvaluatorSpec`, `evaluator_version: str | None = None`. `.reason` is filled only when the evaluator returns an `EvaluationReason` (`:35-46`); scalar-returning evaluators leave it `None`. The split into assertions/scores/labels is by the **runtime type of the value**: `bool` → assertions, `int|float` → scores, `str` → labels (`_group_evaluator_outputs_by_type`, `SP/pydantic_evals/dataset.py:1225-1240`). Probe:

  ```
  Contains: value=False reason="Output string 'hello x' does not contain expected string 'NOPE'"
            source=NamedSpec(name='Contains', arguments=('NOPE',)) evaluator_version=None
  EqualsExpected: value=False reason=None source=NamedSpec(name='EqualsExpected', arguments=None)
  ```

- **Deciding "passed": there is no built-in `passed` property (not found).** The library's own aggregation counts `n_passing = sum(1 for case in cases for assertion in case.assertions.values() if assertion.value)` (`SP/pydantic_evals/reporting/__init__.py:242-246`), so the idiom is:

  ```python
  passed = (case.name not in {f.name for f in report.failures}
            and all(a.value for a in case.assertions.values())
            and not case.evaluator_failures)
  ```
  Because a task error yields no `ReportCase` at all, "no error" collapses to "the case is in `report.cases`". A case with zero assertions passes vacuously — worth guarding against.

- `report.print(...)` exists (`SP/pydantic_evals/reporting/__init__.py:453-478`), with `width`, `baseline`, `console`, and a long list of `include_*` flags: `include_input`, `include_metadata`, `include_expected_output`, `include_output`, `include_durations=True`, `include_total_duration`, `include_removed_cases`, `include_averages=True`, `include_errors=True`, `include_error_stacktrace`, `include_evaluator_failures=True`, `include_analyses=True`, `include_reasons=False`, plus render configs. `render(...)` (`:394-450`) is the same minus `console` and returns a `str`; `__str__` calls it (`:721-723`). `console_table(...)` (`:542-565`) and `failures_table(...)` (`:686-696`) return rich renderables.

- `averages()` exists (`:380-392`) and returns `ReportCaseAggregate | None` — a `BaseModel` (`:181-192`) with `name: str`, `scores`, `labels`, `metrics`, `assertions: float | None` (the **pass fraction**, not a count), `task_duration`, `total_duration`. `None` when there is nothing to aggregate. With `repeat > 1` it averages per-group summaries (`average_from_aggregates`, `:258`).

- Serialisation: **no `to_dict`, no `model_dump`** on the dataclasses (probe: `has to_dict: False has model_dump: False`). Use the module-level adapters: `EvaluationReportAdapter = TypeAdapter(EvaluationReport[Any, Any, Any])` (`:726`), `ReportCaseAdapter` / `ReportCaseFailureAdapter` (`:151-152`), and the private `_REPORT_CASES_ADAPTER`, `_REPORT_CASE_FAILURES_ADAPTER`, `_REPORT_CASE_AGGREGATE_ADAPTER` (`SP/pydantic_evals/dataset.py:84-86`). Probe:

  ```
  EvaluationReportAdapter.dump_python keys: ['name', 'cases', 'failures', 'analyses',
    'report_evaluator_failures', 'experiment_metadata', 'trace_id', 'span_id']
  json: {"name":"t2","cases":[{"name":"a","inputs":"x","metadata":null,"expected_output":"zzz",
    "output":"hello x","metrics":{},"attributes":{},"scores":{},"labels":{},
    "assertions":{"Contains":{"name":"Contains","value":false,
      "reason":"Output string 'hello x' does not contain expected string 'NOPE'",
      "source":{"name":"Contains","arguments":["NOPE"]},"evaluator_version":null}, ...
  ```
  That adapter is the clean way to persist a report as JSON.

### B5. `LLMJudge` parameters and the default judge model

- Dataclass at `SP/pydantic_evals/evaluators/common.py:224-238`:

  | param | type | default | line |
  |---|---|---|---|
  | `rubric` | `str` | **required** | `:231` |
  | `model` | `Model \| KnownModelName \| str \| None` | `None` | `:232` |
  | `include_input` | `bool` | `False` | `:233` |
  | `include_expected_output` | `bool` | `False` | `:234` |
  | `model_settings` | `ModelSettings \| None` | `None` | `:235` |
  | `score` | `OutputConfig \| Literal[False]` | `False` | `:236` |
  | `assertion` | `OutputConfig \| Literal[False]` | `OutputConfig(include_reason=True)` → `{'include_reason': True}` | `:237` |

  So out of the box `LLMJudge` emits **one boolean assertion carrying a reason, and no score**. `OutputConfig` is a `total=False` TypedDict with `evaluation_name` and `include_reason` (`:187-191`). When both `score` and `assertion` are enabled the result names become `{name}_score` and `{name}_pass`; with only one, the bare evaluator name (`:271-281`).

- **`set_default_judge_model` lives only in `pydantic_evals.evaluators.llm_as_a_judge`** (`SP/pydantic_evals/evaluators/llm_as_a_judge.py:220-226`, in that module's `__all__` at `:22`). It is **not** re-exported from `pydantic_evals.evaluators` (`SP/pydantic_evals/evaluators/__init__.py:32-68`) nor from `pydantic_evals` (`SP/pydantic_evals/__init__.py:12-18`). Probe:

  ```
  in pydantic_evals.evaluators.llm_as_a_judge: True
  in pydantic_evals.evaluators: False
  in pydantic_evals: False
  signature: (model: 'models.Model | models.KnownModelName') -> 'None'
  _default_model: 'openai:gpt-5.2'
  ```
  So the import is `from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model`. It accepts a `Model` instance **or** a model-name string, and simply sets the module global (`:225-226`). The un-set fallback is `_default_model = 'openai:gpt-5.2'` (`:26`).

- A YAML `LLMJudge` without `model` does resolve to that default **at evaluation time**: `LLMJudge.evaluate` passes `self.model` straight through (`SP/pydantic_evals/evaluators/common.py:240-268`) and each `judge_*` helper does `agent.run(prompt, model=model or _default_model, model_settings=model_settings)` (`SP/pydantic_evals/evaluators/llm_as_a_judge.py:81, 124, 171, 215, 374`). Probe with the default judge model swapped for a `FunctionModel` (`ALLOW_MODEL_REQUESTS=False`, no network):

  ```
  _default_model now: FunctionModel(function=<function judge_fn ...>, stream_function=None)
  loaded evaluator: LLMJudge(rubric='is polite', include_input=True, assertion={'include_reason': True})
    model field: None
  assertion LLMJudge: value=True reason='looks fine'
  scores: {}
  ```
  `GEval` behaves identically (`:284-347`). Both override `build_serialization_arguments` so a `Model` instance is written back to YAML as its `model_id` string (`_serialize_model_as_string`, `:212-222`).

### B6. `to_file`, round-tripping, appending, the `$schema` line

- Signature (`SP/pydantic_evals/dataset.py:747-753`):

  ```python
  def to_file(self, path, fmt=None,
              schema_path: Path | str | None = DEFAULT_SCHEMA_PATH_TEMPLATE,  # './{stem}_schema.json'
              custom_evaluator_types=(), custom_report_evaluator_types=())
  ```
  `DEFAULT_SCHEMA_PATH_TEMPLATE = './{stem}_schema.json'` (`:79`); `_YAML_SCHEMA_LINE_PREFIX = '# yaml-language-server: $schema='` (`:81`). Unless `schema_path=None`, `to_file` **also writes a sibling JSON-Schema file** (`_save_schema`, `:845-855`) and **prepends** the `# yaml-language-server: $schema=…` line (`:770-795`, prepend at `:787-790`); for JSON it injects a `"$schema"` key instead (`:792-794`, `_add_json_schema` at `:903`). Serialisation runs with `context={'use_short_form': True}` (`:783`), which is what emits evaluators in short form (`NamedSpec.serialize`, `SP/pydantic_ai/_spec.py:95-110`).
- **`from_file` tolerates the `# yaml-language-server: $schema=` comment** (YAML comments are dropped by `safe_load`) and also a literal `$schema:` key, aliased by `_DatasetModel.json_schema_path` (`:102-103`). Probe with both present: `loaded ok, name: s cases: ['a']`.
- Round-trip probe (build in Python → `to_file` → cat → `from_file` → append → save → reload):

  ```yaml
  # yaml-language-server: $schema=rt_schema.json
  name: roundtrip
  cases:
  - name: c1
    inputs: world
    metadata:
      difficulty: easy
      tags:
      - smoke
    expected_output: hello world
    evaluators:
    - Contains: hello
  - name: c2
    inputs: abc
    metadata: null
    expected_output: hello abc
    evaluators:
    - EqualsExpected
  evaluators:
  - IsInstance: str
  - LLMJudge:
      rubric: is polite
      include_input: true
  report_evaluators: []
  ```
  ```
  === files written ===  rt.yaml 431   rt_schema.json 67758
  === reloaded ===
  name: roundtrip
  ds evaluators: [IsInstance(type_name='str'), LLMJudge(rubric='is polite', include_input=True,
                  assertion={'include_reason': True})]
    c1 'world' 'hello world' {'difficulty': 'easy', 'tags': ['smoke']} [Contains(value='hello')]
    c2 'abc' 'hello abc' None [EqualsExpected()]
  # after dataset.cases.append(Case(...)) and to_file again:
  reloaded case names: ['c1', 'c2', 'c3']
  c3 metadata: {'difficulty': 'hard'}
  ```
  So: metadata round-trips verbatim (under `Any`), evaluators round-trip in short form with defaults stripped (`build_serialization_arguments`, `SP/pydantic_evals/evaluators/_base.py:91-110` — `LLMJudge`'s `assertion` default is omitted from the YAML but restored on load), and `dataset.cases.append(Case(...))` then `to_file` works.
- Two caveats. (1) The default `schema_path` drops a ~66 KB `<stem>_schema.json` beside the dataset on every save; pass `schema_path=None` to suppress both it and the comment line (probe confirmed no `nosch_schema.json` was written). (2) `Dataset.add_case` rejects duplicate case names (`:494-496`) but a raw `cases.append` does **not** — the duplicate check only runs in `__init__` (`:250-260`) and `add_case`.

### B7. Probe: hand-written YAML, plain sync task, full case detail

Two cases (`Contains` and `EqualsExpected`) plus a dataset-level `IsInstance`, evaluated with `def task(inputs: str) -> str: return f'hello {inputs}'`:

```
dataset name: b7_dataset
dataset-level evaluators: [IsInstance(type_name='str')]
 case: 'greet' inputs: 'world' expected: 'hello world' metadata: {'difficulty': 'easy', 'tags': ['smoke']}
       type(metadata): dict evaluators: [Contains(value='hello')]
 case: 'echo'  inputs: 'abc'   expected: 'abc!' metadata: None evaluators: [EqualsExpected()]

=== per-case details ===
name: greet
  output: 'hello world'   inputs: 'world'   expected_output: 'hello world'
  metadata: {'difficulty': 'easy', 'tags': ['smoke']}
  assertions type: dict
    'Contains':   EvaluationResult value=True reason=None source=NamedSpec(name='Contains', arguments=('hello',))
    'IsInstance': EvaluationResult value=True reason=None source=NamedSpec(name='IsInstance', arguments=('str',))
  scores: {}   labels: {}   metrics: {}   attributes: {}
  task_duration: 0.00038904102984815836   total_duration: 0.0011219978332519531
  evaluator_failures: []   has .error attr: False
name: echo
  output: 'hello abc'   expected_output: 'abc!'   metadata: None
    'EqualsExpected': EvaluationResult value=False reason=None source=NamedSpec(name='EqualsExpected', arguments=None)
    'IsInstance':     EvaluationResult value=True  reason=None
  task_duration: 0.0006151249981485307   total_duration: 0.0010581016540527344
report.failures: []
report.averages(): name='Averages' scores={} labels={} metrics={} assertions=0.75
  task_duration=0.0005020830139983445 total_duration=0.0010900497436523438
report.case_groups(): None
```

`report.print()` verbatim:

```
      Evaluation Summary: task
┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Case ID  ┃ Assertions ┃ Duration ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━┩
│ greet    │ ✔✔         │    389µs │
├──────────┼────────────┼──────────┤
│ echo     │ ✗✔         │    615µs │
├──────────┼────────────┼──────────┤
│ Averages │ 75.0% ✔    │    502µs │
└──────────┴────────────┴──────────┘
```

The default `print()` shows only assertion ticks and durations — no reasons, no outputs. `include_reasons=True` (and `include_output=True`) is what surfaces the failure text (`SP/pydantic_evals/reporting/__init__.py:1343-1356`):

```
┃ Case ID  ┃ Outputs ┃ Assertions                                                       ┃ Duration ┃
│ a        │ hello x │ Contains: ✗                                                      │    150µs │
│          │         │   Reason: Output string 'hello x' does not contain expected      │          │
│          │         │ string 'NOPE'                                                    │          │
```

### B8. Sync task functions

- The task type is a union of async and sync from the start: `task: Callable[[InputsT], Awaitable[OutputT]] | Callable[[InputsT], OutputT]` (`SP/pydantic_evals/dataset.py:283, :419`).
- Dispatch in `_run_task` (`:976-983`):

  ```python
  if is_async_callable(task):
      task_output_ = await await_maybe(task(case.inputs))
  else:
      # A plain `def` may still return an awaitable, which `to_thread.run_sync` would leave un-awaited.
      task_output_ = await await_maybe(await to_thread.run_sync(task, case.inputs))
  ```
  A plain `def` runs on an `anyio.to_thread` worker, so it does not block the event loop and still honours `max_concurrency`. Evaluators get analogous treatment in `Evaluator.evaluate_async` (`SP/pydantic_evals/evaluators/evaluator.py:233-252`), though they are **not** offloaded to a thread — the comment at `:248-249` says to override `evaluate_async` if a sync evaluator would block.
- The task receives exactly one positional argument, `case.inputs` — no context, no metadata, no expected output. Extra signal goes back through `increment_eval_metric` / `set_eval_attribute` (`SP/pydantic_evals/__init__.py:9`, backed by `SP/pydantic_evals/_task_run.py`), surfacing as `ReportCase.metrics` / `.attributes`.
## C. pydantic-ai-slim 2.40.0

### C1. `Agent.__init__`

- Class at `SP/pydantic_ai/agent/__init__.py:432`; the real (non-overload) `__init__` at `:572-593`, docstring `:594-663`, body `:664-836`. Two identical overloads precede it (`:524-547`, `:548-571`) purely for Pyright's union-`output_type` resolution (comment at `:521-523`). Full parameter list:

  ```python
  Agent(model: models.Model | models.KnownModelName | str | None = None, *,
        output_type: OutputSpec[OutputDataT] = str,
        instructions: AgentInstructions[AgentDepsT] = None,
        system_prompt: str | Sequence[str] = (),
        deps_type: type[AgentDepsT] = object,
        name: str | None = None,
        description: TemplateStr[AgentDepsT] | str | None = None,
        model_settings: AgentModelSettings[AgentDepsT] | None = None,
        retries: int | AgentRetries | None = None,
        validation_context: Any | Callable[[RunContext[AgentDepsT]], Any] = None,
        tools: Sequence[Tool[AgentDepsT] | ToolFuncEither[AgentDepsT, ...]] = (),
        toolsets: Sequence[AgentToolset[AgentDepsT]] | None = None,
        defer_model_check: bool = False,
        end_strategy: EndStrategy = 'graceful',
        metadata: AgentMetadata[AgentDepsT] | None = None,
        tool_timeout: float | None = None,
        max_concurrency: AnyConcurrencyLimit = None,
        capabilities: Sequence[AgentCapability[AgentDepsT]] | None = None) -> None
  ```
- `model` defaults to `None` (`:574`); docstring: "The default model to use for this agent, if not provided, you must provide the model when calling it" (`:598-599`). `name: str | None = None` (`:580`), inferred from the call frame on first run when `None` (`:601-602`).
- **There is no `output_retries` parameter — refuted.** There is a single `retries: int | AgentRetries | None = None` (`:582`), where `AgentRetries` is a `TypedDict(total=False)` with keys `tools` and `output` (`SP/pydantic_ai/agent/abstract.py:109-127`). A bare `int` sets both; both default to **1** (docstring `:614-623`; normalisation at `:720-723` into `self._max_tool_retries` / `self._max_output_retries`). That default of 1 is what produced the `exceeded max retries count of 1` errors in the harness probes (§A4, §A5).
- **`capabilities=` exists — confirmed**: `capabilities: Sequence[AgentCapability[AgentDepsT]] | None = None` (`:592`, and in both overloads at `:546`, `:570`), handled by `wrap_capability_funcs` + `_inject_auto_capabilities` (`:666-668`), a `CombinedCapability` root (`:676-690`), `bind_capabilities_tier` (`:809-813`), with contributions extracted at `:822-826`.
- `agent.model` is a property returning `self._model` (`:1132-1143`; abstract declaration `SP/pydantic_ai/agent/abstract.py:349-354`). A model **string is resolved eagerly** in `__init__` — `self._model = models.infer_model(model)` (`:815-816`) — unless `defer_model_check=True` or a capability declares `has_resolve_model_id`.
- Probe (`c1_probe.py`):

  ```
  pydantic_ai version: 2.40.0
  no model      -> type: <class 'NoneType'> value: None
  TestModel()   -> type: <class 'pydantic_ai.models.test.TestModel'>
  'test'        -> type: <class 'pydantic_ai.models.test.TestModel'>
  'test' defer  -> type: <class 'str'> value: 'test'
  ```
  So "does this Agent have a model?" is `agent.model is None` — but only reliable when `defer_model_check=False`, since a deferred string stays a `str`.

### C2. `run_sync`, per-run overrides, dynamic instructions

- `Agent.run_sync` is defined on the abstract base: `SP/pydantic_ai/agent/abstract.py:721-743` (overloads `:669-701`, `:694-719`; docstring `:744-798`; body `:799-828`):

  ```python
  run_sync(self, user_prompt: str | Sequence[UserContent] | None = None, *,
           output_type=None, message_history=None, deferred_tool_results=None,
           conversation_id=None, run_id=None, model=None, instructions=None, deps=None,
           model_settings=None, usage_limits=None, cancellation_token=None, usage=None,
           metadata=None, retries=None, infer_name=True, toolsets=None,
           event_stream_handler=None, capabilities=None, spec=None) -> AgentRunResult[Any]
  ```
- `model=` per run: **yes** (`:729`). `usage_limits=`: **yes** (`:733`). `deps=`, `message_history=`, `toolsets=`, `retries=`, `capabilities=`: all yes.
- **`instructions=` per run exists — confirmed**, at `SP/pydantic_ai/agent/abstract.py:730`, documented "Optional additional instructions to use for this run" (`:771`), and present on `run`, `run_sync` and `iter` alike. So run-time instructions never require touching the Agent object. It is **additive**; `Agent.override(instructions=...)` is the **replacing** form.
- `Agent.override` — `@contextmanager` at `SP/pydantic_ai/agent/__init__.py:1971-1986` (docstring `:1987-2015`, body `:2016-2147`). Exact accepted keywords, all keyword-only, all sentinel-defaulted to `_utils.UNSET` except `spec`:

  | kwarg | type | line |
  |---|---|---|
  | `name` | `str \| Unset` | `:1975` |
  | `deps` | `AgentDepsT \| Unset` | `:1976` |
  | `model` | `Model \| KnownModelName \| str \| Unset` | `:1977` |
  | `toolsets` | `Sequence[AbstractToolset[AgentDepsT]] \| Unset` | `:1978` |
  | `tools` | `Sequence[Tool[AgentDepsT] \| ToolFuncEither[...]] \| Unset` | `:1979` |
  | `native_tools` | `Sequence[AgentNativeTool[AgentDepsT]] \| Unset` | `:1980` |
  | `instructions` | `AgentInstructions[AgentDepsT] \| Unset` | `:1981` |
  | `metadata` | `AgentMetadata[AgentDepsT] \| Unset` | `:1982` |
  | `model_settings` | `AgentModelSettings[AgentDepsT] \| Unset` | `:1983` |
  | `retries` | `int \| AgentRetries \| Unset` | `:1984` |
  | `spec` | `dict[str, Any] \| AgentSpec \| None = None` | `:1985` |

  There is **no** `output_type=` and no `usage_limits=` on `override`. Each value goes into a `ContextVar` (`_override_*`, created at `:760-793`) and is reset in the `finally` (`:2131-2147`). `override(instructions=...)` **replaces everything**, capability-contributed instructions included (docstring `:2001-2003`; implementation `:3141-3149`).
- Dynamic instructions via `@agent.instructions` — decorator at `SP/pydantic_ai/agent/__init__.py:2175-2228`, overloads `:2155-2173`. Accepted shapes: `() -> str | None`, `() -> Awaitable[str | None]`, `(RunContext[AgentDepsT]) -> str | None`, `(RunContext[AgentDepsT]) -> Awaitable[str | None]`; bare or with `name=`. **The ctx/no-ctx choice is arity-based, not annotation-based**: `self._takes_ctx = len(inspect.signature(self.function).parameters) > 0` (`SP/pydantic_ai/_system_prompt.py:21-23`), and the call passes `(run_context,)` or `()` (`:25-37`). `deps` reaches the function as `ctx.deps`. Sync functions run in an executor and an awaitable result is awaited (`:35-37`). Resolution into `InstructionPart`s: `SP/pydantic_ai/_instructions.py:83-127`.
- Assembly order (`SP/pydantic_ai/agent/__init__.py:3128-3161`): an `override` replaces all; otherwise the agent's constructor literals, then the run-level `instructions=` (appended with `source=None`, `:3153-3159`), then the `@agent.instructions` functions, then capability instructions. Probes:

  ```
  --- instructions delivered to model (agent-level only) ---
  'Static agent instruction.\n\nzero-arg instruction\n\nctx instruction for deps=chris\n\nasync ctx deps=chris'
  --- with run-level instructions= ---
  'Static agent instruction.\n\nRUN-LEVEL extra instruction\n\nzero-arg instruction\n\nctx instruction for deps=chris\n\nasync ctx deps=chris'
  --- inside override(instructions=...) ---
  'OVERRIDE instruction'

  agent only      : 'A-literal\n\nB-dynamic'
  with run instr  : 'A-literal\n\nC-run\n\nB-dynamic'
  two run instrs  : 'A-literal\n\nC-run\n\nD-run\n\nB-dynamic'
  override        : 'OV'
  override+run    : 'OV'
  ```
  The assembled string also lands on `result.all_messages()[0].instructions`, which is the easy way to assert on it in a test.

### C3. `UsageLimits` and `UsageLimitExceeded`

- `SP/pydantic_ai/usage.py:445-446` — `@dataclass(repr=False, kw_only=True) class UsageLimits`. Fields (`:455-500`):

  | field | type | default | line |
  |---|---|---|---|
  | `cost_limit` | `Decimal \| None` | `None` | `:455` |
  | `request_limit` | `int \| None` | **`50`** | `:457` |
  | `tool_calls_limit` | `int \| None` | `None` | `:459` |
  | `input_tokens_limit` | `int \| None` | `None` | `:461` |
  | `output_tokens_limit` | `int \| None` | `None` | `:463` |
  | `total_tokens_limit` | `int \| None` | `None` | `:465` |
  | `per_request_input_tokens_limit` | `int \| None` | `None` | `:467` |
  | `count_tokens_before_request` | `bool` | `False` | `:487` |

  All six limits asked about exist, plus `per_request_input_tokens_limit`. **`request_limit` is the only one with a non-`None` default (50)** — every run already has a request ceiling. Helpers: `has_token_limits` (`:502`), `check_before_request` (`:520`), `check_cost` (`:544`), `check_tokens` (`:566`), `check_before_tool_call` (`:582`), `check_per_request_input_tokens` (`:591`).
- Exception: `UsageLimitExceeded` at `SP/pydantic_ai/exceptions.py:459-471`, subclassing `AgentRunError` (`:251-262`) → `RuntimeError`. Canonical path `pydantic_ai.exceptions.UsageLimitExceeded`, **also re-exported from `pydantic_ai`** (`SP/pydantic_ai/__init__.py:51`, `__all__` at `:237`); the two are the same object. `UsageLimits`, `RunUsage` and `RequestUsage` are re-exported too (`:188`, `:385-387`).
- **The exception does not carry the usage.** `UsageLimitExceeded.__init__` (`exceptions.py:467-471`) takes only `message` and appends a docs hint; `AgentRunError` stores just `self.message` (`:257-259`). Probe: `public attrs: ['add_note', 'args', 'message', 'with_traceback']`, `has .usage? False`. (By contrast `RunCancelled` *does* expose `.usage` — `exceptions.py:428-431`.)
- **Where the usage-so-far lives on an aborted run: only `agent.iter(...)`'s `AgentRun.usage`** (`SP/pydantic_ai/run.py:492-495`, returning `self._graph_run.state.usage`). `AgentRunResult` never comes into existence, so `run_sync` gives you nothing. If a budget guard needs to record how much was spent before the abort, the run has to go through `async with agent.iter(...) as run:`.
- Raise sites: `SP/pydantic_ai/usage.py:524, 528, 534, 540, 554, 570, 574, 580, 587, 599`, called from `SP/pydantic_ai/_agent_graph.py:924, 927, 1670, 1672, 1784, 1850, 1852, 1856`, `SP/pydantic_ai/_tool_execution.py:501`, `SP/pydantic_ai/result.py:1058-1059`.
- Probe (`c3_c4_probe.py`):

  ```
  pydantic_ai.UsageLimitExceeded is pydantic_ai.exceptions.UsageLimitExceeded: True
  MRO: ['UsageLimitExceeded', 'AgentRunError', 'RuntimeError', 'Exception', 'BaseException', 'object']
  repr : UsageLimitExceeded('The next request would exceed the request_limit of 1. Consider raising the
         limit, or see the docs on usage limits for budget-aware patterns: ...')
  public attrs: ['add_note', 'args', 'message', 'with_traceback']   has .usage? False
  tool_calls_limit=0 -> 'The next tool call(s) would exceed the tool_calls_limit of 0 (tool_calls=1). ...'
  === usage recoverable from agent.iter run context after abort ===
  run.usage: RunUsage(input_tokens=51, output_tokens=2, requests=1, tool_calls=1)
  run.result: None
  ```

### C4. `RunUsage`, `AgentRunResult.usage`, and cost

- **`AgentRunResult.usage` is a property, not a method** — `SP/pydantic_ai/run.py:752-755` (class at `:634-635`). `result.usage()` raises `TypeError: 'RunUsage' object is not callable`. The question's `RunResult.usage()` spelling is wrong for this version; use `result.usage`. Same for `AgentRun.usage` (`:492-495`).
- `RunUsage` — `SP/pydantic_ai/usage.py:341-342`, `@dataclass(repr=False, init=False, eq=False)`, subclassing `UsageBase` (`:83-84`):

  | field | type | default | line |
  |---|---|---|---|
  | `input_tokens` | `int` | `0` | `:354` (base `:90-94`) |
  | `cache_write_tokens` | `int` | `0` | `:357` (base `:102`) |
  | `cache_read_tokens` | `int` | `0` | `:360` (base `:104`) |
  | `input_audio_tokens` | `int` | `0` | `:363` (base `:117`) |
  | `cache_audio_read_tokens` | `int` | `0` | `:366` (base `:119`) |
  | `output_tokens` | `int` | `0` | `:369` (base `:110-114`) |
  | `output_audio_tokens` | `int` | `0` | base `:121` |
  | `details` | `dict[str, int]` | `{}` | `:372` (base `:125-130`) |
  | `cost` | `Decimal \| None` | `None` | base `:131-137` |
  | `requests` | `int` | `0` | `:348` |
  | `tool_calls` | `int` | `0` | `:351` |

  `total_tokens` is a **property** = `input_tokens + output_tokens` (`:200-203`). Also `cache_hit_ratio` (`:205-218`), `opentelemetry_attributes()` (`:220-256`), `has_values()` (`:268-270`), `incr` / `__add__` / `__sub__` (`:375-419`).
- **There is no `RunUsage.cost()` method.** `cost` is a plain `Decimal | None` attribute (`usage.py:131`), documented "Best-effort cost in USD, or `None` if no cost could be determined. Calculated with genai-prices. `None` (rather than zero) when the model or provider can't be priced." The only `cost()` **method** is `ModelResponse.cost()` (`SP/pydantic_ai/messages.py:2871-2883`), which returns a genai-prices `PriceCalculation` and **propagates `LookupError`**.
- Pricing path: `fill_response_cost` (`SP/pydantic_ai/_genai_prices.py:155-175`) sets `response.usage.cost = price.total_price` when unset, via `best_effort_price` (`:119-152`), which swallows `LookupError`/`ValueError` into `None` and warns `CostCalculationFailedWarning` for anything else. Lookup tries `provider_api_url` first, then `provider_id` (`:99-116`). Called from `_agent_graph.py:938, 1048, 1057, 1058, 1121, 1364, 1847` and `models/fallback.py:297, 304`; accumulated by `_incr_usage_cost` (`usage.py:421-424`).
- **OpenRouter models are priceable when genai-prices knows the model id, and silently `None` when it does not** — never an exception inside a run. Probes:

  ```
  # c3_c4_probe.py (TestModel)
  RunUsage has cost() method? False        RunUsage.cost is a dataclass field? True
  AgentRunResult.usage is a property (not a method): True
  result.usage repr: RunUsage(input_tokens=51, output_tokens=4, requests=1)
    requests=1  input_tokens=51  output_tokens=4  total_tokens=55  tool_calls=0  details={}  cost=None
  calling u.cost() raises: TypeError: 'NoneType' object is not callable
  calling r.usage() raises: TypeError: 'RunUsage' object is not callable
  ModelResponse.cost() on the TestModel response raises: LookupError: Unable to find provider provider_id='test'

  # c4b_probe.py (genai_prices 0.1.6, no network)
  calc 'anthropic/claude-sonnet-5'   -> total_price=0.007
  calc 'anthropic/claude-sonnet-4-5' -> LookupError: Unable to find model with
       model_ref='anthropic/claude-sonnet-4-5' in openrouter
  fill_response_cost -> resp.usage.cost = Decimal('0.007')
  RunUsage after incr: RunUsage(cost=Decimal('0.007'), input_tokens=1000, output_tokens=500)
  ```
  So a per-run USD budget can read `result.usage.cost`, but must treat `None` as "unpriceable" rather than "free" — and the model id has to be one genai-prices carries.

### C5. `FunctionModel` and `TestModel`

- `FunctionModel` — `SP/pydantic_ai/models/function.py:50-51`, `@dataclass(init=False)`; real `__init__` at `:100-107` (overloads `:70-98`), docstring `:108-119`:

  ```python
  FunctionModel(function: FunctionDef | None = None, *, stream_function: StreamFunctionDef | None = None,
                model_name: str | None = None, profile: ModelProfileSpec | None = None,
                settings: ModelSettings | None = None)
  ```
  Raises `TypeError('Either `function` or `stream_function` must be provided')` when both are `None` (`:120-121`); the default `model_name` is `f'function:{function_name}:{stream_function_name}'` (`:131`).
- The function's shape — `FunctionDef` at `SP/pydantic_ai/models/function.py:314`:

  ```python
  FunctionDef: TypeAlias = Callable[[list[ModelMessage], AgentInfo], ModelResponse | Awaitable[ModelResponse]]
  ```
  It receives `(messages, info)` and must return a `ModelResponse`; a sync callable is run in a worker thread (`:315-319`). `AgentInfo` is `@dataclass(frozen=True, kw_only=True)` at `:248-270` with `function_tools: list[ToolDefinition]` (`:255`), `allow_text_output: bool` (`:261`), `output_tools: list[ToolDefinition]` (`:263`), `model_settings` (`:265`), `model_request_parameters` (`:267`), `instructions: str | None` (`:269`). The streaming variant is `StreamFunctionDef` (`:321-323`) with `DeltaToolCall` (`:274-289`) and `DeltaThinkingPart` (`:291-303`).
- The structured-output tool name is `DEFAULT_OUTPUT_TOOL_NAME = 'final_result'` (`SP/pydantic_ai/_output.py:71`, applied at `:1423` as `default_name = name or DEFAULT_OUTPUT_TOOL_NAME`; also `ToolOutput.name` docs at `SP/pydantic_ai/output.py:114`). In a `FunctionModel` prefer reading `info.output_tools[0].name` over hardcoding it.
- `TestModel` — `SP/pydantic_ai/models/test.py:61-62`, `@dataclass(init=False)`, fields `:83-99`, explicit `__init__` `:101-118`:

  ```python
  TestModel(*, call_tools: list[str] | Literal['all'] = 'all', custom_output_text: str | None = None,
            custom_output_args: Any | None = None, seed: int = 0, model_name: str = 'test',
            profile: ModelProfileSpec | None = None, settings: ModelSettings | None = None)
  ```
  `call_tools='all'` means it calls **every** registered tool with synthesised arguments — the reason the harness smoke test in §A4 needed `call_tools=[]`. `custom_output_text` "is returned as the final output" (`:85-86`); `custom_output_args` "will be passed to the output tool" (`:87-88`). `last_model_request_parameters` (`:91-97`, `init=False`) records the last `ModelRequestParameters` and is set in `request` (`:129`) and `request_stream` (`:145`) — that is how §A4 listed the tool names the model actually saw.
- Working probe (`c5_probe.py`), all three shapes:

  ```python
  class City(BaseModel):
      name: str
      country: str

  # 1. structured output from TestModel
  agent1 = Agent(TestModel(custom_output_args={'name': 'Paris', 'country': 'France'}), output_type=City)
  r1 = agent1.run_sync('capital of france?')

  # 2. structured output from FunctionModel via the output tool call
  def structured(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
      tool_name = info.output_tools[0].name           # 'final_result'
      return ModelResponse(parts=[ToolCallPart(tool_name, {'name': 'Berlin', 'country': 'Germany'})])
  agent2 = Agent(FunctionModel(structured), output_type=City)
  r2 = agent2.run_sync('capital of germany?')

  # 3. plain text, no output_type
  def plain(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
      return ModelResponse(parts=[TextPart('just some text')])
  r3 = Agent(FunctionModel(plain)).run_sync('anything')
  ```
  ```
  1) TestModel(custom_output_args=...) -> City(name='Paris', country='France')
  2) FunctionModel + ToolCallPart    -> City(name='Berlin', country='Germany')
     AgentInfo.output_tools names : ['final_result']
     AgentInfo.function_tools     : []
     AgentInfo.allow_text_output  : False
     AgentInfo.instructions       : 'be terse'
  3) FunctionModel plain text        -> 'just some text'
  4) TestModel(custom_output_text=)  -> 'hi from TestModel'
  ```

### C6. `infer_model` and the OpenRouter API key

- Import path is `pydantic_ai.models.infer_model`, defined at `SP/pydantic_ai/models/__init__.py:1581-1583`. It is **not** exported from the top-level `pydantic_ai` package (probe: `pydantic_ai.infer_model exists (top level): False`). Signature:

  ```python
  infer_model(model: Model | KnownModelName | str,
              provider_factory: Callable[[str], Provider[Any]] = infer_provider) -> Model
  ```
- Flow: a `Model` instance passes through (`:1592-1593`); `'test'` becomes `TestModel()` (`:1594-1597`); otherwise `parse_model_id` (`:1599`), an unknown prefix raises `UserError(f'Unknown model: {model}')` with a "Did you mean" suggestion (`:1600-1613`), and then **`provider = provider_factory(provider_name)` constructs the provider eagerly** (`:1615`). `openrouter` routes to `OpenRouterModel` (`:1637-1640`).
- **Yes, the API key is required at construction time.** `OpenRouterProvider.__init__` (`SP/pydantic_ai/providers/openrouter.py:236-280`) does `api_key = api_key or os.getenv('OPENROUTER_API_KEY')` (`:263`) and raises `UserError` at `:264-268` when there is neither a key nor an `openai_client`. The key check runs **before** model-name validation, so even a malformed model id reports the missing key first.
- Probe, run with `env -u OPENROUTER_API_KEY` and no `.env` loading (`c6_probe.py`; independently reproduced):

  ```
  OPENROUTER_API_KEY set in env? False
  'openrouter:anthropic/claude-sonnet-5'  -> pydantic_ai.exceptions.UserError: Set the `OPENROUTER_API_KEY`
      environment variable or pass it via `OpenRouterProvider(api_key=...)` to use the OpenRouter provider.
  'bogusprovider:some-model'              -> UserError: Unknown model: bogusprovider:some-model
  'test'                                  -> OK pydantic_ai.models.test.TestModel model_name='test' system='test'
  'anthropic/claude-sonnet-5'             -> UserError: Unknown model: anthropic/claude-sonnet-5.
                                             Did you mean 'anthropic:claude-sonnet-5'?
  'openrouter:noslash'                    -> UserError: Set the `OPENROUTER_API_KEY` ... (key checked first)
  ```
  With a dummy key present (`c6b_probe.py`, still no network call): `openrouter:anthropic/claude-sonnet-5 -> pydantic_ai.models.openrouter.OpenRouterModel, model_name='anthropic/claude-sonnet-5', system='openrouter', base_url='https://openrouter.ai/api/v1/'`.
- Escape hatch for constructing an Agent without a key: `Agent('openrouter:...', defer_model_check=True)` skips `infer_model` at construction (`SP/pydantic_ai/agent/__init__.py:815-816`) — the key is then only needed at the first run.

### C7. `Agent.override` accepted keywords

Listed exhaustively in §C2 above (`SP/pydantic_ai/agent/__init__.py:1971-1986`): `name`, `deps`, `model`, `toolsets`, `tools`, `native_tools`, `instructions`, `metadata`, `model_settings`, `retries`, `spec`. All keyword-only; all but `spec` sentinel-defaulted to `_utils.UNSET`. No `output_type`, no `usage_limits`.

### C8. Span names and how a validation retry shows up

The question's premise is out of date for 2.40: **`SP/pydantic_ai/_agent_graph.py` opens no spans at all** (no `start_as_current_span` in it), and `SP/pydantic_ai/models/instrumented.py` now only holds `InstrumentationSettings` (`:63`) and the `InstrumentedModel` wrapper (`:339-408`). The name/attribute table lives in `SP/pydantic_ai/_instrumentation.py`, and the agent-run and tool spans are opened by `SP/pydantic_ai/capabilities/instrumentation.py`.

- Default instrumentation version is **5**: `DEFAULT_INSTRUMENTATION_VERSION = 5` (`SP/pydantic_ai/_instrumentation.py:33`); `InstrumentedModel` accepts `version: Literal[2, 3, 4, 5, 6]` (`SP/pydantic_ai/models/instrumented.py:79, :90`). `InstrumentationConfig.for_version` (`_instrumentation.py:716-743`) picks between two naming schemes:

  | | version 2 | version 3+ (default) |
  |---|---|---|
  | agent run span | `'agent run'` | `'invoke_agent'` → `f'invoke_agent {agent_name}'` |
  | agent name attr | `agent_name` | `gen_ai.agent.name` |
  | tool span | `'running tool'` | `'execute_tool'` → `f'execute_tool {tool_name}'` |
  | tool args attr | `tool_arguments` | `gen_ai.tool.call.arguments` |
  | tool result attr | `tool_response` | `gen_ai.tool.call.result` |
  | output-fn span | `'running output function'` | `f'execute_tool {tool_name}'` |

  (`:726-743`, formatting helpers at `:745-756`, `:758-769`, `:771-782`.) So **`running tool` is a version-2 name only**; under the default version 5 the tool span is `execute_tool {tool_name}` and `running tool: {tool_name}` survives only as the `logfire.msg` attribute.

- Span names actually emitted:

  | span | format | source |
  |---|---|---|
  | model request | `chat {model_name}` (`operation = 'chat'`) | `_instrumentation.py:500-501`, opened `:521` with `kind=SpanKind.CLIENT`, renamed on finish at `:563`; attributes seeded `{'gen_ai.operation.name': 'chat'}` at `:320` |
  | agent run | `invoke_agent {agent_name}` | `_instrumentation.py:737, 745-756`; opened `capabilities/instrumentation.py:211-214` |
  | tool execution | `execute_tool {tool_name}` | `_instrumentation.py:739, 758-769`; opened `capabilities/instrumentation.py:543` via `_run_tool_span` (`:472-476`) |
  | output function | `execute_tool {tool_name}` | `_instrumentation.py:742, 771-782`; opened `capabilities/instrumentation.py:613` |
  | failed argument validation | same `execute_tool {tool_name}` name, `logfire.msg = f'invalid tool call: {tool_name}'` | `capabilities/instrumentation.py:381-388` |
  | concurrency wait | `f'waiting for {display_name} concurrency'` | `SP/pydantic_ai/concurrency.py:238-239` |

- Attributes that name a tool call — `_tool_span_attributes` (`SP/pydantic_ai/capabilities/instrumentation.py:411-444`): `gen_ai.operation.name='execute_tool'` (`:421`), **`gen_ai.tool.name`** (`:422`), **`gen_ai.tool.call.id`** (`:423`), `gen_ai.tool.call.arguments` (`:424`, content capture only), `gen_ai.tool.call.result` (set on success at `:517-521`), `logfire.msg = f'running tool: {tool_name}'` (`:426`), plus the run baggage `gen_ai.agent.name` / `gen_ai.agent.call.id` / `gen_ai.conversation.id` (`:196-199, 215-219`, injected at `:425`). Tool *definitions* appear on the chat span as `gen_ai.tool.definitions` (`_instrumentation.py:513-515`).

- **Detecting a retry.** Three paths, and they do not all produce a span:
  1. **A tool raises `ModelRetry`** → wrapped as `ToolRetryError` and caught at `capabilities/instrumentation.py:500-507`: `gen_ai.tool.call.result = e.tool_retry.model_response()` (`:504`), `span.record_exception(e, escaped=True)` (`:505`), `span.set_status(StatusCode.ERROR)` (`:506`). The tool span **is** ERROR. No `failure_stage` attribute — the constant's comment says it is "Set on tool spans for calls that failed before execution; absent on execution failures" (`_instrumentation.py:713-714`).
  2. **Function-tool argument validation fails** → `on_tool_validate_error` (`capabilities/instrumentation.py:353-409`) emits an `execute_tool {tool_name}` span with **`pydantic_ai.tool.failure_stage = 'validation'`** (`:382`; constant `tool_failure_stage_attr` at `_instrumentation.py:710-714`), `logfire.msg = f'invalid tool call: {tool_name}'` (`:381`), the retry prompt as `gen_ai.tool.call.result` (`:390-391`), `record_exception` (`:392`) and `StatusCode.ERROR` (`:408`). Its docstring notes it "Runs only after every other capability has declined to recover the error, so a recovered validation failure produces no span."
  3. **Output-tool (`final_result`) schema failure, or an `@agent.output_validator` raising `ModelRetry`** → **no span at all**. The only trace is a second `chat` span whose `gen_ai.input.messages` carries the retry. If `output_type` is a *function* that raises `ModelRetry`, `wrap_output_process` (`:556-639`) does emit an `execute_tool final_result` span with status ERROR and an `exception` event of type `pydantic_ai.exceptions.ModelRetry` (catch-all at `:511-517`).
- **In the message stream a retry is not distinguishable by type.** `RetryPromptPart` (`SP/pydantic_ai/messages.py:1693-1798`) renders through `otel_message_parts` (`:1779-1796`) as a `{'type': 'tool_call_response', 'id': ..., 'name': ...}` part — plus `'result'` under content capture — i.e. **the same shape as a successful `ToolReturnPart`** (`:1608-1610`). Only when `tool_name is None` (native-output / plain validation feedback) does it become a `{'type': 'text'}` part. The distinguishing signal is the text itself: `model_response()` (`:1755-1777`) always ends with `"\n\nFix the errors and try again."`, and the no-tool-name form is prefixed `"Validation feedback:"` (`:1759`). The part's role in `gen_ai.input.messages` is `'user'` up to version 5 and `'tool'` from version 6 (`models/instrumented.py:410-437`, esp. `:431-437`).
- Retry budget: `GraphAgentState.consume_output_retry` (`_agent_graph.py:363-381`) raises `UnexpectedModelBehavior(f'Exceeded maximum output retries ({max_output_retries})')` at `:377-380`.
- Agent-run span end attributes (`capabilities/instrumentation.py:264-290`): `pydantic_ai.all_messages` (`:276-278` — the full OTel-rendered history, the best place to count retry parts), `gen_ai.system_instructions` (`:279`), `pydantic_ai.new_message_index` (`:283`), `pydantic_ai.variable_instructions` (`:286`), `metadata` (`:289`), plus `gen_ai.aggregated_usage.*` (`models/instrumented.py:299-311`) and `final_result` (`:230-238`).
- Probes. Note `logfire.configure(local=True, ...)` **does not work** for this: it builds a non-global instance, so `logfire.instrument_pydantic_ai()` warns `LogfireNotConfiguredWarning` and captures nothing. Use `logfire.configure(send_to_logfire=False, console=False, additional_span_processors=[SimpleSpanProcessor(InMemorySpanExporter())])` without `local=True`.

  `c8_probe.py` — a tool raises `ModelRetry`, then the model returns text:

  ```
  === 4 spans ===
  SPAN chat function:fn:        kind=CLIENT   status=UNSET
    attrs: gen_ai.agent.call.id, gen_ai.agent.name, gen_ai.conversation.id, gen_ai.input.messages,
           gen_ai.operation.name, gen_ai.output.messages, gen_ai.provider.name, gen_ai.request.model,
           gen_ai.response.model, gen_ai.system, gen_ai.tool.definitions, gen_ai.usage.input_tokens,
           gen_ai.usage.output_tokens, logfire.json_schema, logfire.msg, logfire.span_type,
           model_request_parameters
  SPAN execute_tool flaky       kind=INTERNAL status=ERROR
    gen_ai.tool.name = 'flaky'
    gen_ai.tool.call.id = 'pyd_ai_0672f85566bb43aab088c7182649872a'
    gen_ai.tool.call.result = 'please try again with x=2\n\nFix the errors and try again.'
    gen_ai.tool.call.arguments = '{"x":1}'
    logfire.msg = 'running tool: flaky'
    EVENT: exception pydantic_ai.exceptions.ToolRetryError 'please try again with x=2' escaped=True
  SPAN chat function:fn:        status=UNSET
  SPAN invoke_agent probe_agent status=UNSET
    attrs: agent_name, final_result, gen_ai.agent.call.id, gen_ai.agent.name,
           gen_ai.aggregated_usage.input_tokens, gen_ai.aggregated_usage.output_tokens,
           gen_ai.conversation.id, gen_ai.operation.name, logfire.json_schema, logfire.metrics,
           logfire.msg ('probe_agent run'), logfire.span_type, model_name, pydantic_ai.all_messages
  ```
  The second `chat` span's `gen_ai.input.messages`:

  ```json
  [{"role": "user", "parts": [{"type": "text", "content": "go"}]},
   {"role": "assistant", "parts": [{"type": "tool_call", "id": "pyd_ai_0672f8…", "name": "flaky",
                                    "arguments": {"x": 1}}]},
   {"role": "user", "parts": [{"type": "tool_call_response", "id": "pyd_ai_0672f8…", "name": "flaky",
      "result": "please try again with x=2\n\nFix the errors and try again."}]}]
  ```
  `c8b_probe.py` / `c8c_probe.py` — output-tool argument validation and an `@agent.output_validator` raising `ModelRetry` produce **no tool span and no ERROR status anywhere**, only an extra `chat` span:

  ```
  ######## A: output-tool ARG VALIDATION retry ########
    chat function:bad_then_good:  status=UNSET  failure_stage=None
    chat function:bad_then_good:  status=UNSET  failure_stage=None
    invoke_agent argval           status=UNSET  failure_stage=None
  ######## B: OUTPUT VALIDATOR ModelRetry ########
    chat function:two:            status=UNSET  failure_stage=None
    chat function:two:            status=UNSET  failure_stage=None
    invoke_agent outval           status=UNSET  failure_stage=None
  ```
  with the retry visible only in the messages:

  ```json
  {"role": "user", "parts": [{"type": "tool_call_response", "id": "pyd_ai_70b892…", "name": "final_result",
    "result": "1 validation error:\n```json\n[{\"type\": \"int_parsing\", \"loc\": [\"population\"],
      \"msg\": \"Input should be a valid integer, unable to parse string as an integer\",
      \"input\": \"nope\"}]\n```\n\nFix the errors and try again."}]}
  ```
  A **function-tool** argument-validation retry, by contrast, is marked:

  ```
    chat function:badtool: | status=UNSET | failure_stage=None
    execute_tool add       | status=ERROR | failure_stage=validation
    chat function:badtool: | status=UNSET | failure_stage=None
    invoke_agent fnargval  | status=UNSET | failure_stage=None
  ```
  and `c8d_probe.py` (an `output_type` function raising `ModelRetry`):

  ```
    chat function:m:          status=UNSET  op=chat
    execute_tool final_result status=ERROR  op=execute_tool tool=final_result
                              msg='running output function: final_result'
        EVENT exception pydantic_ai.exceptions.ModelRetry
    chat function:m:          status=UNSET  op=chat
    execute_tool final_result status=UNSET  result='got 42'
    invoke_agent outfn        status=UNSET  msg='outfn run'
  ```
- **Practical rule.** To count "validation retries" from spans: `execute_tool` spans with `StatusCode.ERROR` cover in-tool `ModelRetry` and bad tool arguments (the latter additionally carrying `pydantic_ai.tool.failure_stage == 'validation'`). Pure output-schema and output-validator retries emit no span, so they have to be counted from messages: parse `pydantic_ai.all_messages` on the `invoke_agent` span (or `gen_ai.input.messages` on the later `chat` span) for a `tool_call_response` part whose `result` ends with `Fix the errors and try again.` A cruder proxy is "more than one `chat` span per `invoke_agent` with no successful tool call in between".
