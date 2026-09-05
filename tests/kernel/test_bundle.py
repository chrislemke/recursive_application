"""The State Bundle and the Capability Inventory.

Every render function is pure over its arguments, so the report, the ratios, the findings, and
the Run Records are built here and the expected lines are literals from the seams document; the
registry and the frontier ladders are the real ones. The tree runs over a `tmp_path` layout and
`assemble_state_bundle` over a runtime directory and a Wiki there. No model call anywhere.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from recursive_application.kernel.bundle import (
    LoopPosition,
    assemble_state_bundle,
    dataset_cases,
    render_bundle,
    render_inventory,
    render_tree,
)
from recursive_application.kernel.evals import (
    EVALS_DIR,
    CaseResult,
    EvalReport,
    FrontierRatio,
    ReportStore,
    frontier_ratios,
)
from recursive_application.kernel.paths import REPO_ROOT, ensure_ra_dirs
from recursive_application.kernel.policy import ToolConfig
from recursive_application.kernel.records import (
    IterationRecord,
    Mode,
    RunRecord,
    RunStore,
    SensorFinding,
    Usage,
    WorkerOutput,
)
from recursive_application.kernel.registry import Registry, RegistryEntry, load_registry
from recursive_application.organism.tools import ToolDescription, describe_tools
from recursive_application.organism.wiki import CapabilityPage, Wiki

FRONTIER_DIR = EVALS_DIR / "frontier"


def _report(cases: dict[str, bool]) -> EvalReport:
    """A report whose cases are `<dataset>/<name>` keys mapped to whether they passed."""
    return EvalReport(
        datasets=sorted({key.rsplit("/", 1)[0] for key in cases}),
        cases=[
            CaseResult(dataset=key.rsplit("/", 1)[0], name=key.rsplit("/", 1)[1], passed=passed)
            for key, passed in cases.items()
        ],
    )


def _tools_of(registry: Registry) -> dict[str, list[ToolDescription]]:
    """The tools of every entry, the mapping the inventory renders."""
    return {entry.name: describe_tools(entry.tools, REPO_ROOT) for entry in registry.entries}


def _line(text: str, prefix: str) -> str:
    """The one line of `text` that starts with `prefix`."""
    return next(line for line in text.splitlines() if line.startswith(prefix))


def test_inventory_without_a_report_marks_every_agent_unproven_and_names_its_tools() -> None:
    registry = load_registry()
    ratios = frontier_ratios(FRONTIER_DIR, None)

    text = render_inventory(registry, None, ratios, [], _tools_of(registry), {})

    assert "## Capability Inventory" in text
    assert _line(text, "- triage") == "- triage (decide): unproven (evals/triage.yaml); tools: none"
    assert "unproven (evals/answers.yaml)" in _line(text, "- worker ")
    assert "write_file" in _line(text, "- implementer ")
    assert "- repo-history: 0/4, next rung 1" in text
    assert "- text-analysis: 0/5, next rung 1" in text
    assert "- web-research: 0/3, next rung 1" in text
    assert "### Learned capabilities\n\n- (none)" in text
    assert text == render_inventory(registry, None, ratios, [], _tools_of(registry), {})


def test_inventory_proves_a_dataset_only_when_the_report_holds_it_all_green() -> None:
    registry = load_registry()
    tools = _tools_of(registry)
    page = CapabilityPage(
        "repo-history",
        "pages/capabilities/repo-history.md",
        "abc1234",
        "evals/frontier/repo-history.yaml",
    )
    green = _report({"triage/a": True, "triage/b": True})
    one_red = _report({"triage/a": True, "triage/b": False})
    full_ladder = [FrontierRatio(capability="repo-history", green=3, total=3)]

    cases = {"triage": ["a", "b"]}

    proven = render_inventory(registry, green, full_ladder, [page], tools, cases)
    unproven = render_inventory(registry, one_red, full_ladder, [page], tools, cases)

    assert "proven by evals/triage.yaml;" in _line(proven, "- triage ")
    assert "unproven (evals/triage.yaml);" in _line(unproven, "- triage ")
    assert "unproven (evals/answers.yaml);" in _line(proven, "- worker ")
    assert (
        _line(proven, "- repo-history:")
        == "- repo-history: evals/frontier/repo-history.yaml (commit abc1234)"
    )
    assert "- repo-history: 3/3, available" in proven


def _write(root: Path, relative: str, text: str = "x\n") -> None:
    """One file under `root`, with the directories on the way to it."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_tree_marks_the_write_scope_editable_and_leaves_out_the_runtime_directories(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "docs/x.md")
    _write(tmp_path, "src/recursive_application/organism/agents.py")
    _write(tmp_path, "wiki/index.md")
    _write(tmp_path, ".venv/x")
    _write(tmp_path, ".ra/y")

    text = render_tree(tmp_path)

    assert "- docs/ (read-only)" in text
    assert "- src/ (read-only)" in text
    assert "- wiki/ (editable)" in text
    assert "  - src/recursive_application/organism/agents.py (editable)" in text
    assert "  - wiki/index.md (editable)" in text
    assert ".venv" not in text
    assert ".ra" not in text


POSITION = LoopPosition(
    run_id="r1",
    mode=Mode.ANSWER,
    iteration=2,
    iteration_limit=5,
    phase="act",
    role="worker",
    previous_gate="failed",
)


def _run(number: int) -> RunRecord:
    """One finished Answer run of one Iteration that cost a quarter of a dollar."""
    return RunRecord(
        run_id=f"run-{number}",
        mode=Mode.ANSWER,
        started_at=datetime(2026, 9, 5, 12, number, tzinfo=UTC),
        outcome="accepted",
        iterations=[IterationRecord(number=1, usage=Usage(cost_usd=Decimal("0.25")))],
    )


def _bundle(**changes: Any) -> str:
    """The State Bundle of the Loop position above, with `changes` replacing single parts."""
    parts: dict[str, Any] = {
        "inventory": "## Capability Inventory",
        "tree": "- wiki/ (editable)",
        "eval_summary": ["triage: 2/2 passed"],
        "findings": [],
        "wiki_index": "# Wiki index",
        "runs": [],
    }
    position = changes.pop("position", POSITION)
    return render_bundle(position, **(parts | changes))


def test_bundle_opens_with_the_loop_position_and_caps_its_findings_and_runs() -> None:
    findings = [
        SensorFinding(id=f"evals:triage/case-{number:02d}", source="evals", summary="is red")
        for number in range(1, 13)
    ]

    text = _bundle(findings=findings, runs=[_run(number) for number in range(1, 6)])

    assert text.startswith(
        "## Loop position\n\n"
        "Run: r1\n"
        "Mode: answer\n"
        "Iteration: 2 of 5\n"
        "Phase: act\n"
        "Role: worker\n"
        "Previous Gate: failed\n"
    )
    assert "Previous Gate: none" in _bundle(
        position=POSITION.model_copy(update={"previous_gate": None})
    )
    assert "- [medium] evals:triage/case-01: is red" in text
    assert "evals:triage/case-10" in text
    assert "evals:triage/case-11" not in text
    assert "evals:triage/case-12" not in text
    assert "- run-3: answer, accepted, 1 Iterations, 0.25 USD" in text
    assert "run-2" not in text
    assert "run-5" in text
    assert "## Evals\n\ntriage: 2/2 passed" in text
    assert "## Evals\n\n(no report)" in _bundle(eval_summary=[])
    assert "## Repository\n\n- wiki/ (editable)" in text
    assert "## Capability Inventory" in text
    assert "## Wiki index\n\n# Wiki index" in text
    assert "## Open Sensor Findings" in text
    assert "## Recent runs" in text


def test_assembled_bundle_reads_the_runtime_directory_the_wiki_and_the_registry(
    tmp_path: Path,
) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)
    ReportStore(ra_dir / "evals").save(_report({f"triage/{name}": True for name in TRIAGE_CASES}))
    RunStore(ra_dir / "runs").save(_run(7))
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()
    (wiki.root / "pages/capabilities/repo-history.md").write_text(
        wiki.capability_page(
            "repo-history",
            "Reads the history of the checkout.",
            commit="abc1234",
            dataset="evals/frontier/repo-history.yaml",
        )
    )
    wiki.rebuild_index()

    text = assemble_state_bundle(
        POSITION,
        root=REPO_ROOT,
        ra_dir=ra_dir,
        registry=load_registry(),
        wiki=wiki,
        budget_usd=Decimal("5"),
    )

    assert "## Loop position" in text
    assert "## Capability Inventory" in text
    assert "- repo-history: evals/frontier/repo-history.yaml (commit abc1234)" in text
    assert "proven by evals/triage.yaml" in _line(text, "- triage ")
    assert "run-7" in text


TRIAGE_CASES = [
    "triage-1-answer-from-current-capabilities",
    "triage-2-growth-skill-gap-analyse-an-argument",
    "triage-3-growth-tool-gap-who-changed-the-gate",
    "triage-4-growth-connection-gap-news-front-page",
    "triage-5-clarification-make-it-better",
]


def test_a_dataset_is_proven_only_when_every_case_in_the_file_passed_not_only_those_run() -> None:
    registry = load_registry()
    tools = _tools_of(registry)
    partial = _report({f"triage/{TRIAGE_CASES[0]}": True})
    complete = _report({f"triage/{name}": True for name in TRIAGE_CASES})

    unproven = render_inventory(
        registry, partial, [], [], tools, dataset_cases(registry, REPO_ROOT)
    )
    proven = render_inventory(registry, complete, [], [], tools, dataset_cases(registry, REPO_ROOT))

    assert "unproven (evals/triage.yaml);" in _line(unproven, "- triage ")
    assert "proven by evals/triage.yaml;" in _line(proven, "- triage ")


def test_the_inventory_describes_every_distinct_tool_once() -> None:
    registry = load_registry()

    text = render_inventory(registry, None, [], [], _tools_of(registry), {})

    tools_section = text.split("### Tools")[1].split("###")[0]
    read_file_lines = [
        line for line in tools_section.splitlines() if line.startswith("- read_file: ")
    ]
    assert len(read_file_lines) == 1
    assert read_file_lines[0].endswith(".")
    assert len(read_file_lines[0]) > len("- read_file: .")


def test_a_specialist_is_listed_only_once_its_dataset_is_green() -> None:
    real = load_registry()
    specialist = RegistryEntry(
        name="specialist_x",
        agent=Agent(name="specialist_x", output_type=WorkerOutput),
        tier="primary",
        phases=("act",),
        tools=ToolConfig(),
        guides=(),
        prompt_path="src/recursive_application/organism/prompts/worker.md",
        dataset="evals/answers.yaml",
    )
    registry = Registry(entries=(*real.entries, specialist))
    cases = {"answers": ["a", "b"]}
    green = _report({"answers/a": True, "answers/b": True})

    before = render_inventory(registry, None, [], [], {}, cases)
    after = render_inventory(registry, green, [], [], {}, cases)

    assert "- specialist_x" not in before
    assert "- worker (act): unproven (evals/answers.yaml)" in before
    assert "- specialist_x (act): proven by evals/answers.yaml; tools: none" in after
