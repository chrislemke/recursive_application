"""Data contracts and the Run Record.

Every piece of data that crosses an agent boundary or lands in a Run Record is a
contract: a frozen Pydantic model that rejects unknown fields and serves as a
Pydantic AI output type.
"""

import secrets
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHECK_OUTPUT_LIMIT = 2000

Outcome = Literal["accepted", "rejected", "error", "aborted"]


class Mode(StrEnum):
    """The way a Task is handled."""

    ANSWER = "answer"
    TASK = "task"
    GROWTH = "growth"


class Contract(BaseModel):
    """Base of every contract: immutable, and strict about the fields it accepts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CapabilityGap(Contract):
    """Something the Organism cannot yet do that a Task requires."""

    kind: Literal["tool", "knowledge", "connection", "skill", "clarification"]
    description: str
    how_to_acquire: str
    needs_human: list[str] = []


class Reflection(Contract):
    """Triage's self-assessment of a Task against the Capability Inventory."""

    required_capabilities: list[str]
    available: list[str] = []
    gaps: list[CapabilityGap] = []


class TriageDecision(Contract):
    """Triage's output: the Mode for a Task and the Reflection behind it."""

    mode: Mode
    reasoning: str
    reflection: Reflection
    clarifying_questions: list[str] = []


class EvalCase(Contract):
    """One eval case: a Target Case, a Guard Case, or a Frontier Case."""

    name: str
    inputs: str
    expected_output: str | None = None
    rubric: str | None = None
    must_contain: list[str] = []


class Plan(Contract):
    """The Planner's output for one Iteration.

    `tests` holds one-sentence behaviours at a public interface; whether it may be
    empty depends on `target_paths` and is enforced by the Loop runner, not here.
    `dataset` names the file under `evals/` the new Target Cases are appended to, and
    is `None` when the targets are Frontier Cases that already exist.
    """

    title: str
    evidence: str
    cause: str
    change: str
    target_paths: list[str] = []
    tests: list[str] = []
    target_cases: list[EvalCase]
    predicted_impact: str
    at_risk: list[str] = []
    gaps: list[CapabilityGap] = []
    actor: str | None = None
    dataset: str | None = None


class CheckResult(Contract):
    """The outcome of one of the four checks, with its output cut to a readable size."""

    name: Literal["ruff-format", "ruff-check", "ty", "pytest"]
    passed: bool
    output: str = ""

    @field_validator("output")
    @classmethod
    def _truncate_output(cls, value: str) -> str:
        return value[:CHECK_OUTPUT_LIMIT]


class GateCheck(Contract):
    """One check the Gate ran, skipped, or failed on an Iteration."""

    name: str
    status: Literal["passed", "skipped", "failed"]
    excerpt: str = ""


class GateResult(Contract):
    """The Gate's verdict on one Iteration and the checks behind it."""

    passed: bool
    checks: list[GateCheck] = []

    @property
    def failed_checks(self) -> list[str]:
        """The names of the checks whose status is `failed`."""
        return [check.name for check in self.checks if check.status == "failed"]


class Usage(Contract):
    """Model usage for one Iteration or one Loop run."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            requests=self.requests + other.requests,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class CodeReport(Contract):
    """What the Test Writer or the Implementer did and how the four checks went."""

    summary: str
    changed_files: list[str] = []
    checks: list[CheckResult] = []


class WorkerOutput(Contract):
    """The Worker's output for a Task, with any Capability Gaps it noticed."""

    content: str
    gaps: list[CapabilityGap] = []


class Review(Contract):
    """The Reviewer's judgement of a diff against its Plan."""

    matches_plan: bool
    gaming_suspected: bool
    notes: str
    verdict: Literal["accept", "reject"]


class SensorFinding(Contract):
    """One item of evidence produced by a Sensor."""

    id: str
    source: Literal["evals", "traces", "feedback", "wiki", "reflection", "policy"]
    summary: str
    details: str = ""
    severity: Literal["low", "medium", "high"] = "medium"


def _now() -> datetime:
    return datetime.now(UTC)


def _generate_run_id() -> str:
    return f"{_now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


class IterationRecord(Contract):
    """One pass through the five phases and what it produced."""

    number: int
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    plan: Plan | None = None
    test_report: CodeReport | None = None
    code_report: CodeReport | None = None
    output_path: str | None = None
    gate: GateResult | None = None
    review: Review | None = None
    outcome: Outcome | None = None
    commit_sha: str | None = None
    usage: Usage = Usage()


class RunRecord(BaseModel):
    """The append-only record of one Loop run.

    Not frozen, because Iterations are appended; unknown fields are still rejected.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=_generate_run_id)
    mode: Mode
    task: str | None = None
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    iterations: list[IterationRecord] = []
    outcome: Outcome | None = None
    findings_addressed: list[str] = []

    @property
    def total_usage(self) -> Usage:
        """The sum of every Iteration's usage."""
        return sum((iteration.usage for iteration in self.iterations), Usage())


class RunStore:
    """One JSON file per Run Record under the runtime directory."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def save(self, record: RunRecord) -> Path:
        """Write the record to `<runs_dir>/<run_id>.json` and return that path."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(record.run_id)
        path.write_text(record.model_dump_json(indent=2))
        return path

    def append_iteration(self, record: RunRecord, iteration: IterationRecord) -> Path:
        """Append the Iteration to the record and save it."""
        record.iterations.append(iteration)
        return self.save(record)

    def load(self, run_id: str) -> RunRecord:
        """Read one record back by its id."""
        return RunRecord.model_validate_json(self._path(run_id).read_text())

    def list_all(self) -> list[RunRecord]:
        """Every record in `started_at` order; `[]` when the directory is missing."""
        if not self.runs_dir.is_dir():
            return []
        records = [
            RunRecord.model_validate_json(path.read_text()) for path in self.runs_dir.glob("*.json")
        ]
        return sorted(records, key=lambda record: (record.started_at, record.run_id))

    def _path(self, run_id: str) -> Path:
        return self.runs_dir / f"{run_id}.json"
