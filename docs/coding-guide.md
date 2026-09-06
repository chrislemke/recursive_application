# Coding Guide

How code is written in this repository. The Kernel prepends this file to the instructions of the Planner, the Test Writer, the Implementer, the Reviewer, and every coding Specialist. Vocabulary is `CONTEXT.md`. The boundary rules (Kernel, Protected Paths, Policy Ceiling) are in the Constitution and are not repeated here.

## The loop, by role

A code change moves through four steps in this order. Each role owns one step and ends on its completion criterion.

1. **Planner: write the seams.** For every Python file in `target_paths`, `Plan.tests` lists the behaviours to test, one sentence each, at a named public interface: "`Wiki.lint_report()` names a page that is missing from the index". Order them as tracer bullets, smallest behaviour first, each building on the last. State expected values as literals taken from the evidence, never as a formula. Done when every target Python file has at least one behaviour and no behaviour needs a private name to be stated.
2. **Test Writer: go red.** Turn each `Plan.tests` sentence into one pytest test under `tests/organism/`, in the listed order, importing only the interface the sentence names. Run `uv run pytest <your files>` through the shell tool. Done when every new test fails for the right reason, an `AssertionError` or a missing name (`ImportError`, `AttributeError`), and for nothing else. A `SyntaxError` or a broken fixture is not red; fix it first.
3. **Implementer: go green.** Write the least code under `src/recursive_application/organism/` that makes the failing tests pass, one test at a time. Then run the four checks below. Done when all four exit 0. Refactoring is not part of this step; it belongs to the Reviewer's remarks and the next Plan.
4. **Reviewer: judge the diff against the Plan.** Confirm the diff does what `Plan.change` says and nothing more; that every test in the diff sits at a public interface, asserts a literal, and would fail if the behaviour broke; that no eval case and no Protected Path changed. A `reject` verdict names the first violated rule.

The Kernel runs pytest between steps 2 and 3 and rejects the Iteration as "no red" when the new tests already pass, then after step 3 and requires green. A Plan whose target paths hold no Python file skips step 2; its Target Cases are the red.

## Checks

Four commands define clean. The Kernel runs them at the Gate; the Implementer runs them before reporting.

```
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Their configuration is `pyproject.toml`; read it instead of guessing rules. A failing check is fixed in the code. `pyproject.toml` is a Protected Path.

## Python here

- Python 3.12, `src` layout, synchronous code (`run_sync`, blocking subprocesses). `async` only where a library offers nothing else (ADR 0006).
- Data that crosses an agent boundary is a frozen Pydantic model from `src/recursive_application/kernel/records.py` that rejects unknown fields. Organism code imports these; it never defines a parallel contract.
- Paths are `pathlib.Path` in code and repo-relative POSIX strings in contracts.
- Tests use `TestModel` or `FunctionModel` for every agent, a real filesystem under `tmp_path`, the `git_repo` fixture for git, and an injected clock for time. Real model requests are disabled for the whole session in `tests/conftest.py`, a Protected Path.
- Tests live at seams. Read `docs/tdd/SKILL.md` before writing or reviewing a test; `docs/tdd/tests.md` shows good and bad tests, `docs/tdd/mocking.md` where a mock is allowed.

## Pydantic AI here

Two facts override anything the library reference says:

- **Agents never set a model.** `Agent(name=..., output_type=..., toolsets=...)` without a model string; the Kernel injects the model at run time from the registry entry's tier (`primary` or `judge`).
- **Instructions are assembled by the Kernel**: Constitution, then the agent's guides, then `prompts/<agent>.md`, then the State Bundle. A prompt file holds only that agent's own job, and opens by naming the agent's phase in the Loop and the artifact it produces.

For an API question, read `docs/pydantic-ai/SKILL.md`, then exactly one reference from its routing table. The ones this repo reaches most: `docs/pydantic-ai/references/AGENTS-CORE.md` (output types, deps, instructions), `docs/pydantic-ai/references/TOOLS-CORE.md` (function tools and toolsets), `docs/pydantic-ai/references/TESTING-AND-DEBUGGING.md` (`TestModel`, `FunctionModel`). Give every `Agent` an explicit `name=`; it labels the span in the Trace Store.

## Every addition is a loop element

The system is a set of closed loops (`docs/self-improving-loops.md`, ADR 0010). A Plan that adds a capability adds a loop element, so it names all five layers before any code is written:

| Layer | Phase | What the Plan names |
|---|---|---|
| Sensor | Sense | The dataset whose red case will report this capability failing; for a new agent, its `dataset` |
| Policy | Decide | The tool configuration within the Policy Ceiling, and any item only the human may grant |
| Tools | Act | The tools the capability uses and the Actor that uses them |
| Quality gate | Gate | The Target Cases that prove it, plus the four checks |
| Learning | Learn | Where its lessons land (Wiki lessons through the Librarian) and what its failure becomes (a Sensor Finding) |

A capability with a layer missing is not a capability: an agent without a dataset never enters the Capability Inventory, and a Plan without Target Cases is rejected before Act. The Reviewer treats a missing layer as a Plan mismatch. The Watcher over every agent is the Kernel (Sensors, Gate, `ra improve`); never add a monitoring agent to the Organism.

## Where things live

| What | Where |
|---|---|
| Agent registry | `src/recursive_application/organism/agents.py` |
| Prompts | `src/recursive_application/organism/prompts/<agent>.md` |
| Tool configurations | `src/recursive_application/organism/tools.py` |
| Eval datasets | `evals/<agent>.yaml`, `evals/frontier/<capability>.yaml` |
| Organism tests | `tests/organism/` |
| Wiki | `wiki/` |

Adding an agent is one registry entry, one prompt file, one tool configuration within the Policy Ceiling, one dataset that proves it, and one test in `tests/organism/` that loads the entry. Prefer a new narrow agent with one job over widening an existing one.
