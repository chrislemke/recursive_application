"""Eval datasets, reports, deltas, and frontier ratios.

Exercised against the seeded Frontier Cases under `evals/frontier/` and probe datasets
written under `tmp_path`. No model is called: the probes evaluate a plain function.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from recursive_application.kernel.evals import (
    EVALS_DIR,
    CaseResult,
    DatasetError,
    EvalReport,
    FrontierCase,
    ReportStore,
    changed_eval_cases,
    compare,
    dataset_name,
    frontier_ratios,
    list_datasets,
    load_dataset,
    results_from,
    validate_frontier,
)


def test_list_datasets_returns_the_seeded_frontier_files_in_sorted_order() -> None:
    frontier = [path for path in list_datasets(EVALS_DIR) if path.parent.name == "frontier"]

    assert frontier == [
        EVALS_DIR / "frontier" / "repo-history.yaml",
        EVALS_DIR / "frontier" / "text-analysis.yaml",
        EVALS_DIR / "frontier" / "web-research.yaml",
    ]


def test_dataset_name_is_the_path_below_the_evals_directory_without_the_extension() -> None:
    assert dataset_name(EVALS_DIR / "frontier" / "text-analysis.yaml") == "frontier/text-analysis"
    assert dataset_name(EVALS_DIR / "triage.yaml") == "triage"


def test_load_dataset_reads_each_seeded_frontier_ladder_with_its_rungs_as_cases() -> None:
    frontier = EVALS_DIR / "frontier"

    assert len(load_dataset(frontier / "text-analysis.yaml").cases) == 5
    assert len(load_dataset(frontier / "repo-history.yaml").cases) == 4
    assert len(load_dataset(frontier / "web-research.yaml").cases) == 3


def test_load_dataset_raises_a_dataset_error_naming_a_file_that_breaks_the_schema(
    tmp_path: Path,
) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("cases:\n  - name: a\n    evaluators:\n      - NoSuchEvaluator: x\n")

    with pytest.raises(DatasetError) as raised:
        load_dataset(path)

    assert "broken.yaml" in str(raised.value)


def test_validate_frontier_reads_the_ladder_of_every_seeded_capability() -> None:
    frontier = EVALS_DIR / "frontier"

    text_analysis = validate_frontier(frontier / "text-analysis.yaml")
    repo_history = validate_frontier(frontier / "repo-history.yaml")
    web_research = validate_frontier(frontier / "web-research.yaml")

    assert [case.rung for case in text_analysis] == [1, 2, 3, 4, 5]
    assert [case.rung for case in repo_history] == [1, 2, 3, 4]
    assert [case.rung for case in web_research] == [1, 2, 3]
    assert {case.capability for case in text_analysis} == {"text-analysis"}
    assert {case.gap_kind for case in text_analysis} == {"skill"}
    assert {case.gap_kind for case in repo_history} == {"tool"}
    assert {case.gap_kind for case in web_research} == {"connection"}
    assert repo_history[0] == FrontierCase(
        name="repo-history-1-first-commit", capability="repo-history", rung=1, gap_kind="tool"
    )
    assert web_research[0].needs_human == ["network access"]


def test_validate_frontier_refuses_a_ladder_whose_rungs_skip_a_number(tmp_path: Path) -> None:
    path = tmp_path / "probe-ladder.yaml"
    path.write_text(
        "cases:\n"
        "  - name: probe-1\n"
        "    inputs: one\n"
        "    metadata: {tier: frontier, capability: probe-ladder, rung: 1, gap_kind: skill}\n"
        "  - name: probe-2\n"
        "    inputs: two\n"
        "    metadata: {tier: frontier, capability: probe-ladder, rung: 3, gap_kind: skill}\n"
    )

    with pytest.raises(DatasetError) as raised:
        validate_frontier(path)

    assert "probe-2" in str(raised.value)
    assert "rung" in str(raised.value)


def test_validate_frontier_refuses_a_case_whose_metadata_omits_the_gap_kind(
    tmp_path: Path,
) -> None:
    path = tmp_path / "probe-ladder.yaml"
    path.write_text(
        "cases:\n"
        "  - name: probe-1\n"
        "    inputs: one\n"
        "    metadata: {tier: frontier, capability: probe-ladder, rung: 1}\n"
    )

    with pytest.raises(DatasetError) as raised:
        validate_frontier(path)

    assert "probe-1" in str(raised.value)
    assert "gap_kind" in str(raised.value)


@pytest.mark.parametrize(
    ("metadata", "fault"),
    [
        ("{tier: frontier, capability: elsewhere, rung: 1, gap_kind: skill}", "capability"),
        ("{tier: target, capability: probe-ladder, rung: 1, gap_kind: skill}", "tier"),
    ],
)
def test_validate_frontier_refuses_a_case_that_is_not_a_frontier_rung_of_its_file(
    tmp_path: Path, metadata: str, fault: str
) -> None:
    path = tmp_path / "probe-ladder.yaml"
    path.write_text(f"cases:\n  - name: probe-1\n    inputs: one\n    metadata: {metadata}\n")

    with pytest.raises(DatasetError) as raised:
        validate_frontier(path)

    assert "probe-1" in str(raised.value)
    assert fault in str(raised.value)


def _write_probe_dataset(tmp_path: Path) -> Path:
    """A dataset with no model behind it: `a` meets `Contains`, `b` fails `EqualsExpected`."""
    path = tmp_path / "probe.yaml"
    path.write_text(
        "cases:\n"
        "  - name: a\n"
        "    inputs: hello world\n"
        "    metadata: {tier: frontier, rung: 1}\n"
        "    evaluators:\n"
        "      - Contains: hello\n"
        "  - name: b\n"
        "    inputs: hello world\n"
        "    expected_output: other\n"
        "    evaluators:\n"
        "      - EqualsExpected\n"
    )
    return path


def test_results_from_passes_a_case_whose_assertions_all_hold_and_fails_one_that_does_not(
    tmp_path: Path,
) -> None:
    report = load_dataset(_write_probe_dataset(tmp_path)).evaluate_sync(
        lambda inputs: inputs, progress=False
    )

    results = results_from("probe", report)

    assert results[0] == CaseResult(
        dataset="probe", name="a", passed=True, metadata={"tier": "frontier", "rung": 1}
    )
    assert results[1].name == "b"
    assert results[1].passed is False
    assert results[1].reasons != []


def test_results_from_fails_every_case_of_a_run_whose_task_raised(tmp_path: Path) -> None:
    def boom(inputs: str) -> str:
        raise RuntimeError("boom")

    report = load_dataset(_write_probe_dataset(tmp_path)).evaluate_sync(boom, progress=False)

    results = results_from("probe", report)

    assert [result.name for result in results] == ["a", "b"]
    assert [result.passed for result in results] == [False, False]
    assert all("boom" in " ".join(result.reasons) for result in results)


def test_results_from_names_a_repeated_case_after_the_case_it_repeats(tmp_path: Path) -> None:
    report = load_dataset(_write_probe_dataset(tmp_path)).evaluate_sync(
        lambda inputs: inputs, progress=False, repeat=2
    )

    results = results_from("probe", report)

    assert sorted(result.name for result in results) == ["a", "a", "b", "b"]


def test_report_store_saves_a_report_under_its_run_id_and_points_latest_at_it(
    tmp_path: Path,
) -> None:
    report = EvalReport(
        created_at=datetime(2026, 9, 5, 14, 15, tzinfo=UTC),
        run_id="r1",
        datasets=["triage"],
        cases=[CaseResult(dataset="triage", name="a", passed=True)],
    )
    store = ReportStore(tmp_path)

    path = store.save(report)

    assert path == tmp_path / "r1.json"
    assert json.loads((tmp_path / "latest.json").read_text()) == {"report": "r1.json"}
    assert store.load_latest() == report


def test_report_store_has_no_latest_report_before_the_first_run(tmp_path: Path) -> None:
    assert ReportStore(tmp_path).load_latest() is None


def test_list_all_returns_every_saved_report_in_created_at_order(tmp_path: Path) -> None:
    store = ReportStore(tmp_path)
    store.save(
        EvalReport(
            created_at=datetime(2026, 9, 5, 14, 15, tzinfo=UTC), run_id="r2", datasets=["triage"]
        )
    )
    store.save(
        EvalReport(
            created_at=datetime(2026, 9, 4, 9, 0, tzinfo=UTC), run_id="r1", datasets=["answers"]
        )
    )

    assert [report.run_id for report in store.list_all()] == ["r1", "r2"]
    assert ReportStore(tmp_path / "missing").list_all() == []


def test_a_report_without_a_run_id_is_saved_under_its_creation_timestamp(tmp_path: Path) -> None:
    store = ReportStore(tmp_path)

    path = store.save(
        EvalReport(created_at=datetime(2026, 9, 5, 14, 15, 30, tzinfo=UTC), datasets=["triage"])
    )

    assert path == tmp_path / "20260905-141530.json"


def test_a_report_finds_one_eval_case_by_its_dataset_and_name() -> None:
    report = EvalReport(
        created_at=datetime(2026, 9, 5, 14, 15, tzinfo=UTC),
        datasets=["triage", "answers"],
        cases=[
            CaseResult(dataset="triage", name="a", passed=True),
            CaseResult(dataset="answers", name="a", passed=False),
        ],
    )

    assert report.case("answers", "a") == CaseResult(dataset="answers", name="a", passed=False)
    assert report.case("triage", "missing") is None


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


def test_a_target_case_missing_from_the_earlier_report_counts_as_failing_so_it_can_improve() -> (
    None
):
    delta = compare(None, _report({"triage/a": True}), ["triage/a"])

    assert delta.targets == ["triage/a"]
    assert delta.targets_passed_before == 0
    assert delta.targets_passed_after == 1
    assert delta.target_improved is True
    assert delta.newly_passing == ["triage/a"]


def test_a_target_case_that_already_passed_is_not_an_improvement() -> None:
    delta = compare(_report({"triage/a": True}), _report({"triage/a": True}), ["triage/a"])

    assert delta.targets_passed_before == 1
    assert delta.targets_passed_after == 1
    assert delta.target_improved is False
    assert delta.newly_passing == []


def test_a_guard_case_that_passed_before_and_fails_now_regresses_while_an_unrun_one_does_not() -> (
    None
):
    before = _report({"triage/a": False, "answers/b": True, "answers/c": True})
    after = _report({"triage/a": True, "answers/b": False})

    delta = compare(before, after, ["triage/a"])

    assert delta.guard_regressions == ["answers/b"]
    assert delta.guard_regressed is True


def test_a_target_case_that_passed_before_and_fails_now_is_newly_failing_not_a_regression() -> None:
    delta = compare(_report({"triage/a": True}), _report({"triage/a": False}), ["triage/a"])

    assert delta.newly_failing == ["triage/a"]
    assert delta.guard_regressions == []
    assert delta.target_improved is False


def test_a_frontier_case_is_addressed_by_its_dataset_path_and_its_case_name() -> None:
    key = "frontier/repo-history/repo-history-1-first-commit"
    after = EvalReport(
        created_at=datetime(2026, 9, 5, 14, 15, tzinfo=UTC),
        datasets=["frontier/repo-history"],
        cases=[
            CaseResult(
                dataset="frontier/repo-history", name="repo-history-1-first-commit", passed=True
            )
        ],
    )

    delta = compare(None, after, [key])

    assert delta.targets_passed_after == 1
    assert delta.newly_passing == [key]


def test_every_frontier_capability_is_red_at_rung_one_when_no_report_exists_yet() -> None:
    ratios = frontier_ratios(EVALS_DIR / "frontier", None)

    assert [(ratio.capability, ratio.green, ratio.total) for ratio in ratios] == [
        ("repo-history", 0, 4),
        ("text-analysis", 0, 5),
        ("web-research", 0, 3),
    ]
    assert [ratio.available for ratio in ratios] == [False, False, False]
    assert [ratio.lowest_red_rung for ratio in ratios] == [1, 1, 1]


def test_a_frontier_capability_reports_the_lowest_rung_that_is_still_red() -> None:
    report = _report(
        {
            "frontier/repo-history/repo-history-1-first-commit": True,
            "frontier/repo-history/repo-history-2-files-in-first-commit": True,
        }
    )

    ratios = frontier_ratios(EVALS_DIR / "frontier", report)
    repo_history = next(ratio for ratio in ratios if ratio.capability == "repo-history")

    assert (repo_history.green, repo_history.total) == (2, 4)
    assert repo_history.lowest_red_rung == 3
    assert repo_history.available is False


def test_a_capability_is_available_only_when_every_rung_of_its_ladder_is_green() -> None:
    report = _report(
        {
            "frontier/web-research/web-research-1-latest-release": True,
            "frontier/web-research/web-research-2-read-a-docs-page": True,
            "frontier/web-research/web-research-3-summarise-recent-posts": True,
        }
    )

    ratios = frontier_ratios(EVALS_DIR / "frontier", report)
    web_research = next(ratio for ratio in ratios if ratio.capability == "web-research")

    assert (web_research.green, web_research.total) == (3, 3)
    assert web_research.available is True
    assert web_research.lowest_red_rung is None


_TWO_CASES = "cases:\n  - name: a\n    inputs: one\n  - name: b\n    inputs: two\n"


@pytest.mark.parametrize(
    ("after", "changed"),
    [
        (_TWO_CASES + "  - name: c\n    inputs: three\n", []),
        ("cases:\n  - name: a\n    inputs: changed\n  - name: b\n    inputs: two\n", ["a"]),
        ("cases:\n  - name: a\n    inputs: one\n", ["b"]),
        (None, ["a", "b"]),
    ],
)
def test_changed_eval_cases_names_existing_cases_that_were_changed_or_deleted(
    after: str | None, changed: list[str]
) -> None:
    assert changed_eval_cases(_TWO_CASES, after) == changed


def test_a_new_dataset_file_has_no_existing_case_to_change() -> None:
    assert changed_eval_cases(None, _TWO_CASES) == []


def test_a_dataset_level_evaluator_is_not_an_eval_case() -> None:
    before = "evaluators:\n  - EqualsExpected\n" + _TWO_CASES
    after = "evaluators:\n  - Contains: hello\n" + _TWO_CASES

    assert changed_eval_cases(before, after) == []


def test_summary_lines_give_one_dataset_per_line_sorted_by_dataset_name() -> None:
    report = _report({"triage/a": True, "triage/b": False, "answers/c": True})

    assert report.summary_lines() == ["answers: 1/1 passed", "triage: 1/2 passed"]
