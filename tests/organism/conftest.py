"""Fixtures for the Organism test suite: a checkout layout and one real tool call.

`call_tool` drives a toolset the way an agent would, through a `FunctionModel` that calls
one tool and then repeats the tool's reply as its output, so a test observes exactly what a
model would see, refusals included.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import AbstractToolset


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A checkout laid out like this repository, with a secret in its environment file.

    Resolved, because `tmp_path` sits under the `/var` symlink on macOS and every path a
    tool reports has been through `Path.resolve()`.
    """
    checkout = (tmp_path / "checkout").resolve()
    for directory in (
        "src/recursive_application/organism",
        "tests/organism",
        "wiki/pages/lessons",
        "evals",
        "docs",
        ".ra/runs",
        ".venv/lib",
    ):
        (checkout / directory).mkdir(parents=True)
    (checkout / "README.md").write_text("# checkout\n")
    (checkout / ".env").write_text("OPENROUTER_API_KEY=sk-or-secret\n")
    return checkout


def _reply_text(message: ModelMessage) -> str:
    """The text of every tool reply in `message`, whether a return or a retry prompt."""
    replies: list[str] = []
    for part in message.parts:
        if isinstance(part, ToolReturnPart):
            replies.append(str(part.content))
        elif isinstance(part, RetryPromptPart):
            replies.append(part.content if isinstance(part.content, str) else str(part.content))
    return "\n".join(replies)


def call_tool(toolsets: Sequence[AbstractToolset[Any]], name: str, args: dict[str, Any]) -> str:
    """Call one tool on `toolsets` through an agent and return its reply as plain text."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(messages) == 1:
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return ModelResponse(parts=[TextPart(_reply_text(messages[-1]))])

    agent = Agent(FunctionModel(respond), name="tool-probe", toolsets=list(toolsets))
    return agent.run_sync("probe").output
