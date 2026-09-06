"""The agent runtime: the one Kernel entry point that runs any registry entry.

The Organism owns the agents; the Kernel owns how they are run. Nothing here mutates an
Agent: the model, the instructions, the usage limits, and the usage accumulator all go in
through `run_sync`, so the same Agent object is safe to run twice with different settings.
The instructions are assembled in one fixed order (the Constitution, the entry's guides,
the entry's prompt file, the State Bundle), which is what makes an agent's own prompt hold
only its own job.
"""

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import logfire
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, RetryPromptPart
from pydantic_ai.models import Model, infer_model
from pydantic_ai.usage import RunUsage, UsageLimits

from recursive_application.kernel.breaker import BreakerStore
from recursive_application.kernel.constitution import load_constitution
from recursive_application.kernel.paths import REPO_ROOT
from recursive_application.kernel.records import Usage
from recursive_application.kernel.registry import RegistryEntry, RegistryError
from recursive_application.kernel.sensors import VALIDATION_RETRIES_ATTRIBUTE
from recursive_application.kernel.settings import Settings

CODER_ROLES: frozenset[str] = frozenset({"test_writer", "implementer"})
"""The roles that write code, and so run under the higher request limit."""

SPAN_NAME = "kernel.agent_run"
"""The span every agent run opens; the Sensors' anomaly rules read its attributes."""

REQUESTS_ATTRIBUTE = "requests"
"""The span attribute holding how many model requests the run made."""

COST_ATTRIBUTE = "cost_usd"
"""The span attribute holding what the run cost in USD, zero when the model is unpriceable."""

FALLBACK_USD_PER_MILLION_TOKENS = Decimal("3")
"""The price assumed for a model that reports none, so the budget also binds as tokens."""


@dataclass(frozen=True)
class AgentRunResult:
    """What one agent run produced: its output contract and what it cost."""

    output: Any
    usage: Usage


class AgentRunError(RuntimeError):
    """A run hit a usage limit; `usage` is what it spent before it was stopped."""

    def __init__(self, message: str, usage: Usage) -> None:
        super().__init__(message)
        self.usage = usage


def instruction_parts(entry: RegistryEntry, bundle: str, root: Path) -> list[str]:
    """The instructions for one run of `entry`, in the order the agent receives them."""
    parts = [load_constitution()]
    parts.extend((root / guide).read_text(encoding="utf-8") for guide in entry.guides)
    parts.append((root / entry.prompt_path).read_text(encoding="utf-8"))
    parts.append(bundle)
    return parts


class AgentRunner:
    """Runs a registry entry with the Kernel's model, instructions, limits, and breaker."""

    def __init__(
        self,
        settings: Settings,
        breakers: BreakerStore,
        *,
        root: Path = REPO_ROOT,
        model_factory: Callable[[str], Model] = infer_model,
    ) -> None:
        self._settings = settings
        self._breakers = breakers
        self._root = root
        self._model_factory = model_factory

    def run(
        self,
        entry: RegistryEntry,
        prompt: str,
        *,
        bundle: str,
        budget_usd: Decimal | None = None,
    ) -> AgentRunResult:
        """Run `entry` on `prompt` with the State Bundle `bundle` and return its output.

        `budget_usd` is what this one call may spend, the run's remaining budget when the Loop
        calls; `None` means the Settings budget.
        """
        if entry.agent.model is not None:
            raise RegistryError(
                f"entry {entry.name!r}: the agent sets a model ({entry.agent.model!r}); "
                "the Kernel injects the model from the entry's tier"
            )
        outcome = self._breakers.call(
            entry.name, lambda: self._run_once(entry, prompt, bundle, budget_usd)
        )
        if isinstance(outcome, AgentRunError):
            raise outcome
        return outcome

    def _run_once(
        self, entry: RegistryEntry, prompt: str, bundle: str, budget_usd: Decimal | None
    ) -> AgentRunResult | AgentRunError:
        """One run of `entry`, inside its span; a usage limit is returned as `AgentRunError`.

        Returned rather than raised so the breaker, which watches for a flaking model, does
        not count a budget stop as a failure. The run gets its own `RunUsage`, which
        pydantic-ai increments in place, so the spending is known even when the run is stopped
        by a limit and no result exists. The Kernel's instructions replace whatever the Agent
        object carries, so an agent's own `instructions` never reach the model.
        """
        with logfire.span(SPAN_NAME, role=entry.name, tier=entry.tier) as span:
            model = self._model_factory(self._model_name(entry))
            run_usage = RunUsage()
            try:
                with entry.agent.override(
                    instructions=instruction_parts(entry, bundle, self._root)
                ):
                    result = entry.agent.run_sync(
                        prompt,
                        model=model,
                        usage_limits=self._usage_limits(entry, budget_usd),
                        usage=run_usage,
                    )
            except UsageLimitExceeded as error:
                usage = _usage_of(run_usage)
                _record_usage(span, usage)
                return AgentRunError(str(error), usage)
            usage = _usage_of(result.usage)
            _record_usage(span, usage)
            span.set_attribute(
                VALIDATION_RETRIES_ATTRIBUTE, _validation_retries(result.all_messages())
            )
            return AgentRunResult(output=result.output, usage=usage)

    def _usage_limits(self, entry: RegistryEntry, budget_usd: Decimal | None) -> UsageLimits:
        """The run's budget: the coding roles may make more requests than the others, and the
        USD budget also binds as tokens at the fallback price for a model that reports none."""
        limit = (
            self._settings.ra_coder_request_limit
            if entry.name in CODER_ROLES
            else self._settings.ra_request_limit
        )
        budget = budget_usd if budget_usd is not None else self._settings.ra_budget_usd
        return UsageLimits(
            request_limit=limit,
            cost_limit=budget,
            total_tokens_limit=int(budget * 1_000_000 / FALLBACK_USD_PER_MILLION_TOKENS),
        )

    def _model_name(self, entry: RegistryEntry) -> str:
        """The model the entry's tier calls for, from Settings."""
        if entry.tier == "judge":
            return self._settings.ra_judge_model
        return self._settings.ra_model


def _usage_of(usage: RunUsage) -> Usage:
    """The Kernel's `Usage` for a run's `RunUsage`; an unpriceable run costs `Decimal("0")`."""
    return Usage(
        requests=usage.requests,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost or Decimal("0"),
    )


def _record_usage(span: logfire.LogfireSpan, usage: Usage) -> None:
    """Put what the run spent on its span, whether it finished or hit a limit."""
    span.set_attribute(REQUESTS_ATTRIBUTE, usage.requests)
    span.set_attribute(COST_ATTRIBUTE, float(usage.cost_usd))


def _validation_retries(messages: list[ModelMessage]) -> int:
    """How often the run was asked again for a valid output or a valid tool call."""
    return sum(isinstance(part, RetryPromptPart) for message in messages for part in message.parts)
