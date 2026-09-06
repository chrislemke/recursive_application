"""The Providers: the Kernel adapter behind the agent runtime's `model_factory` seam.

One factory hides the scheme of a model name, the credentials each tier needs, and the build
of a model from its name, so neither the CLI nor the Judge Model setter spells a Provider.
Messages name a variable, a path, or a command to run, never a value.
"""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx2
from pydantic_ai.models import Model, infer_model

from recursive_application.kernel.settings import (
    API_KEY_VARIABLE,
    ENV_FILENAME,
    OPENAI_API_KEY_VARIABLE,
    Settings,
    SettingsError,
)

EXAMPLE_MODEL_NAME = "openrouter:anthropic/claude-sonnet-5"
"""The form a model name takes, shown when a name has no scheme."""

CHATGPT_SCHEME = "chatgpt"
"""The scheme paid for with the Operator's ChatGPT plan through the Codex Sign-in."""

SIGN_IN_COMMAND = "codex login"
"""The Operator's step that creates the Sign-in; the Kernel never signs in itself."""

KEYED_SCHEMES: Mapping[str, str] = {
    "openrouter": API_KEY_VARIABLE,
    "openai": OPENAI_API_KEY_VARIABLE,
    "openai-responses": OPENAI_API_KEY_VARIABLE,
    "openai-chat": OPENAI_API_KEY_VARIABLE,
}
"""The schemes paid for with a key, and the variable that holds it; the Settings field is the
variable lower-cased. The only place a keyed scheme is spelled."""

SIGN_IN_FILENAME = "auth.json"
"""The file the Codex CLI writes under `CODEX_HOME` when the Operator signs in."""


class ProviderError(SettingsError):
    """A model name or a credential the Kernel cannot use; the message never holds a value."""


def scheme_of(name: str) -> str:
    """The scheme of a model name: the text before the first `:`.

    A name without one is refused here rather than deep inside pydantic-ai, so the Operator sees
    the expected form.
    """
    scheme, separator, _ = name.partition(":")
    if not separator:
        raise ProviderError(f"model name {name!r} has no scheme; the form is {EXAMPLE_MODEL_NAME}")
    return scheme


def sign_in_path(settings: Settings) -> Path:
    """Where the Operator's ChatGPT Sign-in lives: `auth.json` under `codex_home`."""
    return settings.codex_home / SIGN_IN_FILENAME


def require_credentials(settings: Settings) -> None:
    """Raise `ProviderError` naming what the Operator must set before anything runs.

    Each distinct model name among the two tiers is checked by its scheme: a keyed scheme needs
    its variable non-blank; `chatgpt` needs the Sign-in file to exist. Any other scheme is left
    to pydantic-ai, which raises its own error when the model is built.
    """
    for name in dict.fromkeys((settings.ra_model, settings.ra_judge_model)):
        scheme = scheme_of(name)
        variable = KEYED_SCHEMES.get(scheme)
        if variable is not None and not getattr(settings, variable.lower()):
            raise ProviderError(
                f"{variable} is not set for {name!r}; put it in {ENV_FILENAME} or the environment"
            )
        if scheme == CHATGPT_SCHEME and not sign_in_path(settings).is_file():
            raise ProviderError(
                f"no ChatGPT sign-in at {sign_in_path(settings)} for {name!r}; "
                f"run {SIGN_IN_COMMAND}"
            )


def _utc_now() -> datetime:
    """The default clock: an aware UTC instant."""
    return datetime.now(UTC)


def model_factory(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = _utc_now,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Callable[[str], Model]:
    """The adapter `AgentRunner` and the Judge Model setter receive: a model from its name.

    Every name is built by pydantic-ai's `infer_model`, which reads the exported keys and makes
    no network call. `clock` and `transport` are the subscription Provider's seams, part of the
    signature so its callers never change.
    """

    def build(name: str) -> Model:
        return infer_model(name)

    return build
