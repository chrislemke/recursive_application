"""Data contracts and the Run Record, exercised at the records module's seams."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from recursive_application.kernel.records import (
    CapabilityGap,
    CheckResult,
    EvalCase,
    GateCheck,
    GateResult,
    IterationRecord,
    Mode,
    Plan,
    RunRecord,
    RunStore,
    TriageDecision,
    Usage,
)


def _network_gap() -> CapabilityGap:
    return CapabilityGap(
        kind="connection",
        description="No outbound HTTP",
        how_to_acquire="Grant network access",
        needs_human=["network access"],
    )


def test_assigning_a_field_on_a_contract_raises_validation_error() -> None:
    gap = _network_gap()

    with pytest.raises(ValidationError):
        # ty already rejects this statically; the test proves the runtime does too.
        gap.description = "changed"  # ty: ignore[invalid-assignment]


def test_an_unknown_field_on_a_contract_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        CapabilityGap.model_validate(
            {
                "kind": "connection",
                "description": "No outbound HTTP",
                "how_to_acquire": "Grant network access",
                "bogus": True,
            }
        )


def test_triage_decision_from_a_plain_dict_with_a_connection_gap_validates() -> None:
    decision = TriageDecision.model_validate(
        {
            "mode": "growth",
            "reasoning": "The Task needs a connection the Organism lacks.",
            "reflection": {
                "required_capabilities": ["fetch a web page"],
                "gaps": [
                    {
                        "kind": "connection",
                        "description": "No outbound HTTP",
                        "how_to_acquire": "Grant network access",
                        "needs_human": ["network access"],
                    }
                ],
            },
        }
    )

    assert decision.mode == Mode.GROWTH
    assert decision.clarifying_questions == []
    assert decision.reflection.gaps[0].needs_human == ["network access"]


def test_a_contract_works_as_a_pydantic_ai_output_type() -> None:
    agent = Agent(TestModel(), name="triage_probe", output_type=TriageDecision)

    result = agent.run_sync("Summarise this text.")

    assert isinstance(result.output, TriageDecision)


def _plan(**overrides: object) -> Plan:
    fields: dict[str, object] = {
        "title": "Teach the Worker to summarise",
        "evidence": "evals/worker.yaml case summarise-1 fails",
        "cause": "The prompt never asks for a summary",
        "change": "Add a summary section to prompts/worker.md",
        "target_cases": [EvalCase(name="summarise-1", inputs="Summarise this text.")],
        "predicted_impact": "summarise-1 passes; no Guard Case at risk",
    }
    fields.update(overrides)
    return Plan.model_validate(fields)


def test_plan_with_tests_and_actor_round_trips_through_json_unchanged() -> None:
    plan = _plan(
        target_paths=["src/recursive_application/organism/tools.py"],
        tests=[
            "`summarise()` returns one sentence for a one-paragraph input",
            "`summarise()` keeps the input's first proper noun",
        ],
        actor="implementer",
    )

    restored = Plan.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert restored.tests == [
        "`summarise()` returns one sentence for a one-paragraph input",
        "`summarise()` keeps the input's first proper noun",
    ]
    assert restored.actor == "implementer"


def test_plan_without_tests_and_actor_has_an_empty_tests_list_and_no_actor() -> None:
    plan = _plan()

    assert plan.tests == []
    assert plan.actor is None


def test_check_result_output_is_truncated_to_two_thousand_characters() -> None:
    result = CheckResult(name="pytest", passed=False, output="x" * 5000)

    assert len(result.output) == 2000


def test_gate_result_lists_only_its_failed_checks_by_name() -> None:
    gate = GateResult(
        passed=False,
        checks=[
            GateCheck(name="pytest", status="failed"),
            GateCheck(name="ty", status="skipped"),
        ],
    )

    assert gate.failed_checks == ["pytest"]


def test_adding_two_usage_values_adds_every_field_including_the_decimal_cost() -> None:
    total = Usage(requests=1, cost_usd=Decimal("0.5")) + Usage(requests=2, input_tokens=3)

    assert total == Usage(requests=3, input_tokens=3, cost_usd=Decimal("0.5"))


def _one_cent_iteration() -> IterationRecord:
    return IterationRecord(number=1, usage=Usage(requests=1, cost_usd=Decimal("0.01")))


def test_appending_an_iteration_then_loading_returns_an_equal_run_record(
    tmp_path: Path,
) -> None:
    store = RunStore(tmp_path / "runs")
    record = RunRecord(mode=Mode.TASK, task="Summarise this text.")

    path = store.append_iteration(record, _one_cent_iteration())

    assert path == tmp_path / "runs" / f"{record.run_id}.json"
    assert store.load(record.run_id) == record


def test_total_usage_sums_the_iterations_cost(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    record = RunRecord(mode=Mode.TASK)
    store.append_iteration(record, _one_cent_iteration())

    assert store.load(record.run_id).total_usage.cost_usd == Decimal("0.01")


def test_list_all_returns_run_records_in_start_order(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs")
    later = RunRecord(
        run_id="20260905-150000-aaaaaa",
        mode=Mode.ANSWER,
        started_at=datetime(2026, 9, 5, 15, 0, tzinfo=UTC),
    )
    earlier = RunRecord(
        run_id="20260905-140000-bbbbbb",
        mode=Mode.GROWTH,
        started_at=datetime(2026, 9, 5, 14, 0, tzinfo=UTC),
    )
    store.save(later)
    store.save(earlier)

    assert [record.run_id for record in store.list_all()] == [
        "20260905-140000-bbbbbb",
        "20260905-150000-aaaaaa",
    ]


def test_a_generated_run_id_is_a_utc_timestamp_and_six_hex_characters() -> None:
    record = RunRecord(mode=Mode.ANSWER)

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", record.run_id)


def test_list_all_of_a_missing_directory_is_empty(tmp_path: Path) -> None:
    assert RunStore(tmp_path / "missing").list_all() == []
