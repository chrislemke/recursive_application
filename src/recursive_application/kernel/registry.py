"""The Organism's agent registry and the contract the Kernel holds it to.

The Organism owns which agents exist and what they are told; the Kernel owns this contract:
the seven roles the Loop calls, their output types, the phases they may act in, and the
files that prove them. `validate_registry` is what protects the Kernel from a bad
Improvement, so it refuses rather than repairs, and its message names the entry and the
fault.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic_ai import Agent

from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.policy import PolicyError, ToolConfig, validate_tool_config
from recursive_application.kernel.records import (
    CodeReport,
    Plan,
    Review,
    TriageDecision,
    WorkerOutput,
)

Phase = Literal["sense", "decide", "act", "gate", "learn"]
"""The five phases of the Loop, which are the five layers of a self-improving loop."""

Tier = Literal["primary", "judge"]
"""Which of the two models an entry runs on; the Kernel injects it at run time."""

CODING_GUIDE = "docs/coding-guide.md"
"""The guide the coding roles read, repo-relative."""

EVALS_DIRNAME_TRACKED = "evals"
"""Where every entry's dataset must live: the tracked eval directory."""

REGISTRY_MODULE = "src/recursive_application/organism/agents.py"
"""The Organism module holding the registry; a change there affects every agent."""

TOOLS_MODULE = "src/recursive_application/organism/tools.py"
"""The Organism module holding the tool configurations; a change there affects every agent."""

SPECIALIST_PHASES: tuple[str, ...] = ("act",)
"""The only phases a Specialist may act in (ADR 0007)."""

PROMPT_PHASE_LINES = 3
"""How many lines of a prompt file the phase check reads."""


class RegistryError(ValueError):
    """A registry entry breaks the Kernel's contract; the message names the entry and the fault."""


@dataclass(frozen=True)
class RegistryEntry:
    """One agent the Kernel may call, with everything it needs to run and to prove it."""

    name: str
    agent: Agent[None, Any]
    tier: Tier
    phases: tuple[Phase, ...]
    tools: ToolConfig
    guides: tuple[str, ...]
    prompt_path: str
    dataset: str


@dataclass(frozen=True)
class RoleSpec:
    """What the Kernel requires of one of the seven required roles."""

    output_type: type
    tier: Tier
    phases: tuple[Phase, ...]
    guides: tuple[str, ...]


REQUIRED_ROLES: Mapping[str, RoleSpec] = {
    "triage": RoleSpec(TriageDecision, "primary", ("decide",), ()),
    "planner": RoleSpec(Plan, "primary", ("decide",), (CODING_GUIDE,)),
    "test_writer": RoleSpec(CodeReport, "primary", ("act",), (CODING_GUIDE,)),
    "implementer": RoleSpec(CodeReport, "primary", ("act",), (CODING_GUIDE,)),
    "worker": RoleSpec(WorkerOutput, "primary", ("act",), ()),
    "reviewer": RoleSpec(Review, "judge", ("gate",), (CODING_GUIDE,)),
    "librarian": RoleSpec(str, "primary", ("learn",), ()),
}
"""The roles the Loop looks up by name; a registry without one of them is refused."""


@dataclass(frozen=True)
class Registry:
    """A validated registry: the seven required roles and any Specialists beside them."""

    entries: tuple[RegistryEntry, ...]

    def get(self, name: str) -> RegistryEntry:
        """The entry called `name`, or `RegistryError` when the registry has no such entry."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        raise RegistryError(f"unknown registry entry: {name!r}")

    @property
    def names(self) -> tuple[str, ...]:
        """Every entry's name, in registry order."""
        return tuple(entry.name for entry in self.entries)

    @property
    def specialists(self) -> tuple[RegistryEntry, ...]:
        """The entries beyond the seven required roles, in registry order."""
        return tuple(entry for entry in self.entries if entry.name not in REQUIRED_ROLES)


def _type_name(output_type: object) -> str:
    """A readable name for an output type, for a refusal message.

    `Agent.output_type` is an output specification, not always a class, so this takes any
    object and falls back to its text.
    """
    return getattr(output_type, "__name__", str(output_type))


def _refuse_duplicate_names(entries: Sequence[RegistryEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.name in seen:
            raise RegistryError(f"duplicate registry entry: {entry.name!r}")
        seen.add(entry.name)


def _refuse_missing_roles(entries: Sequence[RegistryEntry]) -> None:
    present = {entry.name for entry in entries}
    for name in REQUIRED_ROLES:
        if name not in present:
            raise RegistryError(f"missing required role: {name!r}")


def _refuse_role_mismatch(entries: Sequence[RegistryEntry]) -> None:
    for entry in entries:
        spec = REQUIRED_ROLES.get(entry.name)
        if spec is None:
            continue
        actual = entry.agent.output_type
        if actual is not spec.output_type:
            raise RegistryError(
                f"entry {entry.name!r}: output type is {_type_name(actual)}, "
                f"the Kernel requires {_type_name(spec.output_type)}"
            )
        if entry.tier != spec.tier:
            raise RegistryError(
                f"entry {entry.name!r}: tier is {entry.tier!r}, the Kernel requires {spec.tier!r}"
            )
        if entry.phases != spec.phases:
            raise RegistryError(
                f"entry {entry.name!r}: phases are {entry.phases}, "
                f"the Kernel requires {spec.phases}"
            )
        for guide in spec.guides:
            if guide not in entry.guides:
                raise RegistryError(f"entry {entry.name!r}: guides do not list {guide!r}")


def _refuse_specialist_outside_act(entries: Sequence[RegistryEntry]) -> None:
    for entry in entries:
        if entry.name not in REQUIRED_ROLES and entry.phases != SPECIALIST_PHASES:
            raise RegistryError(
                f"Specialist entry {entry.name!r}: phases are {entry.phases}, "
                f"a Specialist acts only in {SPECIALIST_PHASES} (ADR 0007)"
            )


def _refuse_model(entries: Sequence[RegistryEntry]) -> None:
    for entry in entries:
        if entry.agent.model is not None:
            raise RegistryError(
                f"entry {entry.name!r}: the agent sets a model ({entry.agent.model!r}); "
                "the Kernel injects the model from the entry's tier"
            )


def _refuse_dataset_outside_evals(entries: Sequence[RegistryEntry]) -> None:
    for entry in entries:
        if not entry.dataset.startswith(f"{EVALS_DIRNAME_TRACKED}/"):
            raise RegistryError(
                f"entry {entry.name!r}: dataset is not under {EVALS_DIRNAME_TRACKED}/: "
                f"{entry.dataset!r}"
            )


def _refuse_missing_files(entries: Sequence[RegistryEntry], root: Path) -> None:
    for entry in entries:
        for guide in entry.guides:
            if not (root / guide).is_file():
                raise RegistryError(f"entry {entry.name!r}: guide does not exist: {guide!r}")
        prompt = root / entry.prompt_path
        if not prompt.is_file():
            raise RegistryError(
                f"entry {entry.name!r}: prompt does not exist: {entry.prompt_path!r}"
            )
        if not (root / entry.dataset).is_file():
            raise RegistryError(f"entry {entry.name!r}: dataset does not exist: {entry.dataset!r}")


def _refuse_unnamed_phase(entries: Sequence[RegistryEntry], root: Path) -> None:
    for entry in entries:
        text = (root / entry.prompt_path).read_text(encoding="utf-8")
        if not text.strip():
            raise RegistryError(f"entry {entry.name!r}: prompt is empty: {entry.prompt_path!r}")
        opening = "\n".join(text.splitlines()[:PROMPT_PHASE_LINES])
        for phase in entry.phases:
            if not re.search(rf"\b{phase}\b", opening, flags=re.IGNORECASE):
                raise RegistryError(
                    f"entry {entry.name!r}: the first {PROMPT_PHASE_LINES} lines of "
                    f"{entry.prompt_path!r} do not name its phase {phase!r} (ADR 0010)"
                )


def _refuse_tools_above_the_ceiling(entries: Sequence[RegistryEntry]) -> None:
    for entry in entries:
        try:
            validate_tool_config(entry.tools)
        except PolicyError as error:
            raise RegistryError(f"entry {entry.name!r}: {error}") from error


def validate_registry(entries: Sequence[RegistryEntry], root: Path = REPO_ROOT) -> Registry:
    """Hold `entries` to the Kernel's contract and return the Registry they form.

    Refuses in the order the checks are written: a duplicate name, a missing required role, a
    required role that does not match its `RoleSpec`, a Specialist acting outside the Act
    phase, an agent carrying its own model, a file that does not exist under `root`, a prompt
    that does not name its phase, and a tool configuration above the Policy Ceiling.
    """
    _refuse_duplicate_names(entries)
    _refuse_missing_roles(entries)
    _refuse_role_mismatch(entries)
    _refuse_specialist_outside_act(entries)
    _refuse_model(entries)
    _refuse_dataset_outside_evals(entries)
    _refuse_missing_files(entries, root)
    _refuse_unnamed_phase(entries, root)
    _refuse_tools_above_the_ceiling(entries)
    return Registry(entries=tuple(entries))


def load_registry(root: Path = REPO_ROOT) -> Registry:
    """Import the Organism's registry and validate it.

    The import is local so that the Kernel package does not depend on the Organism at
    import time.
    """
    from recursive_application.organism.agents import REGISTRY

    return validate_registry(REGISTRY, root)


def affected_agents(registry: Registry, changed_paths: Iterable[str]) -> list[str]:
    """The sorted names of the agents a diff touches.

    An agent is affected when its prompt or its dataset changed; a change to the registry
    module or the tools module affects every agent, because both carry all of them.
    """
    paths = set(changed_paths)
    if paths & {REGISTRY_MODULE, TOOLS_MODULE}:
        return sorted(registry.names)
    return sorted(
        entry.name
        for entry in registry.entries
        if entry.prompt_path in paths or entry.dataset in paths
    )
