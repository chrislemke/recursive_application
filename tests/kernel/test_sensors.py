"""The Sensors, exercised over synthetic reports, spans, runs, feedback, and a Wiki.

Every Sensor function is pure over its inputs, so the reports, spans, and runs are built by
hand here; `collect` reads a runtime directory and a Wiki under `tmp_path`.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from recursive_application.kernel.evals import (
    EVALS_DIR,
    CaseResult,
    EvalReport,
    ReportStore,
    frontier_ratios,
)
from recursive_application.kernel.paths import ensure_ra_dirs
from recursive_application.kernel.records import (
    IterationRecord,
    Mode,
    RunRecord,
    RunStore,
    SensorFinding,
    Usage,
)
from recursive_application.kernel.sensors import (
    FEEDBACK_FILENAME,
    FINDINGS_FILENAME,
    FeedbackEntry,
    FeedbackStore,
    FindingStore,
    collect,
    eval_findings,
    feedback_findings,
    stored_findings,
    trace_findings,
    wiki_findings,
)
from recursive_application.organism.wiki import (
    OpenQuestion,
    Wiki,
)

FRONTIER_DIR = EVALS_DIR / "frontier"


def _report(cases: dict[str, bool]) -> EvalReport:
    """A report whose cases are `<dataset>/<name>` keys mapped to whether they passed."""
    return EvalReport(
        created_at=datetime(2026, 9, 5, 14, 15, tzinfo=UTC),
        datasets=sorted({key.rsplit("/", 1)[0] for key in cases}),
        cases=[
            CaseResult(dataset=key.rsplit("/", 1)[0], name=key.rsplit("/", 1)[1], passed=passed)
            for key, passed in cases.items()
        ],
    )


def test_eval_findings_names_every_red_case_and_one_finding_per_unproven_capability() -> None:
    report = _report(
        {
            "triage/a": False,
            "triage/b": True,
            "frontier/repo-history/repo-history-1-first-commit": True,
            "frontier/repo-history/repo-history-2-files-in-first-commit": True,
        }
    )

    findings = eval_findings(report, frontier_ratios(FRONTIER_DIR, report))

    assert [finding.id for finding in findings] == [
        "evals:triage/a",
        "evals:frontier/repo-history",
        "evals:frontier/text-analysis",
        "evals:frontier/web-research",
    ]
    assert "capability: repo-history" in findings[1].details
    assert "rung: 3" in findings[1].details
    assert findings[1].severity == "medium"
    assert findings[0].severity == "high"
    assert findings[0].source == "evals"


def test_eval_findings_without_a_report_names_every_frontier_capability_and_nothing_else() -> None:
    findings = eval_findings(None, frontier_ratios(FRONTIER_DIR, None))

    assert [finding.id for finding in findings] == [
        "evals:frontier/repo-history",
        "evals:frontier/text-analysis",
        "evals:frontier/web-research",
    ]
    assert [finding.details for finding in findings] == [
        "capability: repo-history\nrung: 1",
        "capability: text-analysis\nrung: 1",
        "capability: web-research\nrung: 1",
    ]


def _span(
    name: str, *, status: str = "OK", attributes: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A span record in the Trace Store's schema, carrying only what the rules read."""
    return {
        "trace_id": "0" * 32,
        "span_id": "0" * 16,
        "parent_span_id": None,
        "name": name,
        "start_ns": 0,
        "end_ns": 1_000_000,
        "duration_ms": 1.0,
        "status": status,
        "status_description": None,
        "attributes": attributes or {},
    }


def test_trace_findings_reports_an_error_span_once_for_the_run_that_holds_it() -> None:
    spans = [
        _span("chat gpt-5"),
        _span("execute_tool read_file", status="ERROR"),
        _span("kernel.agent_run", status="ERROR"),
    ]

    findings = trace_findings({"20260905-141500-aa11bb": spans}, [], Decimal("5"))

    assert [finding.id for finding in findings] == ["traces:20260905-141500-aa11bb:error-span"]
    assert findings[0].severity == "high"
    assert findings[0].source == "traces"


def _tool_call(arguments: str) -> dict[str, Any]:
    """A pydantic-ai tool span for `read_file` called with `arguments`."""
    return _span(
        "execute_tool read_file",
        attributes={
            "gen_ai.tool.name": "read_file",
            "gen_ai.tool.call.arguments": arguments,
        },
    )


def test_trace_findings_reports_the_same_tool_call_three_times_but_not_twice() -> None:
    same = '{"path": "README.md"}'
    other = '{"path": "CONTEXT.md"}'

    findings = trace_findings(
        {
            "run-three": [_tool_call(same), _tool_call(same), _tool_call(same)],
            "run-two": [_tool_call(same), _tool_call(same), _tool_call(other)],
        },
        [],
        Decimal("5"),
    )

    assert [finding.id for finding in findings] == ["traces:run-three:repeated-tool-call"]
    assert findings[0].severity == "medium"
    assert "read_file" in findings[0].summary


def test_trace_findings_reports_two_validation_retries_on_an_agent_run_span_but_not_one() -> None:
    findings = trace_findings(
        {
            "run-two-retries": [
                _span("kernel.agent_run", attributes={"validation_retries": 2}),
            ],
            "run-one-retry": [
                _span("kernel.agent_run", attributes={"validation_retries": 1}),
            ],
        },
        [],
        Decimal("5"),
    )

    assert [finding.id for finding in findings] == ["traces:run-two-retries:validation-retries"]
    assert findings[0].severity == "medium"
    assert "retries: 2" in findings[0].details


FIRST_RUN_AT = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


def _run(run_id: str, *, started_at: datetime, seconds: float, cost: str = "0") -> RunRecord:
    """A finished Answer run of `seconds` whose single Iteration cost `cost`."""
    return RunRecord(
        run_id=run_id,
        mode=Mode.ANSWER,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=seconds),
        iterations=[IterationRecord(number=1, usage=Usage(cost_usd=Decimal(cost)))],
        outcome="accepted",
    )


def _runs_ending_with(latest_seconds: float) -> list[RunRecord]:
    """Twenty-one finished runs of sixty seconds, then a latest one of `latest_seconds`."""
    runs = [
        _run(f"run-{index:02d}", started_at=FIRST_RUN_AT + timedelta(minutes=index), seconds=60)
        for index in range(21)
    ]
    runs.append(
        _run("run-latest", started_at=FIRST_RUN_AT + timedelta(minutes=30), seconds=latest_seconds)
    )
    return runs


def test_trace_findings_reports_the_latest_run_when_it_runs_past_twice_the_median() -> None:
    slow = trace_findings({}, _runs_ending_with(200), Decimal("5"))

    assert [finding.id for finding in slow] == ["traces:run-latest:slow-run"]
    assert slow[0].severity == "low"
    assert trace_findings({}, _runs_ending_with(100), Decimal("5")) == []


def test_trace_findings_reports_a_run_that_spent_more_than_four_fifths_of_the_budget() -> None:
    costly = _run("run-costly", started_at=FIRST_RUN_AT, seconds=60, cost="4.5")
    affordable = _run("run-affordable", started_at=FIRST_RUN_AT, seconds=60, cost="3.5")

    findings = trace_findings({}, [costly], Decimal("5"))

    assert [finding.id for finding in findings] == ["traces:run-costly:costly-run"]
    assert findings[0].severity == "high"
    assert trace_findings({}, [affordable], Decimal("5")) == []


def test_feedback_store_reads_back_what_it_appended_and_nothing_for_a_missing_file(
    tmp_path: Path,
) -> None:
    store = FeedbackStore(tmp_path / FEEDBACK_FILENAME)
    assert store.list_all() == []

    store.append(FeedbackEntry(run_id="run-praised", at=FIRST_RUN_AT, positive=True))
    store.append(
        FeedbackEntry(
            run_id="run-scolded", at=FIRST_RUN_AT, positive=False, comment="It read the wrong file"
        )
    )

    assert [
        (entry.run_id, entry.positive, entry.comment, entry.addressed) for entry in store.list_all()
    ] == [
        ("run-praised", True, "", False),
        ("run-scolded", False, "It read the wrong file", False),
    ]


def test_feedback_findings_names_the_negative_entry_and_skips_the_positive_one() -> None:
    findings = feedback_findings(
        [
            FeedbackEntry(run_id="run-praised", at=FIRST_RUN_AT, positive=True, comment="Spot on"),
            FeedbackEntry(
                run_id="run-scolded",
                at=FIRST_RUN_AT,
                positive=False,
                comment="It read the wrong file",
            ),
        ]
    )

    assert [finding.id for finding in findings] == ["feedback:run-scolded"]
    assert findings[0].source == "feedback"
    assert findings[0].severity == "high"
    assert "It read the wrong file" in findings[0].details


def test_feedback_marked_addressed_stops_being_a_finding_and_leaves_the_others_alone(
    tmp_path: Path,
) -> None:
    store = FeedbackStore(tmp_path / FEEDBACK_FILENAME)
    store.append(
        FeedbackEntry(run_id="run-scolded", at=FIRST_RUN_AT, positive=False, comment="Wrong file")
    )
    store.append(
        FeedbackEntry(run_id="run-ignored", at=FIRST_RUN_AT, positive=False, comment="Too slow")
    )

    store.mark_addressed(["run-scolded"])

    assert [entry.addressed for entry in store.list_all()] == [True, False]
    assert [finding.id for finding in feedback_findings(store.list_all())] == [
        "feedback:run-ignored"
    ]


def test_wiki_findings_names_every_open_question_and_the_capability_a_proposal_carries() -> None:
    findings = wiki_findings(
        [
            OpenQuestion(
                "pages/open-questions/next-frontier-text-analysis.md",
                "Next rungs for text-analysis",
                "text-analysis",
            ),
            OpenQuestion("pages/open-questions/why-flaky.md", "Why is answers flaky?", None),
        ]
    )

    assert [finding.id for finding in findings] == [
        "wiki:pages/open-questions/next-frontier-text-analysis.md",
        "wiki:pages/open-questions/why-flaky.md",
    ]
    assert [finding.summary for finding in findings] == [
        "Wiki proposes harder rungs for the capability text-analysis: Next rungs for text-analysis",
        "Wiki open question: Why is answers flaky?",
    ]
    assert [finding.details for finding in findings] == ["capability: text-analysis", ""]
    assert [finding.severity for finding in findings] == ["low", "low"]
    assert [finding.source for finding in findings] == ["wiki", "wiki"]


def test_finding_store_reads_back_the_findings_the_kernel_wrote_during_a_run(
    tmp_path: Path,
) -> None:
    store = FindingStore(tmp_path / FINDINGS_FILENAME)
    assert stored_findings(store) == []

    unmet_gap = SensorFinding(
        id="reflection:r1:gap-1",
        source="reflection",
        summary="Triage saw a tool gap that no Iteration acted on",
        details="kind: tool",
    )
    store.append(unmet_gap, FIRST_RUN_AT)

    assert stored_findings(store) == [unmet_gap]
    assert store.list_all() == [(unmet_gap, FIRST_RUN_AT)]


def test_collect_ranks_every_open_finding_by_severity_and_drops_the_addressed_ones(
    tmp_path: Path,
) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)
    ReportStore(ra_dir / "evals").save(_report({"triage/a": False}))
    RunStore(ra_dir / "runs").save(
        RunRecord(
            run_id="run-scolded",
            mode=Mode.ANSWER,
            started_at=FIRST_RUN_AT + timedelta(hours=5),
            finished_at=FIRST_RUN_AT + timedelta(hours=5, seconds=60),
            findings_addressed=["evals:triage/a"],
        )
    )
    FeedbackStore(ra_dir / FEEDBACK_FILENAME).append(
        FeedbackEntry(
            run_id="run-scolded", at=FIRST_RUN_AT, positive=False, comment="It read the wrong file"
        )
    )
    FindingStore(ra_dir / FINDINGS_FILENAME).append(
        SensorFinding(
            id="policy:run-scolded:kernel-edit",
            source="policy",
            summary="The Planner wished to edit a Protected Path",
            severity="low",
        ),
        FIRST_RUN_AT,
    )
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    findings = collect(ra_dir=ra_dir, wiki=wiki, frontier_dir=FRONTIER_DIR, budget_usd=Decimal("5"))

    assert [finding.id for finding in findings] == [
        "feedback:run-scolded",
        "evals:frontier/repo-history",
        "evals:frontier/text-analysis",
        "evals:frontier/web-research",
        "policy:run-scolded:kernel-edit",
    ]
    assert [finding.severity for finding in findings] == [
        "high",
        "medium",
        "medium",
        "medium",
        "low",
    ]


def test_collect_puts_the_older_of_two_findings_of_the_same_severity_first(
    tmp_path: Path,
) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)
    store = FeedbackStore(ra_dir / FEEDBACK_FILENAME)
    store.append(
        FeedbackEntry(run_id="run-today", at=FIRST_RUN_AT, positive=False, comment="Too slow")
    )
    store.append(
        FeedbackEntry(
            run_id="run-yesterday",
            at=FIRST_RUN_AT - timedelta(days=1),
            positive=False,
            comment="Wrong file",
        )
    )
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    findings = collect(ra_dir=ra_dir, wiki=wiki, frontier_dir=FRONTIER_DIR, budget_usd=Decimal("5"))

    assert [finding.id for finding in findings[:2]] == [
        "feedback:run-yesterday",
        "feedback:run-today",
    ]


def test_a_case_fixed_once_but_red_in_a_newer_report_is_a_finding_again(tmp_path: Path) -> None:
    ra_dir = ensure_ra_dirs(tmp_path)
    reports = ReportStore(ra_dir / "evals")
    red = [CaseResult(dataset="triage", name="a", passed=False)]
    reports.save(
        EvalReport(
            created_at=FIRST_RUN_AT - timedelta(days=1),
            run_id="before",
            datasets=["triage"],
            cases=red,
        )
    )
    RunStore(ra_dir / "runs").save(
        RunRecord(
            run_id="fixer",
            mode=Mode.GROWTH,
            started_at=FIRST_RUN_AT,
            finished_at=FIRST_RUN_AT + timedelta(seconds=60),
            findings_addressed=["evals:triage/a"],
        )
    )
    reports.save(
        EvalReport(
            created_at=FIRST_RUN_AT + timedelta(days=1),
            run_id="after",
            datasets=["triage"],
            cases=red,
        )
    )
    wiki = Wiki(tmp_path / "wiki")
    wiki.ensure_layout()

    findings = collect(ra_dir=ra_dir, wiki=wiki, frontier_dir=FRONTIER_DIR, budget_usd=Decimal("5"))

    assert "evals:triage/a" in [finding.id for finding in findings]
