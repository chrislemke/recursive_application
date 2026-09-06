"""Support for the Loop runner's tests: scripted models and a checkout-shaped repository.

The Loop calls every agent through the real `AgentRunner`, so a test scripts the models rather
than the runner: `scripted_models` gives each role its next output, dispatching on the `Role:`
line of the State Bundle in the request's instructions, and records every request so a test can
assert on the Loop position and the prompt an agent received. The `checkout` fixture lays the
temporary git repository out the way the real checkout is laid out, so the State Bundle, the
frontier ratios, and the Wiki all read real files.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

ROLE_LINE = re.compile(r"^Role: (.+)$", re.MULTILINE)
"""The State Bundle line a scripted model dispatches on."""


@dataclass(frozen=True)
class ScriptedRequest:
    """One model request a scripted role received: its instructions and its user prompt."""

    role: str
    instructions: str
    prompt: str


class ScriptedModels:
    """A `model_factory` whose models answer each role from its script, one output per call."""

    def __init__(
        self, script: Mapping[str, Sequence[Any]], *, usage: RequestUsage | None = None
    ) -> None:
        self._remaining = {role: list(outputs) for role, outputs in script.items()}
        self._usage = usage
        self.requests: dict[str, list[ScriptedRequest]] = {}

    def __call__(self, model_name: str) -> Model:
        """The model the agent runtime asks for; every role shares one scripted function."""
        return FunctionModel(self._respond)

    def prompts_for(self, role: str) -> list[str]:
        """The user prompts `role` received, in the order the Loop sent them."""
        return [request.prompt for request in self.requests.get(role, [])]

    def calls_for(self, role: str) -> int:
        """How often `role` was called."""
        return len(self.requests.get(role, []))

    def _respond(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """Answer as the role the instructions name, from that role's script."""
        instructions = info.instructions or ""
        role = _role_of(instructions)
        self.requests.setdefault(role, []).append(
            ScriptedRequest(role=role, instructions=instructions, prompt=_prompt_of(messages))
        )
        outputs = self._remaining.get(role, [])
        if not outputs:
            raise AssertionError(f"the script has no further output for the role {role!r}")
        return _response(outputs.pop(0), info, self._usage)


def scripted_models(
    script: Mapping[str, Sequence[Any]], *, usage: RequestUsage | None = None
) -> ScriptedModels:
    """A `model_factory` for `AgentRunner` that hands each role the outputs `script` lists.

    A contract comes back as the run's output tool call, a string as text, and an exception is
    raised where the model would have answered. Every scripted response reports `usage`, so a
    test can give the run a price the budget stop rule reads.
    """
    return ScriptedModels(script, usage=usage)


def _role_of(instructions: str) -> str:
    """The role the State Bundle's Loop position names in the instructions of this request."""
    match = ROLE_LINE.search(instructions)
    if match is None:
        raise AssertionError("the instructions carry no `Role:` line to dispatch on")
    return match.group(1).strip()


def _prompt_of(messages: list[ModelMessage]) -> str:
    """The user prompt of this request: the last one the run sent."""
    prompts = [
        part.content
        for message in messages
        for part in message.parts
        if isinstance(part, UserPromptPart)
    ]
    return str(prompts[-1]) if prompts else ""


def _response(output: Any, info: AgentInfo, usage: RequestUsage | None) -> ModelResponse:
    """A contract as the run's output tool call, an exception raised, anything else as text."""
    if isinstance(output, BaseException):
        raise output
    if isinstance(output, BaseModel):
        part: ToolCallPart | TextPart = ToolCallPart(
            info.output_tools[0].name, output.model_dump(mode="json")
        )
    else:
        part = TextPart(str(output))
    if usage is None:
        return ModelResponse(parts=[part])
    return ModelResponse(parts=[part], usage=usage)
