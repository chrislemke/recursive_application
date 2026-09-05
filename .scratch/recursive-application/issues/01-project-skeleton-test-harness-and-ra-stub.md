# 01: Project skeleton, test harness, and the `ra` command stub

**What to build:** A fresh checkout where `uv sync` succeeds, `uv run ra --help` lists the six commands and every command exits 2 saying it is not implemented, the four checks (ruff format check, ruff check, ty check, pytest) are green on the otherwise empty tree, and the shared test fixtures that every later ticket relies on exist. This is the prefactoring ticket: it settles the tooling and the fixtures that are off limits during every later red to green loop, so no other ticket has to touch them.

Source: spec sections "Project and tooling" and "Testing Decisions"; the Phase 1 seams document (rules for every module, and the CLI module's two tracer bullets).

**Blocked by:** None (can start immediately)

**Status:** done

- [x] pyright is removed from the project file entirely; ty is the only type checker, configured for Python 3.12 over the source and test roots; ruff, ty, and pytest carry the pinned ranges from the spec's tooling decisions (ty below 0.1)
- [x] ruff keeps line length 100 and target 3.12 and extends its rule selection with the simplification, pathlib, naming, and Ruff-specific groups; formatting is ruff's
- [x] The Kernel package, the Organism package, and the Kernel and Organism test packages exist and import; stale bytecode caches from the cancelled attempt are gone
- [x] The shared conftest disables real model requests for the whole session, removes provider and Logfire keys and every `RA_` variable before each test, and restores the environment afterwards
- [x] The shared conftest provides the temporary git repository fixture the git seam expects: a real repository with commit signing disabled, an author configured, an initial commit holding a README whose content is `# test`, and an ignore file that lists the runtime directory
- [x] The CLI stub is built red to green from the seams document's two tracer bullets: `--help` exits 0 and lists ask, improve, evals, status, wiki; `ask hello` and `wiki lint` exit 2 and mention "not implemented"
- [x] All four checks exit 0

## Comments

**2026-09-05, implemented.** Prefactoring first (`pyproject.toml`, package skeleton, `tests/conftest.py`), then the CLI stub red to green from the seams doc's two tracer bullets (three tests in `tests/kernel/test_cli.py`). Library facts were verified against primary sources in `thoughts/shared/research/2026-09-05-ty-ruff-pytest-config.md`. Two-axis code review found no standards violations and all seven criteria met; its judgement calls (shared flag aliases, dead `__future__` imports, a redundant `--no-gpg-sign`, and ruff ignores the spec did not ask for) were applied.

Two deviations for the human to confirm, both forced by the libraries:

- **ruff never touches Markdown.** ruff 0.16 formats Python code blocks inside `*.md` by default and would have rewritten the verbatim reference copies under `docs/pydantic-ai/`, which are Protected. `pyproject.toml` therefore sets `extend-exclude = ["*.md"]`. Suggested spec amendment under "Project and tooling": "ruff excludes Markdown files; the reference copies stay verbatim."
- **`--budget` is a float at the CLI boundary.** Typer 0.27 raises `Type not yet supported` for `Decimal`. The Loop's budget arithmetic can still use `Decimal` (settings module); the CLI converts when the Loop runner lands (ticket 18).

Also noted: `ty` 0.0.78 fails on warnings by default since 0.0.52, so `[tool.ty.terminal] error-on-warning = false` is what implements "errors fail, warnings are reported". Kernel commits are made with `-c commit.gpgsign=false`; the fixture disables signing through the temporary repo's config.
