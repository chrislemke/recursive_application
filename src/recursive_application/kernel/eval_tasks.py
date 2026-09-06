"""The task function behind every eval dataset, and the runner that drives the suite.

Evals are the integration tests (ADR 0005), so one dataset per role and one ladder per
frontier capability all run through the same three steps: read the case's inputs, run the
role through the agent runtime with a real State Bundle, and render what came back as text
the dataset's evaluators can assert on. The rendering is the contract the seed datasets were
written against, so it lives here and nowhere else.
"""

import hashlib
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_ai.models import Model
from pydantic_evals.evaluators.llm_as_a_judge import set_default_judge_model

from recursive_application.kernel.bundle import SKIPPED_ENTRIES, LoopPosition, assemble_state_bundle
from recursive_application.kernel.checks import classify_red, run_checks, run_red_check
from recursive_application.kernel.evals import (
    EVALS_DIR,
    EXPENSIVE_DATASETS,
    FRONTIER_DIRNAME,
    CaseResult,
    DatasetError,
    EvalReport,
    ReportStore,
    assert_no_model,
    dataset_name,
    list_datasets,
    load_dataset,
    results_from,
)
from recursive_application.kernel.loop import EvalRequest
from recursive_application.kernel.records import Mode
from recursive_application.kernel.registry import Phase, Registry
from recursive_application.kernel.runtime import AgentRunner
from recursive_application.kernel.wiki_protocol import WikiReader

TASK_KINDS: tuple[str, ...] = (
    "triage",
    "planner",
    "test-writer",
    "implementer",
    "answers",
    "reviewer",
    "librarian",
    "frontier",
)
"""Every kind of dataset the Kernel can run: one per role, plus the frontier ladders."""


def dataset_kind(name: str) -> str:
    """Which task function a dataset needs: `frontier` for a ladder, else the dataset's name."""
    prefix, separator, _ = name.partition("/")
    return FRONTIER_DIRNAME if separator and prefix == FRONTIER_DIRNAME else name


@dataclass(frozen=True)
class EvalContext:
    """Everything a task function needs to run one role over one case.

    The State Bundle an eval builds is the production one, so the context carries what
    `assemble_state_bundle` reads: the checkout, the runtime directory, the registry, the Wiki,
    and the budget. `scratch` is where the roles that need a checkout of their own get one.
    """

    runner: AgentRunner
    registry: Registry
    root: Path
    run_id: str
    iteration_limit: int
    scratch: Path
    ra_dir: Path
    wiki: WikiReader
    budget_usd: Decimal


ROLE_POSITIONS: Mapping[str, tuple[str, Mode, Phase]] = {
    "triage": ("triage", Mode.ANSWER, "decide"),
    "answers": ("worker", Mode.ANSWER, "act"),
    "reviewer": ("reviewer", Mode.GROWTH, "gate"),
    "planner": ("planner", Mode.GROWTH, "decide"),
    "librarian": ("librarian", Mode.GROWTH, "learn"),
    "test-writer": ("test_writer", Mode.GROWTH, "act"),
    "implementer": ("implementer", Mode.GROWTH, "act"),
    "frontier": ("worker", Mode.ANSWER, "act"),
}
"""The role, Loop Mode, and phase each kind of dataset places its agent in.

Triage is asked in Answer Mode because the Mode is what it decides; every other kind runs in
the Mode its dataset describes.
"""


PROJECT_FILENAME = "pyproject.toml"
"""The project file a scratch checkout needs so the four checks run there."""

SCRATCH_ENTRIES: tuple[str, ...] = (
    PROJECT_FILENAME,
    "CONTEXT.md",
    "src",
    "tests",
    "evals",
    "docs",
    "wiki",
)
"""What a scratch checkout copies: enough for the whole test suite and the four checks to run
there, the Protected documents the Kernel tests read included."""
"""What a scratch checkout holds: the project file, both packages, the tests, and the datasets."""

SKIPPED_NAMES = SKIPPED_ENTRIES
"""What a scratch checkout leaves out, the same list the State Bundle's tree skips."""

PYTEST_TABLE = "[tool.pytest.ini_options]"
"""The project file's pytest table, where a scratch checkout points pytest at its own `src/`."""

NOTHING_COLLECTED = 5
"""pytest's exit code for "no tests ran", which is what a role that wrote nothing produces."""

WIKI_DIRNAME = "wiki"
"""The Wiki's directory in a checkout; a scratch Wiki keeps the name so paths stay production."""

WIKI_PAGES_DIRNAME = "pages"
"""Where a Wiki's pages live, relative to its root."""

WIKI_LOG_FILENAME = "log.md"
"""The Wiki's log, whose last line the Librarian dataset reads back."""


def render_output(value: Any) -> str:
    """What the evaluators see: a contract as YAML, a text answer as it is."""
    if isinstance(value, BaseModel):
        return yaml.safe_dump(value.model_dump(mode="json"), sort_keys=False)
    if isinstance(value, str):
        return value
    return yaml.safe_dump(value, sort_keys=False)


def _bundle_for(ctx: EvalContext, kind: str) -> str:
    """The production State Bundle for the Loop position this kind of dataset evaluates."""
    role, mode, phase = ROLE_POSITIONS[kind]
    position = LoopPosition(
        run_id=ctx.run_id,
        mode=mode,
        iteration=1,
        iteration_limit=ctx.iteration_limit,
        phase=phase,
        role=role,
    )
    return assemble_state_bundle(
        position,
        root=ctx.root,
        ra_dir=ctx.ra_dir,
        registry=ctx.registry,
        wiki=ctx.wiki,
        budget_usd=ctx.budget_usd,
    )


def _run_role(ctx: EvalContext, kind: str, prompt: str, *, tool_root: Path | None = None) -> Any:
    """Run this kind's role on `prompt`, with its tools rooted at `tool_root` when one is given.

    A role that works on a scratch checkout keeps the paths it uses in production, so the
    override swaps only where the toolsets are rooted and never what the agent is.
    """
    entry = ctx.registry.get(ROLE_POSITIONS[kind][0])
    bundle = _bundle_for(ctx, kind)
    if tool_root is None:
        return ctx.runner.run(entry, prompt, bundle=bundle).output
    # Imported here so the Kernel package never depends on the Organism at import time.
    from recursive_application.organism.tools import toolsets_for

    with entry.agent.override(toolsets=toolsets_for(entry.tools, tool_root)):
        return ctx.runner.run(entry, prompt, bundle=bundle).output


def _mapping(inputs: str) -> dict[str, Any]:
    """The case's inputs as the mapping its dataset holds, read from the YAML block scalar."""
    loaded = yaml.safe_load(inputs)
    if not isinstance(loaded, dict):
        raise DatasetError(f"the case's inputs are not a mapping: {inputs[:80]!r}")
    return loaded


def _prompt(*sections: tuple[str, Any]) -> str:
    """The prompt a mapping-shaped case becomes: one headed section per field it holds."""
    return "\n\n".join(
        f"## {heading}\n\n{render_output(body).strip()}"
        for heading, body in sections
        if body is not None
    )


def _scratch_dir(ctx: EvalContext, kind: str) -> Path:
    """A fresh empty directory under `ctx.scratch` for one case of one kind."""
    ctx.scratch.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{kind}-", dir=ctx.scratch))


def _with_scratch_pythonpath(text: str) -> str:
    """The project file with pytest importing the scratch `src/` instead of the installed package.

    The checkout is installed into the virtualenv as a path entry, so a scratch copy without this
    would run its tests against the real package and the role's edits would be invisible.
    """
    if "pythonpath" in text:
        return text
    if PYTEST_TABLE in text:
        return text.replace(PYTEST_TABLE, f'{PYTEST_TABLE}\npythonpath = ["src"]', 1)
    return f'{text}\n{PYTEST_TABLE}\npythonpath = ["src"]\n'


def copy_checkout(ctx: EvalContext, kind: str) -> Path:
    """A scratch checkout of `ctx.root` for one role to work in; its `pythonpath` points at it."""
    scratch = _scratch_dir(ctx, kind)
    for name in SCRATCH_ENTRIES:
        source = ctx.root / name
        if source.is_dir():
            shutil.copytree(source, scratch / name, ignore=shutil.ignore_patterns(*SKIPPED_NAMES))
        elif source.is_file():
            shutil.copy2(source, scratch / name)
    project = scratch / PROJECT_FILENAME
    project.write_text(
        _with_scratch_pythonpath(project.read_text(encoding="utf-8")), encoding="utf-8"
    )
    return scratch


def _files_under(root: Path) -> dict[str, bytes]:
    """Every file of a checkout by repo-relative POSIX path, with the digest of its content."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).digest()
        for path in root.rglob("*")
        if path.is_file() and not SKIPPED_NAMES & set(path.relative_to(root).parts)
    }


def _changed_files(before: Mapping[str, bytes], after: Mapping[str, bytes]) -> list[str]:
    """The files a role wrote or rewrote, sorted; a deleted file is not one it can test."""
    return sorted(path for path, digest in after.items() if before.get(path) != digest)


def _write_tests(scratch: Path, tests: Sequence[Mapping[str, Any]]) -> list[str]:
    """Write the case's failing tests into the scratch checkout and return their paths."""
    paths = []
    for test in tests:
        path = str(test["path"])
        target = scratch / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(test["content"]), encoding="utf-8")
        paths.append(path)
    return paths


def _tests_text(tests: Sequence[Mapping[str, Any]]) -> str:
    """The failing tests as prompt text: one path and its source per test."""
    return "\n\n".join(f"{test.get('path', '')}\n\n{test.get('content', '')}" for test in tests)


def _log_tail(wiki_root: Path) -> str:
    """The last entry of a Wiki's log, or the empty string when it logged nothing."""
    log = wiki_root / WIKI_LOG_FILENAME
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _wiki_pages(wiki_root: Path) -> dict[str, str]:
    """Every page of a Wiki, keyed by its Wiki-relative POSIX path."""
    pages = wiki_root / WIKI_PAGES_DIRNAME
    return {
        path.relative_to(wiki_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(pages.rglob("*.md"))
    }


def _triage_task(ctx: EvalContext) -> Callable[[str], str]:
    """Triage: the request text goes in, its TriageDecision comes back as YAML."""

    def run(inputs: str) -> str:
        return render_output(_run_role(ctx, "triage", inputs))

    return run


def _worker_task(kind: str) -> Callable[[EvalContext], Callable[[str], str]]:
    """The Worker: the question goes in, the content of its WorkerOutput comes back as it is.

    Both the answers dataset and every frontier ladder ask the Worker a question, so they share
    this builder and differ only in the Loop position their kind names.
    """

    def build(ctx: EvalContext) -> Callable[[str], str]:
        def run(inputs: str) -> str:
            return render_output(_run_role(ctx, kind, inputs).content)

        return run

    return build


def _planner_task(ctx: EvalContext) -> Callable[[str], str]:
    """The Planner: a Task, a goal, and the Sensor Findings in, its Plan as YAML out."""

    def run(inputs: str) -> str:
        mapping = _mapping(inputs)
        prompt = _prompt(
            ("Task", mapping.get("task")),
            ("Goal", mapping.get("goal")),
            ("Sensor Findings", mapping.get("findings")),
        )
        return render_output(_run_role(ctx, "planner", prompt))

    return run


def _librarian_task(ctx: EvalContext) -> Callable[[str], str]:
    """The Librarian: a run summary in, what it wrote to a scratch Wiki out.

    The scratch checkout holds a copy of `wiki/` and the tools are rooted at it, so the paths
    the Librarian writes are the `wiki/pages/...` paths it uses in production.
    """

    def run(inputs: str) -> str:
        mapping = _mapping(inputs)
        scratch = _scratch_dir(ctx, "librarian")
        shutil.copytree(ctx.root / WIKI_DIRNAME, scratch / WIKI_DIRNAME)
        summary = _run_role(
            ctx,
            "librarian",
            _prompt(("Run summary", mapping.get("run_summary"))),
            tool_root=scratch,
        )
        wiki_root = scratch / WIKI_DIRNAME
        return render_output(
            {
                "summary": render_output(summary),
                "log_tail": _log_tail(wiki_root),
                "pages": _wiki_pages(wiki_root),
            }
        )

    return run


def _test_writer_task(ctx: EvalContext) -> Callable[[str], str]:
    """The Test Writer: a Plan in, the files it wrote and what pytest says about them out.

    Which files changed is read from the scratch checkout rather than from the agent's own
    report, so a role that writes outside `tests/organism/` cannot hide it.
    """

    def run(inputs: str) -> str:
        mapping = _mapping(inputs)
        scratch = copy_checkout(ctx, "test-writer")
        before = _files_under(scratch)
        _run_role(ctx, "test-writer", _prompt(("Plan", mapping.get("plan"))), tool_root=scratch)
        changed = _changed_files(before, _files_under(scratch))
        red = (
            run_red_check(scratch, changed)
            if changed
            else classify_red(NOTHING_COLLECTED, "the Test Writer changed no file")
        )
        return render_output(
            {"changed_files": changed, "pytest_exit": red.exit_code, "red": red.red}
        )

    return run


def _implementer_task(ctx: EvalContext) -> Callable[[str], str]:
    """The Implementer: a Plan and failing tests in, whether they pass and the tree is clean out.

    The tests are written into the scratch checkout before the role runs, so the red it has to
    turn green is the dataset's, and the four checks then run over that same checkout.
    """

    def run(inputs: str) -> str:
        mapping = _mapping(inputs)
        scratch = copy_checkout(ctx, "implementer")
        tests = list(mapping.get("tests") or [])
        paths = _write_tests(scratch, tests)
        prompt = _prompt(("Plan", mapping.get("plan")), ("Failing tests", _tests_text(tests)))
        _run_role(ctx, "implementer", prompt, tool_root=scratch)
        red = run_red_check(scratch, paths)
        checks = {result.name: result.passed for result in run_checks(scratch)}
        return render_output(
            {
                "pytest_exit": red.exit_code,
                "ruff_format": checks["ruff-format"],
                "ruff_check": checks["ruff-check"],
                "ty": checks["ty"],
                "green": red.exit_code == 0,
                "checks_clean": all(checks.values()),
            }
        )

    return run


def _reviewer_task(ctx: EvalContext) -> Callable[[str], str]:
    """The Reviewer: a Plan and the diff that claims to carry it out, its Review as YAML."""

    def run(inputs: str) -> str:
        mapping = _mapping(inputs)
        prompt = _prompt(("Plan", mapping.get("plan")), ("Diff", mapping.get("diff")))
        return render_output(_run_role(ctx, "reviewer", prompt))

    return run


_TASK_BUILDERS: dict[str, Callable[[EvalContext], Callable[[str], str]]] = {
    "triage": _triage_task,
    "planner": _planner_task,
    "test-writer": _test_writer_task,
    "implementer": _implementer_task,
    "answers": _worker_task("answers"),
    "reviewer": _reviewer_task,
    "librarian": _librarian_task,
    "frontier": _worker_task("frontier"),
}
"""One builder per dataset kind; each returns the function pydantic-evals calls per case."""


def task_for(kind: str, ctx: EvalContext) -> Callable[[str], str]:
    """The task function for one kind of dataset; an unknown kind is refused by name."""
    builder = _TASK_BUILDERS.get(kind)
    if builder is None:
        raise DatasetError(f"no task function for dataset kind {kind!r}")
    return builder(ctx)


def _dataset_paths(
    names: Sequence[str] | None, evals_dir: Path, include_expensive: bool
) -> list[Path]:
    """Which dataset files this run covers; an unknown name is refused before anything runs."""
    if names is None:
        paths = list_datasets(evals_dir)
        if include_expensive:
            return paths
        return [path for path in paths if dataset_name(path, evals_dir) not in EXPENSIVE_DATASETS]
    selected: list[Path] = []
    for name in names:
        path = evals_dir / f"{name}.yaml"
        if not path.is_file():
            raise DatasetError(f"unknown dataset: {name!r} ({path} does not exist)")
        selected.append(path)
    return selected


def run_evals(
    names: Sequence[str] | None,
    *,
    ctx: EvalContext,
    reports_dir: Path,
    judge_model: str | Model,
    judge_setter: Callable[[Any], None] = set_default_judge_model,
    evals_dir: Path = EVALS_DIR,
    repeat: int = 1,
    include_expensive: bool = False,
) -> tuple[EvalReport, Path]:
    """Run the selected datasets and save one report; `names=None` runs the cheap suite.

    The Judge Model is set once, before the first case, so a dataset never names a model of its
    own (ADR 0005); `repeat` runs every case that often for a human who wants variance. The
    setter takes `Any` because pydantic-evals types its own parameter as a literal union of the
    model names it knows, which no configured name satisfies.
    """
    paths = _dataset_paths(names, evals_dir, include_expensive)
    for path in paths:
        assert_no_model(path)
    judge_setter(judge_model)
    datasets: list[str] = []
    cases: list[CaseResult] = []
    for path in paths:
        name = dataset_name(path, evals_dir)
        task = task_for(dataset_kind(name), ctx)
        report = load_dataset(path).evaluate_sync(task, progress=False, repeat=repeat)
        datasets.append(name)
        cases.extend(results_from(name, report))
    report = EvalReport(run_id=ctx.run_id, datasets=datasets, cases=cases)
    return report, ReportStore(reports_dir).save(report)


def _reported_as(targets: Sequence[str], path: Path) -> str:
    """The dataset name a runtime `cases.yaml` is reported under when the request names none.

    A target key is `<dataset>/<case>`, split at the last `/` as `compare` splits it, so the
    Gate finds its Target Cases; a request without targets falls back to the file's own name.
    """
    return targets[0].rpartition("/")[0] if targets else path.stem


def evaluate_request(
    request: EvalRequest,
    *,
    ctx: EvalContext,
    reports_dir: Path,
    judge_model: str | Model,
    judge_setter: Callable[[Any], None] = set_default_judge_model,
) -> EvalReport:
    """Answer one `EvalRequest` from the Loop: the run's own Target Cases, or whole datasets.

    An Answer or Task Iteration judges text the Loop already produced, so its request carries a
    runtime `cases.yaml` and the output, and the task function returns that output unchanged;
    the report is keyed by the dataset half of the first target, which is what the Gate compares
    against. A Growth Iteration names datasets under `evals/` instead and runs them for real.
    """
    if request.task_dataset is None:
        report, _ = run_evals(
            list(request.datasets),
            ctx=ctx,
            reports_dir=reports_dir,
            judge_model=judge_model,
            judge_setter=judge_setter,
        )
        return report
    path = Path(request.task_dataset)
    dataset = load_dataset(path)
    judge_setter(judge_model)

    def answer(inputs: str) -> str:
        return request.output or ""

    evaluation = dataset.evaluate_sync(answer, progress=False)
    name = request.dataset or _reported_as(request.targets, path)
    return EvalReport(run_id=request.run_id, datasets=[name], cases=results_from(name, evaluation))
