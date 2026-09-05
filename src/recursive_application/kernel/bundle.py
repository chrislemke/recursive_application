"""The State Bundle and the Capability Inventory.

The Kernel tells every agent what the system is and where in the Loop it stands, with no model
call: the render functions are pure over their arguments and `assemble_state_bundle` is the one
composer that reads the runtime directory and the Wiki. The Capability Inventory is the sole
source Triage may cite for "available" (ADR 0009), so what it claims is proven comes from the
eval report and the frontier ladders, never from an agent.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from recursive_application.kernel.evals import (
    EVALS_DIR,
    FRONTIER_DIRNAME,
    EvalReport,
    FrontierRatio,
    ReportStore,
    dataset_name,
    frontier_ratios,
    load_dataset,
)
from recursive_application.kernel.paths import (
    EVALS_DIRNAME,
    RUNS_DIRNAME,
    WRITABLE_DIRS,
    is_writable,
)
from recursive_application.kernel.records import (
    Contract,
    Mode,
    RunRecord,
    RunStore,
    SensorFinding,
)
from recursive_application.kernel.registry import Phase, Registry, RegistryEntry
from recursive_application.kernel.sensors import collect
from recursive_application.kernel.wiki_protocol import CapabilityPageLike, WikiReader

INVENTORY_HEADING = "## Capability Inventory"
"""The heading the inventory opens with, inside the State Bundle and on its own."""

EVALS_ROOT_DIRNAME = EVALS_DIR.name
"""The tracked `evals/` directory's name, as distinct from the runtime directory's `evals/`."""


class ToolDescriptionLike(Protocol):
    """What the inventory shows of a tool: its name and one sentence on what it does."""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...


MAX_FINDINGS = 10
"""How many open Sensor Findings the State Bundle shows: the most severe ten."""

MAX_RUNS = 3
"""How many Run Records the State Bundle shows: the last three."""


class LoopPosition(Contract):
    """Where in the Loop an agent stands when the Kernel calls it (ADR 0010)."""

    run_id: str
    mode: Mode
    iteration: int
    iteration_limit: int
    phase: Phase
    role: str
    previous_gate: Literal["passed", "failed"] | None = None


SKIPPED_ENTRIES: frozenset[str] = frozenset(
    {".git", ".venv", ".ra", ".logfire", ".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache"}
)
"""What the tree never shows: git, the virtualenv, runtime data, and the caches."""

SKIPPED_FILES: frozenset[str] = frozenset({".gitkeep"})
"""Files inside the write scope the tree leaves out: they say nothing about the code."""


def dataset_cases(registry: Registry, root: Path) -> dict[str, list[str]]:
    """The case names of every registry entry's dataset under `root`, keyed by dataset name.

    The inventory proves a dataset only when every case in the file passed, not only the
    cases the latest report happened to run (a Gate Iteration runs the Guard subset only).
    """
    return {
        dataset_name(Path(entry.dataset), Path(EVALS_ROOT_DIRNAME)): [
            case.name or "" for case in load_dataset(root / entry.dataset).cases
        ]
        for entry in registry.entries
    }


def _is_proven(
    report: EvalReport | None, entry: RegistryEntry, cases: Mapping[str, Sequence[str]]
) -> bool:
    """Whether every case of the entry's dataset has a passing result in `report`."""
    if report is None:
        return False
    name = dataset_name(Path(entry.dataset), Path(EVALS_ROOT_DIRNAME))
    names = cases.get(name, [])
    passed = {result.name for result in report.cases if result.dataset == name and result.passed}
    return bool(names) and set(names) <= passed


def _agent_line(entry: RegistryEntry, proven: bool, tools: Sequence[ToolDescriptionLike]) -> str:
    """One agent: its phases, whether its dataset proves it, and the names of its tools."""
    names = ", ".join(tool.name for tool in tools) or "none"
    proof = f"proven by {entry.dataset}" if proven else f"unproven ({entry.dataset})"
    return f"- {entry.name} ({', '.join(entry.phases)}): {proof}; tools: {names}"


def _tool_lines(tools: Mapping[str, Sequence[ToolDescriptionLike]]) -> list[str]:
    """Every distinct tool any agent has, once, with what it does."""
    described = {
        tool.name: tool.description for entry_tools in tools.values() for tool in entry_tools
    }
    return [f"- {name}: {described[name]}" for name in sorted(described)]


def _capability_line(page: CapabilityPageLike) -> str:
    """One learned capability: the dataset that proves it and the commit that added it."""
    return f"- {page.name}: {page.dataset or 'no dataset'} (commit {page.commit or 'unknown'})"


def frontier_line(ratio: FrontierRatio) -> str:
    """One frontier capability: how much of its ladder is green and the rung to climb next."""
    standing = "available" if ratio.available else f"next rung {ratio.lowest_red_rung}"
    return f"- {ratio.capability}: {ratio.green}/{ratio.total}, {standing}"


def _block(heading: str, lines: Sequence[str], empty: str = "- (none)") -> str:
    """One markdown section: its heading and its lines, or `empty` when there are none."""
    return f"{heading}\n\n" + ("\n".join(lines) or empty)


def render_inventory(
    registry: Registry,
    report: EvalReport | None,
    ratios: list[FrontierRatio],
    capabilities: Sequence[CapabilityPageLike],
    tools: Mapping[str, Sequence[ToolDescriptionLike]],
    cases: Mapping[str, Sequence[str]],
) -> str:
    """The Capability Inventory: the agents, their tools, the Wiki's capability pages, and the
    frontier. A required role is always listed, proven or not; a Specialist is listed only once
    its dataset is green (ADR 0007)."""
    specialists = {entry.name for entry in registry.specialists}
    agent_lines = []
    for entry in registry.entries:
        proven = _is_proven(report, entry, cases)
        if entry.name in specialists and not proven:
            continue
        agent_lines.append(_agent_line(entry, proven, tools.get(entry.name, [])))
    blocks = [
        INVENTORY_HEADING,
        _block("### Agents", agent_lines),
        _block("### Tools", _tool_lines(tools)),
        _block("### Learned capabilities", [_capability_line(page) for page in capabilities]),
        _block("### Frontier", [frontier_line(ratio) for ratio in ratios]),
    ]
    return "\n\n".join(blocks) + "\n"


def _top_level_line(entry: Path, root: Path) -> str:
    """One top-level entry, marked editable when a tool may write inside it."""
    scope = "editable" if is_writable(entry.name, root) else "read-only"
    name = f"{entry.name}/" if entry.is_dir() else entry.name
    return f"- {name} ({scope})"


def _writable_files(root: Path) -> list[str]:
    """Every file under the write scope as a repo-relative POSIX path, one directory at a time."""
    files: list[str] = []
    for directory in WRITABLE_DIRS:
        base = root / directory
        if not base.is_dir():
            continue
        files += [
            path.relative_to(root).as_posix()
            for path in sorted(base.rglob("*"))
            if path.is_file()
            and path.name not in SKIPPED_FILES
            and not set(path.relative_to(root).parts) & SKIPPED_ENTRIES
        ]
    return files


def render_tree(root: Path) -> str:
    """The repo as the agents see it: the top-level entries and the write scope below them."""
    lines = [
        _top_level_line(entry, root)
        for entry in sorted(root.iterdir(), key=lambda path: path.name)
        if entry.name not in SKIPPED_ENTRIES
    ]
    lines += [f"  - {path} (editable)" for path in _writable_files(root)]
    return "\n".join(lines) + "\n"


def _position_lines(position: LoopPosition) -> list[str]:
    """The Loop position: the run, the Mode, the Iteration, the phase, the role, and the Gate."""
    return [
        f"Run: {position.run_id}",
        f"Mode: {position.mode}",
        f"Iteration: {position.iteration} of {position.iteration_limit}",
        f"Phase: {position.phase}",
        f"Role: {position.role}",
        f"Previous Gate: {position.previous_gate or 'none'}",
    ]


def finding_line(finding: SensorFinding) -> str:
    """One open Sensor Finding: its severity, its id, and what it says."""
    return f"- [{finding.severity}] {finding.id}: {finding.summary}"


def run_line(record: RunRecord) -> str:
    """One recent run: its Mode, how it ended, how many Iterations it took, and what it cost."""
    return (
        f"- {record.run_id}: {record.mode}, {record.outcome or 'running'}, "
        f"{len(record.iterations)} Iterations, {record.total_usage.cost_usd} USD"
    )


def render_bundle(
    position: LoopPosition,
    *,
    inventory: str,
    tree: str,
    eval_summary: list[str],
    findings: list[SensorFinding],
    wiki_index: str,
    runs: list[RunRecord],
) -> str:
    """The State Bundle: where the agent stands, what the system can do, and what it knows."""
    blocks = [
        _block("## Loop position", _position_lines(position)),
        inventory.strip("\n"),
        _block("## Repository", tree.strip("\n").splitlines(), "(none)"),
        _block("## Evals", eval_summary, "(no report)"),
        _block(
            "## Open Sensor Findings",
            [finding_line(finding) for finding in findings[:MAX_FINDINGS]],
            "(none)",
        ),
        _block("## Wiki index", wiki_index.strip("\n").splitlines(), "(none)"),
        _block("## Recent runs", [run_line(record) for record in runs[-MAX_RUNS:]], "(none)"),
    ]
    return "\n\n".join(blocks) + "\n"


def _frontier_dir(root: Path) -> Path:
    """Where the frontier ladders live under `root`, so a scratch checkout works the same way."""
    return root / EVALS_ROOT_DIRNAME / FRONTIER_DIRNAME


def assemble_state_bundle(
    position: LoopPosition,
    *,
    root: Path,
    ra_dir: Path,
    registry: Registry,
    wiki: WikiReader,
    budget_usd: Decimal,
) -> str:
    """The whole State Bundle for one agent call: the one composer, and it calls no model.

    The runtime directory gives the latest eval report, the open findings, and the Run Records;
    the checkout gives the tree and the tools every registry entry really has; the Wiki gives its
    capability pages and its index.
    """
    # Imported here so the Kernel package never depends on the Organism at import time.
    from recursive_application.organism.tools import describe_tools

    frontier = _frontier_dir(root)
    report = ReportStore(ra_dir / EVALS_DIRNAME).load_latest()
    inventory = render_inventory(
        registry,
        report,
        frontier_ratios(frontier, report),
        wiki.list_capabilities(),
        {entry.name: describe_tools(entry.tools, root) for entry in registry.entries},
        dataset_cases(registry, root),
    )
    return render_bundle(
        position,
        inventory=inventory,
        tree=render_tree(root),
        eval_summary=report.summary_lines() if report is not None else [],
        findings=collect(ra_dir=ra_dir, wiki=wiki, frontier_dir=frontier, budget_usd=budget_usd),
        wiki_index=wiki.index_text(),
        runs=RunStore(ra_dir / RUNS_DIRNAME).list_all(),
    )
