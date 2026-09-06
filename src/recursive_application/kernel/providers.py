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

from recursive_application.kernel.chatgpt import (
    SIGN_IN_COMMAND,
    SIGN_IN_FILENAME,
    SignInError,
    chatgpt_model,
    load_sign_in,
)
from recursive_application.kernel.settings import (
    API_KEY_VARIABLE,
    CODEX_HOME_VARIABLE,
    ENV_FILENAME,
    OPENAI_API_KEY_VARIABLE,
    Settings,
    SettingsError,
)

EXAMPLE_MODEL_NAME = "openrouter:anthropic/claude-sonnet-5"
"""The form a model name takes, shown when a name has no scheme."""

CHATGPT_SCHEME = "chatgpt"
"""The scheme paid for with the Operator's ChatGPT plan through the Codex Sign-in."""

KEYED_SCHEMES: Mapping[str, str] = {
    "openrouter": API_KEY_VARIABLE,
    "openai": OPENAI_API_KEY_VARIABLE,
    "openai-responses": OPENAI_API_KEY_VARIABLE,
    "openai-chat": OPENAI_API_KEY_VARIABLE,
}
"""The schemes paid for with a key, and the variable that holds it; the Settings field is the
variable lower-cased. The only place a keyed scheme is spelled."""


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


def _utc_now() -> datetime:
    """The default clock: an aware UTC instant."""
    return datetime.now(UTC)


def instant_text(instant: datetime) -> str:
    """An aware instant as ISO 8601 UTC with a `Z`, the form the Operator reads it in."""
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_credentials(settings: Settings, *, clock: Callable[[], datetime] = _utc_now) -> None:
    """Raise `ProviderError` naming what the Operator must set before anything runs.

    Each distinct model name among the two tiers is checked by its scheme: a keyed scheme needs
    its variable non-blank; `chatgpt` needs a Sign-in that loads and whose token outlives a run
    of `ra_max_minutes` starting at `clock()`. Any other scheme is left to pydantic-ai, which
    raises its own error when the model is built.
    """
    for name in dict.fromkeys((settings.ra_model, settings.ra_judge_model)):
        scheme = scheme_of(name)
        variable = KEYED_SCHEMES.get(scheme)
        if variable is not None and not getattr(settings, variable.lower()):
            raise ProviderError(
                f"{variable} is not set for {name!r}; put it in {ENV_FILENAME} or the environment"
            )
        if scheme == CHATGPT_SCHEME:
            _require_sign_in(settings, name, clock())


def _require_sign_in(settings: Settings, name: str, now: datetime) -> None:
    """The `chatgpt` check: the Sign-in loads and its token outlives the run's wall time.

    A Sign-in that does not load is refused with its own message plus the second remedy, a
    `CODEX_HOME` naming the directory the Operator signed in under.
    """
    path = sign_in_path(settings)
    try:
        sign_in = load_sign_in(path)
    except SignInError as error:
        raise ProviderError(
            f"for {name!r}: {error}, or point {CODEX_HOME_VARIABLE} at the directory "
            "the Codex CLI signed in under"
        ) from error
    expires_at = sign_in.expires_at
    if expires_at is not None and not sign_in.valid_for(now, settings.ra_max_minutes):
        raise ProviderError(
            f"the ChatGPT Sign-in at {path} for {name!r} expires at {instant_text(expires_at)}, "
            f"before a run of {settings.ra_max_minutes} minutes would end; run {SIGN_IN_COMMAND}"
        )


def model_factory(
    settings: Settings,
    *,
    clock: Callable[[], datetime] = _utc_now,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Callable[[str], Model]:
    """The adapter `AgentRunner` and the Judge Model setter receive: a model from its name.

    A `chatgpt:` name is the subscription Provider over the Sign-in at `sign_in_path(settings)`,
    read by `clock` and carried by `transport` (the network by default). Every other name is
    built by pydantic-ai's `infer_model`, which reads the exported keys. Neither makes a network
    call at build time.
    """

    def build(name: str) -> Model:
        scheme, _, model_name = name.partition(":")
        if scheme == CHATGPT_SCHEME:
            return chatgpt_model(
                model_name,
                sign_in_path=sign_in_path(settings),
                clock=clock,
                transport=transport,
                originator=settings.ra_chatgpt_originator,
            )
        return infer_model(name)

    return build
