"""The seven seed eval datasets, one per registry role.

Structure only: the files exist, load through the Kernel's loader, name no model, and hold the
cases the spec requires. Whether the agents pass them is an eval question, never a pytest one
(ADR 0005), so nothing here calls a model.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from recursive_application.kernel.evals import EVALS_DIR, dataset_name, list_datasets, load_dataset

ROLE_DATASETS = (
    "triage",
    "planner",
    "test-writer",
    "implementer",
    "answers",
    "reviewer",
    "librarian",
)

FRONTIER_DATASETS = (
    "frontier/repo-history",
    "frontier/text-analysis",
    "frontier/web-research",
)

GAP_KINDS = ("kind: skill", "kind: tool", "kind: connection", "kind: clarification")

PHASES = ("Sense", "Decide", "Act", "Gate", "Learn")


def _evaluator_arguments(path: Path) -> list[dict[str, Any]]:
    """The argument mapping of every evaluator spec in a dataset file, from the raw YAML."""
    raw = yaml.safe_load(path.read_text())
    specs = list(raw.get("evaluators", []))
    for case in raw["cases"]:
        specs.extend(case.get("evaluators", []))
    return [
        arguments
        for spec in specs
        if isinstance(spec, dict)
        for arguments in spec.values()
        if isinstance(arguments, dict)
    ]


def _contains_values(path: Path) -> list[str]:
    """The value of every `Contains` evaluator in a dataset file, from the raw YAML."""
    raw = yaml.safe_load(path.read_text())
    return [
        spec["Contains"]
        for case in raw["cases"]
        for spec in case.get("evaluators", [])
        if isinstance(spec, dict) and isinstance(spec.get("Contains"), str)
    ]


def _rubrics(path: Path) -> list[str]:
    """Every judge rubric in a dataset file, from the raw YAML."""
    return [
        arguments["rubric"]
        for arguments in _evaluator_arguments(path)
        if isinstance(arguments.get("rubric"), str)
    ]


@pytest.mark.parametrize("role", ROLE_DATASETS)
def test_each_role_dataset_loads_with_at_least_two_cases(role: str) -> None:
    path = EVALS_DIR / f"{role}.yaml"

    assert path.is_file()
    assert len(load_dataset(path).cases) >= 2


def test_every_dataset_under_evals_loads_and_the_seven_roles_are_among_them() -> None:
    paths = list_datasets(EVALS_DIR)

    assert {dataset_name(path) for path in paths} >= set(ROLE_DATASETS) | set(FRONTIER_DATASETS)
    for path in paths:
        assert load_dataset(path).cases, path


def test_no_evaluator_in_any_dataset_names_a_model() -> None:
    for path in list_datasets(EVALS_DIR):
        for arguments in _evaluator_arguments(path):
            assert "model" not in arguments, path


def test_the_seed_datasets_carry_at_least_seven_judge_rubrics() -> None:
    judged = sum(
        1
        for path in list_datasets(EVALS_DIR)
        for arguments in _evaluator_arguments(path)
        if "rubric" in arguments
    )

    assert judged >= 7


def test_triage_asserts_the_four_gap_kinds_and_both_modes() -> None:
    values = _contains_values(EVALS_DIR / "triage.yaml")

    assert set(GAP_KINDS) <= set(values)
    assert "mode: growth" in values
    assert "mode: answer" in values


def test_answers_rubrics_demand_a_frontier_ratio_and_the_five_phases() -> None:
    rubrics = _rubrics(EVALS_DIR / "answers.yaml")

    assert any("frontier" in rubric for rubric in rubrics)
    assert any(all(phase in rubric for phase in PHASES) for rubric in rubrics)


def test_planner_asserts_the_frontier_file_the_new_specialist_is_proven_by() -> None:
    assert "evals/frontier/text-analysis.yaml" in _contains_values(EVALS_DIR / "planner.yaml")


@pytest.mark.parametrize("role", ROLE_DATASETS)
def test_each_case_name_is_unique_and_opens_with_its_role(role: str) -> None:
    names = [case.name for case in load_dataset(EVALS_DIR / f"{role}.yaml").cases]

    assert len(set(names)) == len(names)
    for name in names:
        assert name is not None and name.startswith(f"{role}-")
