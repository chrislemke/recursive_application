"""The Sensors: deterministic evidence the Kernel gathers at Sense.

Each Sensor is a pure function over data someone else read, so a rule can be exercised with
a literal report, span, or feedback entry; `collect` is the one call that touches the runtime
directory and the Wiki, ranks every finding by severity and then by age, and drops the ones a
Run Record already addressed.
"""

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from recursive_application.kernel.evals import (
    EvalReport,
    FrontierRatio,
    ReportStore,
    frontier_ratios,
)
from recursive_application.kernel.paths import EVALS_DIRNAME, RUNS_DIRNAME, TRACES_DIRNAME
from recursive_application.kernel.records import Contract, RunRecord, RunStore, SensorFinding
from recursive_application.kernel.tracing import read_spans
from recursive_application.kernel.wiki_protocol import OpenQuestionLike, WikiReader

FEEDBACK_FILENAME = "feedback.jsonl"
"""The JSON lines file under the runtime directory holding the human's feedback."""

FINDINGS_FILENAME = "findings.jsonl"
"""The JSON lines file holding the findings the Kernel wrote while runs were going on."""

FRONTIER_PREFIX = "frontier/"
"""The dataset-name prefix of a Frontier Case ladder."""

TRACES_SUBDIR, RUNS_SUBDIR, REPORTS_SUBDIR = TRACES_DIRNAME, RUNS_DIRNAME, EVALS_DIRNAME
"""The runtime subdirectories `collect` reads, named by the path rule."""

SEVERITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
"""How the ranking orders severities: the most severe finding comes first."""

UNDATED = datetime.min.replace(tzinfo=UTC)
"""The age of a finding whose report, run, or page is gone: as old as the system gets."""

REPEATED_TOOL_CALLS = 3
"""How often one tool call may repeat in a run before it is an anomaly."""

TOOL_NAME_ATTRIBUTE = "gen_ai.tool.name"
"""The span attribute naming the tool a tool span ran."""

TOOL_ARGUMENTS_ATTRIBUTE = "gen_ai.tool.call.arguments"
"""The span attribute holding the arguments a tool span was called with."""

VALIDATION_RETRIES = 2
"""How many output-validation retries a run may take before it is an anomaly."""

VALIDATION_RETRIES_ATTRIBUTE = "validation_retries"
"""The attribute the agent runtime writes on its own span; a retry emits no span of its own."""

RECENT_RUNS = 20
"""How many finished runs the slow-run rule takes the median of."""

SLOW_RUN_FACTOR = 2.0
"""How far past that median the latest run may go before it is an anomaly."""

COSTLY_RUN_SHARE = Decimal("0.8")
"""How much of the budget one run may spend before it is an anomaly."""


def eval_findings(report: EvalReport | None, ratios: list[FrontierRatio]) -> list[SensorFinding]:
    """One finding per red non-frontier case, then one per capability that is not proven."""
    findings = [
        SensorFinding(
            id=f"evals:{result.dataset}/{result.name}",
            source="evals",
            summary=f"Eval case {result.dataset}/{result.name} is red",
            details="\n".join(result.reasons),
            severity="high",
        )
        for result in (report.cases if report is not None else [])
        if not result.passed and not result.dataset.startswith(FRONTIER_PREFIX)
    ]
    findings += [
        SensorFinding(
            id=f"evals:{FRONTIER_PREFIX}{ratio.capability}",
            source="evals",
            summary=(
                f"Frontier capability {ratio.capability} is red at rung {ratio.lowest_red_rung} "
                f"({ratio.green}/{ratio.total} rungs green)"
            ),
            details=f"capability: {ratio.capability}\nrung: {ratio.lowest_red_rung}",
            severity="medium",
        )
        for ratio in ratios
        if not ratio.available
    ]
    return findings


def trace_findings(
    spans_by_run: Mapping[str, list[dict[str, Any]]],
    runs: list[RunRecord],
    budget_usd: Decimal,
) -> list[SensorFinding]:
    """The trace anomalies of every run, each rule firing at most once per run."""
    findings: list[SensorFinding] = []
    for run_id, spans in spans_by_run.items():
        if any(span.get("status") == "ERROR" for span in spans):
            findings.append(
                SensorFinding(
                    id=f"traces:{run_id}:error-span",
                    source="traces",
                    summary=f"Run {run_id} has a span that ended in an error",
                    details="\n".join(
                        f"{span.get('name')}: {span.get('status_description') or 'no description'}"
                        for span in spans
                        if span.get("status") == "ERROR"
                    ),
                    severity="high",
                )
            )
        repeated = _repeated_tool_calls(spans)
        if repeated is not None:
            tool, arguments, count = repeated
            findings.append(
                SensorFinding(
                    id=f"traces:{run_id}:repeated-tool-call",
                    source="traces",
                    summary=(
                        f"Run {run_id} called the tool {tool} {count} times "
                        f"with one set of arguments"
                    ),
                    details=f"tool: {tool}\narguments: {arguments}\ncalls: {count}",
                    severity="medium",
                )
            )
        retries = _validation_retries(spans)
        if retries >= VALIDATION_RETRIES:
            findings.append(
                SensorFinding(
                    id=f"traces:{run_id}:validation-retries",
                    source="traces",
                    summary=f"Run {run_id} needed {retries} output-validation retries",
                    details=f"retries: {retries}",
                    severity="medium",
                )
            )
    slow = _slow_run(runs)
    if slow is not None:
        run, duration, middle = slow
        findings.append(
            SensorFinding(
                id=f"traces:{run.run_id}:slow-run",
                source="traces",
                summary=(
                    f"Run {run.run_id} took {duration:.0f} seconds, more than "
                    f"{SLOW_RUN_FACTOR} times the median of {middle:.0f}"
                ),
                details=f"seconds: {duration:.0f}\nmedian_seconds: {middle:.0f}",
                severity="low",
            )
        )
    findings += [
        SensorFinding(
            id=f"traces:{run.run_id}:costly-run",
            source="traces",
            summary=(
                f"Run {run.run_id} spent {run.total_usage.cost_usd} USD of a "
                f"{budget_usd} USD budget"
            ),
            details=f"cost_usd: {run.total_usage.cost_usd}\nbudget_usd: {budget_usd}",
            severity="high",
        )
        for run in runs
        if run.total_usage.cost_usd > COSTLY_RUN_SHARE * budget_usd
    ]
    return findings


def _duration_seconds(run: RunRecord) -> float | None:
    """How long the run took, or `None` while it has not finished."""
    if run.finished_at is None:
        return None
    return (run.finished_at - run.started_at).total_seconds()


def _slow_run(runs: list[RunRecord]) -> tuple[RunRecord, float, float] | None:
    """The latest finished run when it runs past `SLOW_RUN_FACTOR` times the recent median."""
    finished = sorted(
        (run for run in runs if _duration_seconds(run) is not None),
        key=lambda run: (run.started_at, run.run_id),
    )
    recent = finished[-RECENT_RUNS:]
    if len(recent) < 3:
        return None
    durations = [seconds for run in recent if (seconds := _duration_seconds(run)) is not None]
    middle = median(durations)
    latest, duration = recent[-1], durations[-1]
    return (latest, duration, middle) if duration > SLOW_RUN_FACTOR * middle else None


def _validation_retries(spans: list[dict[str, Any]]) -> int:
    """The highest retry count any span of the run reports; `0` when none carries one."""
    return max(
        (
            int((span.get("attributes") or {}).get(VALIDATION_RETRIES_ATTRIBUTE, 0))
            for span in spans
        ),
        default=0,
    )


def _repeated_tool_calls(spans: list[dict[str, Any]]) -> tuple[str, str, int] | None:
    """The first tool call repeated `REPEATED_TOOL_CALLS` times or more, in span order."""
    counted: Counter[tuple[str, str]] = Counter()
    for span in spans:
        attributes = span.get("attributes") or {}
        if TOOL_NAME_ATTRIBUTE in attributes:
            counted[
                (attributes[TOOL_NAME_ATTRIBUTE], attributes.get(TOOL_ARGUMENTS_ATTRIBUTE, ""))
            ] += 1
    for (tool, arguments), count in counted.items():
        if count >= REPEATED_TOOL_CALLS:
            return tool, arguments, count
    return None


class FeedbackEntry(Contract):
    """One verdict the human gave on a finished run."""

    run_id: str
    at: datetime
    positive: bool
    comment: str = ""
    addressed: bool = False


class FeedbackStore:
    """The human's feedback as one JSON line per entry, in the order it was given."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, entry: FeedbackEntry) -> None:
        """Add one entry as a JSON line; earlier lines are never touched."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(entry.model_dump_json() + "\n")

    def list_all(self) -> list[FeedbackEntry]:
        """Every entry in the order it was appended; `[]` when the file does not exist."""
        return [FeedbackEntry.model_validate_json(line) for line in _json_lines(self.path)]

    def mark_addressed(self, run_ids: Iterable[str]) -> None:
        """Rewrite the file with the entries of `run_ids` flagged as addressed."""
        wanted = set(run_ids)
        entries = [
            entry.model_copy(update={"addressed": True}) if entry.run_id in wanted else entry
            for entry in self.list_all()
        ]
        self.path.write_text(
            "".join(entry.model_dump_json() + "\n" for entry in entries), encoding="utf-8"
        )


def feedback_findings(entries: list[FeedbackEntry]) -> list[SensorFinding]:
    """One finding per negative entry the human has not seen addressed yet."""
    return [
        SensorFinding(
            id=f"feedback:{entry.run_id}",
            source="feedback",
            summary=f"The human rejected the output of run {entry.run_id}",
            details=entry.comment,
            severity="high",
        )
        for entry in entries
        if not entry.positive and not entry.addressed
    ]


class FindingStore:
    """The `reflection` and `policy` findings the Kernel wrote during runs, one JSON line each."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, finding: SensorFinding, at: datetime) -> None:
        """Add one finding and the moment it was recorded; earlier lines are never touched."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({**finding.model_dump(mode="json"), "at": at.isoformat()})
        with self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    def list_all(self) -> list[tuple[SensorFinding, datetime]]:
        """Every stored finding with its timestamp; `[]` when the file does not exist."""
        stored = []
        for line in _json_lines(self.path):
            record = json.loads(line)
            at = datetime.fromisoformat(record.pop("at"))
            stored.append((SensorFinding.model_validate(record), at))
        return stored


def stored_findings(store: FindingStore) -> list[SensorFinding]:
    """The findings the Kernel recorded during runs, as they were written."""
    return [finding for finding, _ in store.list_all()]


def wiki_findings(questions: Sequence[OpenQuestionLike]) -> list[SensorFinding]:
    """One finding per open question in the Wiki, a frontier proposal naming its capability."""
    return [
        SensorFinding(
            id=f"wiki:{question.path}",
            source="wiki",
            summary=(
                f"Wiki proposes harder rungs for the capability {question.capability}: "
                f"{question.title}"
                if question.capability is not None
                else f"Wiki open question: {question.title}"
            ),
            details=f"capability: {question.capability}" if question.capability else "",
            severity="low",
        )
        for question in questions
    ]


def _json_lines(path: Path) -> list[str]:
    """The non-blank lines of a JSON lines file; `[]` when the file does not exist."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect(
    *, ra_dir: Path, wiki: WikiReader, frontier_dir: Path, budget_usd: Decimal
) -> list[SensorFinding]:
    """Every open Sensor Finding of one runtime directory and Wiki, most severe and oldest first.

    A finding a Run Record names in `findings_addressed` is left out only while its evidence
    is older than that run: a case fixed once and red again in a newer report is a finding
    again. The rest are ranked by severity, then by the age of the evidence behind them.
    """
    report = ReportStore(ra_dir / REPORTS_SUBDIR).load_latest()
    runs = RunStore(ra_dir / RUNS_SUBDIR).list_all()
    spans_by_run = {
        path.stem: read_spans(path) for path in sorted((ra_dir / TRACES_SUBDIR).glob("*.jsonl"))
    }
    feedback = FeedbackStore(ra_dir / FEEDBACK_FILENAME).list_all()
    questions = wiki.list_open_questions()

    report_age = _as_utc(report.created_at) if report is not None else UNDATED
    run_ages = {run.run_id: _as_utc(run.started_at) for run in runs}
    feedback_ages = {f"feedback:{entry.run_id}": _as_utc(entry.at) for entry in feedback}
    wiki_ages = {f"wiki:{question.path}": _page_age(wiki, question) for question in questions}

    dated: list[tuple[SensorFinding, datetime]] = [
        (finding, report_age)
        for finding in eval_findings(report, frontier_ratios(frontier_dir, report))
    ]
    dated += [
        (finding, run_ages.get(finding.id.split(":")[1], UNDATED))
        for finding in trace_findings(spans_by_run, runs, budget_usd)
    ]
    dated += [(finding, feedback_ages[finding.id]) for finding in feedback_findings(feedback)]
    dated += [(finding, wiki_ages[finding.id]) for finding in wiki_findings(questions)]
    dated += [
        (finding, _as_utc(at))
        for finding, at in FindingStore(ra_dir / FINDINGS_FILENAME).list_all()
    ]

    addressed_at: dict[str, datetime] = {}
    for run in runs:
        for finding_id in run.findings_addressed:
            started = _as_utc(run.started_at)
            addressed_at[finding_id] = max(addressed_at.get(finding_id, UNDATED), started)
    open_findings = [
        (finding, age)
        for finding, age in dated
        if finding.id not in addressed_at or addressed_at[finding.id] < age
    ]
    return [
        finding
        for finding, _ in sorted(
            open_findings, key=lambda pair: (SEVERITY_RANK[pair[0].severity], pair[1])
        )
    ]


def _page_age(wiki: WikiReader, question: OpenQuestionLike) -> datetime:
    """When the Wiki page behind an open question was last written."""
    page = wiki.root / question.path
    if not page.exists():
        return UNDATED
    return datetime.fromtimestamp(page.stat().st_mtime, UTC)


def _as_utc(moment: datetime) -> datetime:
    """The same moment in UTC, so a stored timestamp without a zone still compares."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
