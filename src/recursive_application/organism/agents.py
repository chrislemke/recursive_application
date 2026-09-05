"""The Organism's agent registry: the seven required roles, in Loop order.

Organism code (ADR 0003), so the system may improve it; the Kernel's registry contract test
holds it to the roles the Loop calls. No agent sets a model and none carries instructions:
the Kernel injects the model from the entry's tier and assembles the instructions from the
Constitution, the entry's guides, its prompt file, and the State Bundle at run time.

Adding a Specialist is one call to `_entry` with `phases=("act",)`, one prompt file beside
this module, one tool configuration in `tools.py`, and the dataset that proves it (ADR 0007).
"""

from typing import Any

from pydantic_ai import Agent

from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.records import (
    CodeReport,
    Plan,
    Review,
    TriageDecision,
    WorkerOutput,
)
from recursive_application.kernel.registry import CODING_GUIDE, Phase, RegistryEntry, Tier
from recursive_application.organism.tools import ROLE_TOOL_CONFIGS, toolsets_for

PROMPTS_DIR = "src/recursive_application/organism/prompts"
"""Where the prompt files live, repo-relative POSIX."""

RETRIES = 2
"""How often an agent may be asked again for a valid output or a valid tool call."""


def _entry(
    name: str,
    output_type: type,
    tier: Tier,
    phases: tuple[Phase, ...],
    guides: tuple[str, ...],
    dataset: str,
) -> RegistryEntry:
    """One registry entry, with the agent built from the role's tool configuration."""
    tools = ROLE_TOOL_CONFIGS[name]
    return RegistryEntry(
        name=name,
        agent=Agent[None, Any](
            name=name,
            output_type=output_type,
            toolsets=toolsets_for(tools, REPO_ROOT),
            retries=RETRIES,
        ),
        tier=tier,
        phases=phases,
        tools=tools,
        guides=guides,
        prompt_path=f"{PROMPTS_DIR}/{name}.md",
        dataset=dataset,
    )


REGISTRY: tuple[RegistryEntry, ...] = (
    _entry("triage", TriageDecision, "primary", ("decide",), (), "evals/triage.yaml"),
    _entry("planner", Plan, "primary", ("decide",), (CODING_GUIDE,), "evals/planner.yaml"),
    _entry(
        "test_writer", CodeReport, "primary", ("act",), (CODING_GUIDE,), "evals/test-writer.yaml"
    ),
    _entry(
        "implementer", CodeReport, "primary", ("act",), (CODING_GUIDE,), "evals/implementer.yaml"
    ),
    _entry("worker", WorkerOutput, "primary", ("act",), (), "evals/answers.yaml"),
    _entry("reviewer", Review, "judge", ("gate",), (CODING_GUIDE,), "evals/reviewer.yaml"),
    _entry("librarian", str, "primary", ("learn",), (), "evals/librarian.yaml"),
)
"""Every agent the Kernel may call, in Loop order: decide, act, gate, learn."""
