# ty / ruff / pydantic-ai / pytest configuration facts (2026-09-05)

Research against primary sources only: the astral-sh docs and repos, the PyPI JSON API, the pydantic-ai docs and the installed package source, and the pytest docs/changelog. Summary: ty's latest release is 0.0.78 (PyPI upload 2026-09-02); its docs at the `0.0.78` tag are byte-identical to `main` for the configuration and rules references, so every ty citation below applies to the released version. The Python version is set with `[tool.ty.environment] python-version = "3.12"`; checked paths are scoped with `[tool.ty.src] include = ["src", "tests"]`; there is no `src.root` any more (removed in 0.0.67, superseded by `environment.root`, which auto-detects `./src`). Rule severities live in `[tool.ty.rules]` with values `error`/`warn`/`ignore`. Since ty 0.0.52 warnings DO fail the run by default (`terminal.error-on-warning` defaults to `true`); to report warnings without failing, set `[tool.ty.terminal] error-on-warning = false`. One ty guide page still carries stale text claiming the opposite default; the reference, exit-code page, and changelog agree on the new default. ruff 0.16.6 (installed and latest) keeps `select` under `[tool.ruff.lint]` and `line-length`/`target-version` under `[tool.ruff]`; none of the formatter-conflicting rules are in RUF or SIM, but E111/E114/E117 are, so ignore them. Since ruff 0.16.0, `*.md` is in the default `include` and Python code blocks in Markdown are formatted by default; the documented off-switch is `[tool.ruff] extend-exclude = ["*.md"]`. `pydantic_ai.models.ALLOW_MODEL_REQUESTS` is a module-level bool (default `True`) that the docs tell you to set to `False` globally in tests. pytest 9.x supports both `[tool.pytest]` (native TOML, since 9.0) and `[tool.pytest.ini_options]` (since 6.0); neither is deprecated, but they cannot be combined.

Environment facts observed locally (all read-only):

- Installed: ruff 0.16.6, pytest 9.1.1, pydantic-ai-slim 2.40.0, pydantic-ai-harness 0.29.0, Python 3.12 (`.python-version`). ty is NOT installed in `.venv` (no `.venv/bin/ty`); the dev group currently lists `pyright`, so `uv run ty check` needs `ty` added to `[dependency-groups].dev` first. Source: `/Users/chris/Developer/recursive_application/pyproject.toml`, `.venv/lib/python3.12/site-packages/*.dist-info`, accessed 2026-09-05.

## 1. ty (Astral type checker), latest 0.0.x

### 1e. Latest version and release date (answered first because everything else hangs on it)

- PyPI `info.version` for `ty` is `0.0.78`; it is also the newest release overall (no `0.1.x` exists). First file upload time: `2026-09-02T22:40:56Z`. Preceding releases: 0.0.77 (2026-09-01T00:25Z), 0.0.76 (2026-08-31T15:55Z), 0.0.75 (2026-08-26). The spec's claim "0.0.78 as of 2026-09-05" is CONFIRMED. Source: https://pypi.org/pypi/ty/json, accessed 2026-09-05.
- ty CHANGELOG top entry: `## 0.0.78` / `Released on 2026-09-02.` Source: https://github.com/astral-sh/ty/blob/main/CHANGELOG.md, accessed 2026-09-05.
- `docs/reference/configuration.md` and `docs/reference/rules.md` at the `0.0.78` git tag are identical to `main` (`diff` produced no output), so the docs cited below describe 0.0.78 exactly. Source: https://raw.githubusercontent.com/astral-sh/ty/0.0.78/docs/reference/configuration.md vs https://raw.githubusercontent.com/astral-sh/ty/main/docs/reference/configuration.md (and the same for `rules.md`), accessed 2026-09-05.

### 1a. Target Python version

- Key: `[tool.ty.environment] python-version = "3.12"` (in `ty.toml`: `[environment] python-version = "3.12"`). Doc text: "Specifies the version of Python that will be used to analyze the source code. The version should be specified as a string in the format `M.m` ... (e.g. `"3.7"` or `"3.12"`)." Type: `"3.7" | "3.8" | "3.9" | "3.10" | "3.11" | "3.12" | "3.13" | "3.14" | "3.15"`. Default value: `"3.14"`. Source: https://docs.astral.sh/ty/reference/configuration/#python-version, accessed 2026-09-05.
- Inference when unset: "1. Check for the `project.requires-python` setting in a `pyproject.toml` file and use the minimum version from the specified range 2. Check for an activated or configured Python environment and attempt to infer the Python version of that environment 3. Fall back to the default value". This project has `requires-python = ">=3.12"`, so ty would infer 3.12 even without the key; setting it explicitly is still the deterministic choice. Source: https://docs.astral.sh/ty/reference/configuration/#python-version, accessed 2026-09-05.
- "ty officially supports type checking code that targets Python 3.10 and later." Source: same page, accessed 2026-09-05.
- CLI equivalent: `--python-version` / `--target-version <version>`. Source: https://docs.astral.sh/ty/reference/cli/#ty-check--python-version, accessed 2026-09-05.

### 1b. Restricting what `ty check` checks

- Table is `[tool.ty.src]` with these keys (the full list of `src` keys in the reference): `exclude`, `exclude-scripts`, `include`, `respect-ignore-files`. There is NO `root` key under `src` in 0.0.78. Source: https://docs.astral.sh/ty/reference/configuration/#src, accessed 2026-09-05.
- `src.include`: "A list of files and directories to check. The `include` option follows a similar syntax to `.gitignore` but reversed: Including a file or directory will make it so that it (and its contents) are type checked." Pattern rules: "`./src/` matches only a directory; `./src` matches both files and directories; `src` matches a file or directory named `src`; `*` ...; `**` ...". "All paths are anchored relative to the project root (`src` only matches `<project_root>/src` and not `<project_root>/test/src`)." "`exclude` takes precedence over `include`." Default `null`, type `list[str]`. Example in the docs is literally `include = ["src", "tests"]`. Source: https://docs.astral.sh/ty/reference/configuration/#include_1, accessed 2026-09-05.
- `src.exclude`: same gitignore-like syntax plus `!pattern` negation; default `null`, but ty always applies a built-in exclude list (`**/.git/`, `**/.venv/`, `**/venv/`, `**/.ruff_cache/`, `**/.mypy_cache/`, `**/dist/`, `**/node_modules/`, ...); "You can override any default exclude by using a negated pattern. For example, to re-include `dist` use `exclude = ["!dist"]`". Source: https://docs.astral.sh/ty/reference/configuration/#exclude_1, accessed 2026-09-05.
- `src.respect-ignore-files`: "Whether to automatically exclude files that are ignored by `.ignore`, `.gitignore`, `.git/info/exclude`, and global `gitignore` files. Enabled by default." Default `true`. Source: https://docs.astral.sh/ty/reference/configuration/#respect-ignore-files, accessed 2026-09-05.
- `src.root` history: renamed to `environment.root` in `0.0.1-alpha.12` ("Rename `src.root` setting to `environment.root` (#18760)"); the deprecated alias was removed in `0.0.67` (released 2026-08-05): "Remove deprecated `src.root` setting in favor of `environment.root` (#27456)". Writing `[tool.ty.src] root = ...` against 0.0.78 is therefore not a supported key. Source: https://github.com/astral-sh/ty/blob/main/CHANGELOG.md (sections 0.0.67 and 0.0.1-alpha.12), accessed 2026-09-05.
- Positional paths: usage is `ty check [OPTIONS] [PATH]...`; argument doc: "PATHS: List of files or directories to check [default: the project root]". So yes, `ty check src tests` is accepted. Source: https://docs.astral.sh/ty/reference/cli/#ty-check, accessed 2026-09-05.
- Interaction between positional paths and `src.include`/`src.exclude`: the docs do not state it. The implementation comment in `ty_project` says `is_file_included` "only checks the project's include and exclude settings as well as the paths that were passed to `ty check <paths>`", and `included_paths_or_root` falls back to the project root when no paths are given, i.e. both filters apply together (a file must be under a passed path AND pass include/exclude). Exact precedence (whether an explicitly passed file can override `exclude`) is UNVERIFIED from docs. Source: https://github.com/astral-sh/ruff/blob/main/crates/ty_project/src/lib.rs (`is_file_included`, `included_paths_or_root`), accessed 2026-09-05.
- CLI equivalents exist for exclusion: `--exclude <glob>` ("Glob patterns for files to exclude from type checking. Uses gitignore-style syntax") and `--respect-ignore-files` / `--no-respect-ignore-files`. Source: https://docs.astral.sh/ty/reference/cli/#ty-check--exclude, accessed 2026-09-05.

### 1c. Virtual environment discovery

- Reference text for `environment.python`: "ty uses the `site-packages` directory of your project's Python environment to resolve third-party (and, in some cases, first-party) imports in your code. This can be a path to: A Python interpreter, e.g. `.venv/bin/python3`; A virtual environment directory, e.g. `.venv`; A system Python `sys.prefix` directory, e.g. `/usr`". Default `null`. Source: https://docs.astral.sh/ty/reference/configuration/#python, accessed 2026-09-05.
- Discovery order, verbatim: "If you're using a project management tool such as uv, you should not generally need to specify this option, as commands such as `uv run` will set the `VIRTUAL_ENV` environment variable to point to your project's virtual environment. ty can also infer the location of your environment from an activated Conda environment, and will look for a `.venv` directory in the project root if none of the above apply. Failing that, ty will look for a `python3` or `python` binary available in `PATH`." Source: https://docs.astral.sh/ty/reference/configuration/#python, accessed 2026-09-05.
- Module-discovery guide, verbatim: "First, ty checks for an active virtual environment using the `VIRTUAL_ENV` environment variable. If not set, ty will search for a `.venv` directory in the project root or working directory. ty only supports discovery of virtual environments at this time." and "When using project management tools, such as uv or Poetry, the `run` command usually automatically activates the virtual environment and will be detected by ty." Explicit override: "`environment.python` setting or `--python` flag". Source: https://docs.astral.sh/ty/modules/#python-environment, accessed 2026-09-05.
- CLI: `--python` / `--venv <path>`; `--project <dir>`: "All `pyproject.toml` files will be discovered by walking up the directory tree from the given project directory, as will the project's virtual environment (`.venv`)". Source: https://docs.astral.sh/ty/reference/cli/#ty-check--python and `#ty-check--project`, accessed 2026-09-05.
- Conclusion: `uv run ty check` needs no `environment.python` setting; `uv run` sets `VIRTUAL_ENV`, and even a bare `ty check` from the repo root finds `./.venv`. `PYTHONPATH` entries are also added "just after any `extra-paths` and before the environment's `site-packages`". Source: https://docs.astral.sh/ty/modules/#pythonpath, accessed 2026-09-05.

### 1d. Rule severities, exit codes, warnings

- Table: `[tool.ty.rules]` (in `ty.toml`: `[rules]`). Type: `dict[RuleName | "all", "ignore" | "warn" | "error"]`. "Valid severities are: `ignore`: Disable the rule. `warn`: Enable the rule and create a warning diagnostic. `error`: Enable the rule and create an error diagnostic." The special key `all` sets every rule (e.g. `all = "error"`). Source: https://docs.astral.sh/ty/reference/configuration/#rules, accessed 2026-09-05.
- Default exit behaviour, verbatim from the rules reference intro: "By default, ty exits with code 1 if it emits any warning or error diagnostics. Set `terminal.error-on-warning` to `false` to exit with code 0 if all diagnostics have `warning` severity." Source: https://docs.astral.sh/ty/reference/configuration/#rules, accessed 2026-09-05.
- `terminal.error-on-warning` exists: "Use exit code 1, even if all diagnostics only had `warning` severity. Defaults to `true`." Default value `true`, type `bool`. Example: `[tool.ty.terminal]` / `error-on-warning = false` with comment "Exit with code 0 if all diagnostics had `warning` severity." Source: https://docs.astral.sh/ty/reference/configuration/#error-on-warning, accessed 2026-09-05.
- When the default flipped: ty `0.0.52` (released 2026-06-22): "Make `error-on-warning` the default (#26157)". Source: https://github.com/astral-sh/ty/blob/main/CHANGELOG.md, accessed 2026-09-05.
- Exit codes table: `0` "no violations with severity `warning` or higher were found"; `1` "violations with severity `warning` or higher were found"; `2` "invalid CLI options, invalid configuration, or IO errors"; `101` "internal error". Flags: "`--exit-zero`: ty will exit with `0` even if violations were found. `--error-on-warning`: ty will exit with `1` if it finds any violations with severity `warning` or higher. `--exit-zero-on-warning`: ty will only exit with `1` if it finds violations with severity `error` or higher. `--error-on-warning` cannot be supplied at the same time as `--exit-zero` or `--exit-zero-on-warning`." Source: https://docs.astral.sh/ty/reference/exit-codes/, accessed 2026-09-05.
- CLI reference wording: `--error-on-warning` "Use exit code 1 if there are any warning-level diagnostics."; `--exit-zero` "Always use exit code 0, even when there are error-level diagnostics."; `--exit-zero-on-warning` "Use exit code 0 if there are no error-level diagnostics."; `--error/--warn/--ignore <rule>` "Treat the given rule as having severity '...'. Can be specified multiple times. Use 'all' to apply to all rules." Source: https://docs.astral.sh/ty/reference/cli/#ty-check--error-on-warning (and neighbouring anchors), accessed 2026-09-05.
- Docs inconsistency to be aware of: the narrative rules guide still says "`warn`: ... ty exits with an exit code of 0 if there are only warning violations (default) or 1 when using `--error-on-warning`." That sentence predates 0.0.52 and contradicts the reference, the exit-code table (which has no warnings-only-is-0 row), the existence of `--exit-zero-on-warning`, and the changelog. Treat the reference + changelog as authoritative. Source: https://docs.astral.sh/ty/rules/ (line "`warn`: violations are reported as warnings..."), accessed 2026-09-05.
- Default severities (rules reference, 131 rules total: 94 `error`, 23 `warn`, 14 `ignore`): `unresolved-import` error; `unresolved-attribute` error; `unresolved-reference` error; `invalid-assignment` error; `invalid-argument-type` error; `invalid-return-type` error; `call-non-callable` error; `missing-argument` error; `unknown-argument` error; `too-many-positional-arguments` error; `no-matching-overload` error; `not-iterable` error; `unsupported-operator` error; `invalid-type-form` error; `index-out-of-bounds` error; `unused-ignore-comment` warn; `unused-type-ignore-comment` warn; `invalid-ignore-comment` warn; `redundant-cast` warn; `deprecated` warn; `undefined-reveal` warn; `unsupported-base` warn; `possibly-unresolved-reference` ignore; `possibly-missing-attribute` ignore; `possibly-missing-import` ignore; `division-by-zero` ignore. Rules named `possibly-unbound-attribute`, `possibly-unbound-import`, `unknown-rule` do not exist on the page (the first two are named `possibly-missing-attribute` / `possibly-missing-import`). Source: https://docs.astral.sh/ty/reference/rules/, accessed 2026-09-05.
- Per-file overrides: `[[tool.ty.overrides]]` with `include`, `exclude`, `rules` (and `overrides.analysis`); "Multiple overrides can match the same file; later entries take precedence" and override rules are merged over global rules. Source: https://docs.astral.sh/ty/reference/configuration/#overrides, accessed 2026-09-05.

### 1f. `src` layout: is configuration needed?

- No. `environment.root` ("The root paths of the project, used for finding first-party modules.") defaults to `null`, and "If left unspecified, ty will try to detect common project layouts and initialize `root` accordingly. The project root (`.`) is always included. Additionally, the following directories are included if they exist and are not packages (i.e. they do not contain `__init__.py` or `__init__.pyi` files): `./src`, `./<project-name>` (if a `./<project-name>/<project-name>` directory exists), `./python`". This repo has `src/recursive_application/` with no `src/__init__.py`, so `./src` is auto-added. Source: https://docs.astral.sh/ty/reference/configuration/#root, accessed 2026-09-05.
- Guide wording: "By default, ty searches for first-party modules in the project's root directory or the `src` directory, if present. If your project uses a different layout, configure the project's `environment.root`". Explicit form if ever needed: `[tool.ty.environment] root = ["./src"]`. Source: https://docs.astral.sh/ty/modules/#first-party-modules, accessed 2026-09-05.
- `tests/` is NOT in the current auto-detected root list (an early `0.0.1-alpha.7` entry "Add `tests` to `src.root` by default if a `tests/` directory exists and is not a package" is no longer reflected in the reference; when it was dropped is UNVERIFIED). Because `.` is always a root, `tests/...` modules still resolve as the `tests` package as long as `tests/__init__.py` exists or they are only imported relative to `.`. Source: https://github.com/astral-sh/ty/blob/main/CHANGELOG.md and https://docs.astral.sh/ty/reference/configuration/#root, accessed 2026-09-05.
- The package is also importable via `site-packages` because uv installs the project into `.venv` (the reference notes ty uses site-packages "to resolve third-party (and, in some cases, first-party) imports"). Source: https://docs.astral.sh/ty/reference/configuration/#python, accessed 2026-09-05.

## 2. ruff 0.16.x

- Versions: installed `ruff 0.16.6`; PyPI `info.version` is `0.16.6`, uploaded 2026-09-03T16:56Z; 0.16.0 was uploaded 2026-07-23 (changelog: "Released on 2026-07-23"). Source: https://pypi.org/pypi/ruff/json and https://github.com/astral-sh/ruff/blob/0.16.6/CHANGELOG.md, accessed 2026-09-05; `.venv/bin/ruff --version` run locally 2026-09-05.

### 2a. Rule-group prefixes

- Section headers on the rules page, verbatim: `pycodestyle (E, W)` with sub-sections `Error (E)` and `Warning (W)`; `Pyflakes (F)`; `isort (I)`; `pyupgrade (UP)`; `flake8-bugbear (B)`; `flake8-simplify (SIM)`; `flake8-use-pathlib (PTH)`; `pep8-naming (N)`; `Ruff-specific rules (RUF)`. Codes confirmed present on the page: E501, E711, W291, W605, F401, F841, I001, I002, UP006, UP035, B006, B904, SIM102, SIM108, PTH118, PTH123, N801, N802, RUF005, RUF012, RUF100. Page states "over 900 lint rules". Source: https://docs.astral.sh/ruff/rules/, accessed 2026-09-05.
- Note (relevant only if you rely on defaults rather than `select`): 0.16.0 expanded the default rule set and removed 18 E/F rules from it ("`E401`, `E402`, `E701`, `E702`, `E703`, `E711`, `E712`, `E713`, `E714`, `E721`, `E731`, `E741`, `E742`, `E743`, `F403`, `F405`, `F406`, and `F722`"). An explicit `select = ["E", "F", ...]` re-enables all of them. Source: https://github.com/astral-sh/ruff/blob/0.16.6/CHANGELOG.md (0.16.0), accessed 2026-09-05.

### 2b. Where settings live

- `lint.select`: "A list of rule codes or prefixes to enable. Prefixes can specify exact rules (like `F841`), entire groups (like `F`), or anything in between." Documented under `[tool.ruff.lint]` (anchor `lint_select`). `lint.ignore` and `lint.extend-select` likewise; `lint.extend-ignore` is marked "Deprecated ... interchangeable with `ignore`". The lint section header says "Options specified in the lint section take precedence over the deprecated top-level settings" (i.e. top-level `[tool.ruff] select` is the deprecated form). Source: https://docs.astral.sh/ruff/settings/#lint_select, `#lint_ignore`, `#lint_extend-select`, `#lint`, accessed 2026-09-05.
- `line-length`: "The line length to use when enforcing long-lines violations (like `E501`) and at which `isort` and the formatter prefers to wrap lines." Default `88`, type `int`, example `[tool.ruff] line-length = 120`. Source: https://docs.astral.sh/ruff/settings/#line-length, accessed 2026-09-05.
- `target-version`: "The minimum Python version to target, e.g., when considering automatic code upgrades, like rewriting type annotations." Default `"py310"`; type `"py37" | "py38" | "py39" | "py310" | "py311" | "py312" | "py313" | "py314"`; under `[tool.ruff]`. If unspecified, ruff respects `project.requires-python` (e.g. `>=3.8` is treated as `py38`); an explicit `target-version` takes precedence. Source: https://docs.astral.sh/ruff/settings/#target-version, accessed 2026-09-05.
- Local confirmation: the repo's existing `[tool.ruff] line-length = 100 / target-version = "py312"` and `[tool.ruff.lint] select = [...]` is already the current shape and `ruff check .` exits 0 with it. Source: `/Users/chris/Developer/recursive_application/pyproject.toml`, run locally 2026-09-05.

### 2c. Lint rules that conflict with the formatter

- Verbatim list ("When using Ruff as a formatter, we recommend avoiding the following lint rules"): `tab-indentation` (W191); `indentation-with-invalid-multiple` (E111); `indentation-with-invalid-multiple-comment` (E114); `over-indented` (E117); `incorrect-blank-line-before-class` (D203); `docstring-tab-indentation` (D206); `triple-single-quotes` (D300); `bad-quotes-inline-string` (Q000); `bad-quotes-multiline-string` (Q001); `bad-quotes-docstring` (Q002); `avoidable-escaped-quote` (Q003); `unnecessary-escaped-quote` (Q004); `missing-trailing-comma` (COM812); `prohibited-trailing-comma` (COM819); `multi-line-implicit-string-concatenation` (ISC002) "if used without `ISC001` and `flake8-implicit-str-concat.allow-multiline = false`". Source: https://docs.astral.sh/ruff/formatter/#conflicting-lint-rules, accessed 2026-09-05 (section identical at tag 0.16.6 and `main`).
- No RUF and no SIM rule appears in that list. Of the requested groups (E, F, I, UP, B, SIM, PTH, N, RUF) only E111, E114, E117 are affected, via the `E` parent prefix. The docs' guidance: "None of the above are included in Ruff's default configuration. However, if you've enabled any of these rules or their parent categories (like `Q`), we recommend disabling them via the linter's `lint.ignore` setting." Source: same URL, accessed 2026-09-05.
- E501 caveat: "While the `line-too-long` (`E501`) rule _can_ be used alongside the formatter, the formatter only makes a best-effort attempt to wrap lines at the configured `line-length`. As such, formatted code _may_ exceed the line length, leading to `line-too-long` (`E501`) errors." Source: same URL, accessed 2026-09-05.
- isort settings to leave at defaults: `force-single-line`, `force-wrap-aliases`, `lines-after-imports`, `lines-between-types`, `split-on-trailing-comma`. "When an incompatible lint rule or setting is enabled, `ruff format` will emit a warning." Source: same URL, accessed 2026-09-05.

### 2d. Markdown files and `ruff format` (added at coordinator request)

- `*.md` IS in ruff's default `include`: `Default value: ["*.py", "*.pyi", "*.pyw", "*.ipynb", "*.md", "**/pyproject.toml", "**/ruff.toml", "**/.ruff.toml"]`. Source: `.venv/bin/ruff config include` (ruff 0.16.6, run locally 2026-09-05) and https://docs.astral.sh/ruff/settings/#include, accessed 2026-09-05.
- Timeline from the changelogs: 0.15.0 "Apply formatting to Markdown code blocks (#22470, ...)" (preview); 0.15.5 "Discover Markdown files by default in preview mode (#23434)"; 0.15.8 "Warn when Markdown files are skipped due to preview being disabled (#24150)"; 0.16.0 (released 2026-07-23) stabilised it: "Ruff can now format Python code blocks in Markdown files and will do this by default. See the documentation for more details." Sources: https://github.com/astral-sh/ruff/blob/0.16.6/changelogs/0.15.x.md and https://github.com/astral-sh/ruff/blob/0.16.6/CHANGELOG.md, accessed 2026-09-05.
- What gets formatted: "Ruff will format any CommonMark fenced code blocks with the following info strings: `python`, `py`, `python3`, `py3`, `pyi`, or `pycon`" (and Quarto `{python}`); blocks that don't parse are skipped. Source: https://docs.astral.sh/ruff/formatter/#markdown-code-formatting, accessed 2026-09-05.
- Documented off-switch: "To *disable* formatting of Markdown files, add them to `extend-exclude` in your project settings: `[tool.ruff]` / `# Disable formatting in Markdown files` / `extend-exclude = ["*.md"]`". Source: https://docs.astral.sh/ruff/formatter/#markdown-code-formatting, accessed 2026-09-05.
- There is no Markdown-specific key under `[tool.ruff.format]`. The complete `format` key list on 0.16.6 is: `exclude`, `preview`, `indent-style`, `quote-style`, `nested-string-quote-style`, `skip-magic-trailing-comma`, `line-ending`, `docstring-code-format`, `docstring-code-line-length` (`docstring-code-format` concerns code blocks inside Python docstrings, not `.md` files). `format.exclude = ["*.md"]` would also work as a formatter-only exclusion, but `extend-exclude` is the form the docs prescribe. Source: `.venv/bin/ruff config format` (run locally 2026-09-05) and https://docs.astral.sh/ruff/settings/#format, accessed 2026-09-05.
- Per-block escape hatch: wrap blocks in `<!-- fmt:off -->` ... `<!-- fmt:on -->` HTML comments (blacken-docs comments are also recognised). Source: https://docs.astral.sh/ruff/formatter/#markdown-code-formatting, accessed 2026-09-05.
- Related knobs: `extension = { mdx = "markdown", qmd = "markdown" }` maps extra extensions to Markdown; `force-exclude` / `--force-exclude` makes excludes apply even to paths passed explicitly (needed for pre-commit style invocation). Source: https://docs.astral.sh/ruff/formatter/#markdown-code-formatting and `.venv/bin/ruff format --help`, accessed 2026-09-05.
- Local observation: `ruff format --check .` on this repo flags 14 `.md` files (starting with `docs/pydantic-ai/SKILL.md`, single-quote to double-quote rewrites in ```python blocks); `ruff format --check --exclude '*.md' .` reports "9 files already formatted". `ruff check --show-files .` lists 0 `.md` files, so the linter does not touch Markdown; only the formatter does. Run locally 2026-09-05.

## 3. pydantic-ai 2.40 (installed)

- `ALLOW_MODEL_REQUESTS` is a module-level bool in `pydantic_ai/models/__init__.py`, line 1426: `ALLOW_MODEL_REQUESTS = True`. Docstring: "Whether to allow requests to models. This global setting allows you to disable request to most models, e.g. to make sure you don't accidentally make costly requests to a model during tests. The testing models `TestModel`, `FunctionModel` and `TestEmbeddingModel` are not affected by this setting, nor is `SentenceTransformerEmbeddingModel`, which runs inference locally". Source: `/Users/chris/Developer/recursive_application/.venv/lib/python3.12/site-packages/pydantic_ai/models/__init__.py:1426-1437`, accessed 2026-09-05.
- Enforcement: `check_allow_model_requests()` (line 1440) raises `RuntimeError('Model requests are not allowed, since ALLOW_MODEL_REQUESTS is False')` (lines 1460-1461); provider models call it at the top of `request`/`request_stream`/`count_tokens` (e.g. `models/openai.py` lines 1056, 1093, 2100, ...). `models/test.py` and `models/function.py` never call it. Source: same file plus `pydantic_ai/models/openai.py`, `test.py`, `function.py`, accessed 2026-09-05.
- Temporary override: `override_allow_model_requests(allow_model_requests: bool)` context manager (line 1465) that sets and restores the global. Source: `pydantic_ai/models/__init__.py:1465-1477`, accessed 2026-09-05.
- Module paths: `class TestModel(Model)` at `pydantic_ai/models/test.py:62` -> `pydantic_ai.models.test.TestModel`; `class FunctionModel(Model)` at `pydantic_ai/models/function.py:52` -> `pydantic_ai.models.function.FunctionModel`. Source: those files, accessed 2026-09-05.
- Docs: https://ai.pydantic.dev/testing/ now 301-redirects to https://pydantic.dev/docs/ai/guides/testing/. Bullet: "Set `ALLOW_MODEL_REQUESTS=False` globally to block any requests from being made to non-test models accidentally". The example test module does `from pydantic_ai import models` ... `models.ALLOW_MODEL_REQUESTS = False  # (2)!` with the note "This is a safety measure to make sure we don't accidentally make real requests to the LLM while testing, see `ALLOW_MODEL_REQUESTS` for more details." Imports shown: `from pydantic_ai.models.test import TestModel` and `from pydantic_ai.models.function import AgentInfo, FunctionModel`. The docs set it at module scope in the test file; they do not show a `conftest.py` specifically (a conftest is the natural single place for module-scope code, and the existing `tests/conftest.py` already does exactly this). Source: https://pydantic.dev/docs/ai/guides/testing/ and https://github.com/pydantic/pydantic-ai/blob/main/docs/testing.md, accessed 2026-09-05; `/Users/chris/Developer/recursive_application/tests/conftest.py`.
- Implementation note: assign through the module object (`models.ALLOW_MODEL_REQUESTS = False`); `from pydantic_ai.models import ALLOW_MODEL_REQUESTS` would copy the value and `check_allow_model_requests` reads the module global. Source: `pydantic_ai/models/__init__.py:1460` (reads the global), accessed 2026-09-05.

## 4. pytest 9.1: `[tool.pytest.ini_options]` vs `[tool.pytest]`

- Installed and latest on PyPI: pytest 9.1.1. Source: https://pypi.org/pypi/pytest/json and `.venv/bin/pytest --version`, accessed 2026-09-05.
- Docs (`.. versionadded:: 6.0`, `.. versionchanged:: 9.0`): "Use `[tool.pytest]` to leverage native TOML types (supported since pytest 9.0)" with `addopts = ["-ra", "-q"]` as a TOML list; "Use `[tool.pytest.ini_options]` for INI-style configuration (supported since pytest 6.0)" with `addopts = "-ra -q"` as a string. Both remain documented; neither is labelled deprecated or preferred. Source: https://docs.pytest.org/en/stable/reference/customize.html#pyproject-toml, accessed 2026-09-05.
- Changelog 9.0.0 (2025-11-05), #13743 "Added support for native TOML configuration files": "While pytest, since version 6, supports configuration in `pyproject.toml` files under `[tool.pytest.ini_options]`, it does so in an 'INI compatibility mode', where all configuration values are treated as strings or list of strings. Now, pytest supports the native TOML data model. In `pyproject.toml`, the native TOML configuration is under the `[tool.pytest]` table. ... The `[tool.pytest.ini_options]` table remains supported, but both tables cannot be used at the same time." Source: https://docs.pytest.org/en/stable/changelog.html (9.0.0) / https://github.com/pytest-dev/pytest/blob/main/doc/en/changelog.rst, accessed 2026-09-05.
- `deprecations.rst` has no entry for `ini_options`. Source: https://github.com/pytest-dev/pytest/blob/main/doc/en/deprecations.rst, accessed 2026-09-05.
- Config discovery order: `pytest.toml`, `pytest.ini`, `pyproject.toml` ("contains a `[tool.pytest]` or `[tool.pytest.ini_options]` table"), `tox.ini` (`[pytest]`), `setup.cfg` (`[tool:pytest]`); "the first match wins"; a `pyproject.toml` without either table is still used as the configfile if nothing else matches (since 9.0 for `[tool.pytest]`, 8.1 for `ini_options`). Source: https://docs.pytest.org/en/stable/reference/customize.html#finding-the-rootdir, accessed 2026-09-05.
- Conclusion: the repo's existing `[tool.pytest.ini_options] testpaths = ["tests"]` is fully supported on 9.1.1. Migrating to `[tool.pytest]` is optional; if you do, remove `ini_options` (the two tables are mutually exclusive) and express `addopts` as a list.

## Recommended pyproject.toml snippets

Targets: Python 3.12; ty checks only `src` and `tests`; errors fail the run while warnings are reported but do not fail; ruff line length 100, target py312, `select = E, F, I, UP, B, SIM, PTH, N, RUF`, with formatter-conflict ignores; ruff never touches Markdown.

```toml
[dependency-groups]
dev = [
    "pytest>=9.1",
    "ruff>=0.16",
    "ty>=0.0.78,<0.1",   # not yet installed in .venv; add with uv when ready
]

# --- ty (0.0.78) -----------------------------------------------------------
[tool.ty.environment]
python-version = "3.12"
# `root` is intentionally unset: ty auto-adds `./src` (it has no __init__.py) and always includes `.`.
# The .venv is found via VIRTUAL_ENV (set by `uv run`) or ./.venv; no `python =` needed.

[tool.ty.src]
include = ["src", "tests"]      # anchored at the project root; `exclude` wins over `include`

[tool.ty.terminal]
# Default is `true` (since ty 0.0.52): warnings alone make `ty check` exit 1.
# `false` = errors still exit 1, warnings are printed but exit 0.
error-on-warning = false

[tool.ty.rules]
# Defaults are already error for unresolved-import, invalid-*, etc.
# Uncomment to surface the "possibly-*" family as warnings (they default to `ignore`):
# possibly-unresolved-reference = "warn"
# possibly-missing-attribute = "warn"
# possibly-missing-import = "warn"

# --- ruff (0.16.6) ---------------------------------------------------------
[tool.ruff]
line-length = 100
target-version = "py312"
# ruff >= 0.16.0 formats Python code blocks inside *.md by default (`*.md` is in the default `include`).
# This is the documented off-switch (formatter docs, "Markdown code formatting").
extend-exclude = ["*.md"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PTH", "N", "RUF"]
ignore = [
    # The only members of the selected groups on the formatter's "conflicting lint rules" list:
    "E111",  # indentation-with-invalid-multiple
    "E114",  # indentation-with-invalid-multiple-comment
    "E117",  # over-indented
    # E501 is kept on purpose; the docs note the formatter is best-effort at line-length,
    # so an occasional E501 on a long string/comment is expected and can be noqa'd.
]

# --- pytest (9.1.1) --------------------------------------------------------
# Either table is supported; do not use both at once.
[tool.pytest.ini_options]
testpaths = ["tests"]
# Native-TOML alternative (pytest >= 9.0):
# [tool.pytest]
# testpaths = ["tests"]
# addopts = ["-ra"]
```

Alternative to `error-on-warning = false` when you want CI to fail on warnings too: delete the `[tool.ty.terminal]` table (default) or run `ty check --error-on-warning`; for a one-off lenient run use `ty check --exit-zero-on-warning`.

Equivalent CLI for the ty scope without config: `uv run ty check src tests` (positional PATHS are accepted; `[default: the project root]`).
