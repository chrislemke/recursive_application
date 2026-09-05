"""The registry contract, through `kernel.registry`.

This is the test that protects the Kernel from a bad Improvement: it loads the Organism's
own registry and holds it to the seven roles the Loop calls, their output types, the files
that prove them, and the Policy Ceiling.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.policy import ToolConfig
from recursive_application.kernel.records import (
    CodeReport,
    Plan,
    Review,
    TriageDecision,
    WorkerOutput,
)
from recursive_application.kernel.registry import (
    RegistryEntry,
    RegistryError,
    affected_agents,
    load_registry,
    validate_registry,
)

WORKER_PROMPT = "src/recursive_application/organism/prompts/worker.md"
ANSWERS_DATASET = "evals/answers.yaml"

# The seven required roles as the seams document lists them: name, output type, tier,
# phases, guides.
REQUIRED_ROLE_ROWS = [
    ("triage", TriageDecision, "primary", ("decide",), ()),
    ("planner", Plan, "primary", ("decide",), ("docs/coding-guide.md",)),
    ("test_writer", CodeReport, "primary", ("act",), ("docs/coding-guide.md",)),
    ("implementer", CodeReport, "primary", ("act",), ("docs/coding-guide.md",)),
    ("worker", WorkerOutput, "primary", ("act",), ()),
    ("reviewer", Review, "judge", ("gate",), ("docs/coding-guide.md",)),
    ("librarian", str, "primary", ("learn",), ()),
]


def test_the_registry_holds_the_seven_required_roles_and_no_specialists() -> None:
    registry = load_registry()

    assert registry.names == (
        "triage",
        "planner",
        "test_writer",
        "implementer",
        "worker",
        "reviewer",
        "librarian",
    )
    assert registry.specialists == ()


@pytest.mark.parametrize(
    ("name", "output_type", "tier", "phases", "guides"),
    REQUIRED_ROLE_ROWS,
    ids=[row[0] for row in REQUIRED_ROLE_ROWS],
)
def test_a_required_role_matches_its_specification(
    name: str,
    output_type: type,
    tier: str,
    phases: tuple[str, ...],
    guides: tuple[str, ...],
) -> None:
    entry = load_registry().get(name)

    assert entry.agent.output_type is output_type
    assert entry.tier == tier
    assert entry.phases == phases
    assert entry.guides == guides


@pytest.mark.parametrize(
    ("name", "output_type"),
    [(row[0], row[1]) for row in REQUIRED_ROLE_ROWS],
    ids=[row[0] for row in REQUIRED_ROLE_ROWS],
)
def test_a_required_role_produces_its_output_type(name: str, output_type: type) -> None:
    entry = load_registry().get(name)

    # `call_tools=[]` because the default `TestModel` calls every tool an entry grants with
    # synthesised arguments, which for the Implementer means writing into the checkout.
    with entry.agent.override(model=TestModel(call_tools=[])):
        result = entry.agent.run_sync("probe")

    assert isinstance(result.output, output_type)


def _without(entries: Sequence[RegistryEntry], name: str) -> tuple[RegistryEntry, ...]:
    """The entries with the one called `name` dropped."""
    return tuple(entry for entry in entries if entry.name != name)


def _changed(
    entries: Sequence[RegistryEntry], name: str, **changes: object
) -> tuple[RegistryEntry, ...]:
    """The entries with `changes` applied to the one called `name`."""
    return tuple(replace(entry, **changes) if entry.name == name else entry for entry in entries)


def _with_specialist(entries: Sequence[RegistryEntry]) -> tuple[RegistryEntry, ...]:
    """The entries plus a Specialist that acts in the Decide phase, which ADR 0007 forbids."""
    return (
        *entries,
        RegistryEntry(
            name="specialist",
            agent=Agent(name="specialist", output_type=WorkerOutput),
            tier="primary",
            phases=("decide",),
            tools=ToolConfig(),
            guides=(),
            prompt_path=WORKER_PROMPT,
            dataset=ANSWERS_DATASET,
        ),
    )


@pytest.mark.parametrize(
    ("break_it", "named"),
    [
        # A required role the Loop calls is gone.
        (lambda entries: _without(entries, "reviewer"), "reviewer"),
        # A required role whose agent no longer returns the Kernel's contract.
        (
            lambda entries: _changed(
                entries, "worker", agent=Agent(name="worker", output_type=str)
            ),
            "worker",
        ),
        # A coding role that no longer reads the Coding Guide.
        (lambda entries: _changed(entries, "planner", guides=()), "docs/coding-guide.md"),
        # Files that prove an entry and are not there.
        (
            lambda entries: _changed(
                entries,
                "worker",
                prompt_path="src/recursive_application/organism/prompts/missing.md",
            ),
            "src/recursive_application/organism/prompts/missing.md",
        ),
        (
            lambda entries: _changed(entries, "worker", dataset="evals/missing.yaml"),
            "evals/missing.yaml",
        ),
        # A tool configuration above the Policy Ceiling.
        (
            lambda entries: _changed(entries, "worker", tools=ToolConfig(shell_commands=["git"])),
            "git",
        ),
        # A dataset that does not live under evals/.
        (
            lambda entries: _changed(entries, "worker", dataset="tests/organism/spec.yaml"),
            "evals/",
        ),
        # A tool configuration outside an agent's write scope.
        (
            lambda entries: _changed(
                entries, "librarian", tools=ToolConfig(write_globs=["evals/**"])
            ),
            "evals/**",
        ),
        # A Specialist acting outside the Act phase.
        (_with_specialist, "decide"),
        # An agent that brought its own model instead of taking the Kernel's.
        (
            lambda entries: _changed(
                entries,
                "worker",
                agent=Agent(TestModel(), name="worker", output_type=WorkerOutput),
            ),
            "TestModel",
        ),
    ],
    ids=[
        "missing-role",
        "wrong-output-type",
        "missing-guide",
        "missing-prompt",
        "missing-dataset",
        "tools-above-the-ceiling",
        "dataset-outside-evals",
        "tools-outside-the-write-scope",
        "specialist-outside-act",
        "agent-with-a-model",
    ],
)
def test_a_registry_that_breaks_the_contract_is_refused_by_name(
    break_it: Callable[[Sequence[RegistryEntry]], Sequence[RegistryEntry]], named: str
) -> None:
    entries = break_it(load_registry().entries)

    with pytest.raises(RegistryError) as refusal:
        validate_registry(entries)

    assert named in str(refusal.value)


def _mirror(root: Path, entries: Sequence[RegistryEntry]) -> Path:
    """Copy every guide, prompt, and dataset the entries name from the checkout into `root`."""
    for entry in entries:
        for relative in (*entry.guides, entry.prompt_path, entry.dataset):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text((REPO_ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    return root


def test_a_prompt_whose_opening_does_not_name_its_phase_is_refused(tmp_path: Path) -> None:
    entries = load_registry().entries
    root = _mirror(tmp_path, entries)
    (root / WORKER_PROMPT).write_text(
        "Phase: Decide. You write the answer.\n\nNothing here names the phase.\n", encoding="utf-8"
    )

    with pytest.raises(RegistryError) as refusal:
        validate_registry(entries, root)

    assert "worker" in str(refusal.value)
    assert "act" in str(refusal.value)


@pytest.mark.parametrize(
    ("changed_paths", "affected"),
    [
        # An agent's own prompt or its dataset affects that agent.
        (["src/recursive_application/organism/prompts/worker.md"], ["worker"]),
        (["evals/triage.yaml"], ["triage"]),
        # The tools module carries every agent's configuration, so it affects all of them.
        (
            ["src/recursive_application/organism/tools.py"],
            ["implementer", "librarian", "planner", "reviewer", "test_writer", "triage", "worker"],
        ),
        # So does the registry module.
        (
            ["src/recursive_application/organism/agents.py"],
            ["implementer", "librarian", "planner", "reviewer", "test_writer", "triage", "worker"],
        ),
        # A file no entry names affects nobody.
        (["README.md"], []),
    ],
    ids=["a-prompt", "a-dataset", "the-tools-module", "the-registry-module", "an-unrelated-file"],
)
def test_a_diff_affects_the_agents_it_touches(
    changed_paths: list[str], affected: list[str]
) -> None:
    assert affected_agents(load_registry(), changed_paths) == affected


def test_a_specialist_that_acts_only_in_the_act_phase_is_accepted() -> None:
    specialist = RegistryEntry(
        name="text_analyst",
        agent=Agent(name="text_analyst", output_type=WorkerOutput),
        tier="primary",
        phases=("act",),
        tools=ToolConfig(),
        guides=(),
        prompt_path=WORKER_PROMPT,
        dataset=ANSWERS_DATASET,
    )

    registry = validate_registry((*load_registry().entries, specialist))

    assert registry.specialists == (specialist,)
    assert registry.get("text_analyst") is specialist
