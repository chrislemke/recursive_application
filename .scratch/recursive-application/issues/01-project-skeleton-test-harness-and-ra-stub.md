# 01: Project skeleton, test harness, and the `ra` command stub

**What to build:** A fresh checkout where `uv sync` succeeds, `uv run ra --help` lists the six commands and every command exits 2 saying it is not implemented, the four checks (ruff format check, ruff check, ty check, pytest) are green on the otherwise empty tree, and the shared test fixtures that every later ticket relies on exist. This is the prefactoring ticket: it settles the tooling and the fixtures that are off limits during every later red to green loop, so no other ticket has to touch them.

Source: spec sections "Project and tooling" and "Testing Decisions"; the Phase 1 seams document (rules for every module, and the CLI module's two tracer bullets).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] pyright is removed from the project file entirely; ty is the only type checker, configured for Python 3.12 over the source and test roots; ruff, ty, and pytest carry the pinned ranges from the spec's tooling decisions (ty below 0.1)
- [ ] ruff keeps line length 100 and target 3.12 and extends its rule selection with the simplification, pathlib, naming, and Ruff-specific groups; formatting is ruff's
- [ ] The Kernel package, the Organism package, and the Kernel and Organism test packages exist and import; stale bytecode caches from the cancelled attempt are gone
- [ ] The shared conftest disables real model requests for the whole session, removes provider and Logfire keys and every `RA_` variable before each test, and restores the environment afterwards
- [ ] The shared conftest provides the temporary git repository fixture the git seam expects: a real repository with commit signing disabled, an author configured, an initial commit holding a README whose content is `# test`, and an ignore file that lists the runtime directory
- [ ] The CLI stub is built red to green from the seams document's two tracer bullets: `--help` exits 0 and lists ask, improve, evals, status, wiki; `ask hello` and `wiki lint` exit 2 and mention "not implemented"
- [ ] All four checks exit 0
