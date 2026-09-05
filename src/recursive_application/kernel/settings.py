"""Kernel Settings: the provider key, the models, and the Loop's limits.

Values come from environment variables (upper-cased field names) and, below them in
precedence, the `.env` file at `REPO_ROOT`; `.env.example` documents them. The key is
never printed or logged.
"""

import os
from decimal import Decimal
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from recursive_application.kernel.paths import REPO_ROOT

ENV_FILENAME = ".env"
API_KEY_VARIABLE = "OPENROUTER_API_KEY"
LOGFIRE_TOKEN_VARIABLE = "LOGFIRE_TOKEN"


class SettingsError(RuntimeError):
    """A Setting the Kernel needs is missing; the message names the variable, never a value."""


class Settings(BaseSettings):
    """The Kernel's configuration, with the spec's defaults.

    No `env_file` is configured here on purpose: `load_settings` names the file explicitly, so
    nothing is ever read from the working directory. A blank value reads as unset, and keys the
    file holds for other tools are ignored.
    """

    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    openrouter_api_key: str = Field(default="", repr=False)
    ra_model: str = "openrouter:anthropic/claude-sonnet-5"
    ra_judge_model: str = "openrouter:openai/gpt-5.4-mini"
    logfire_token: str | None = Field(default=None, repr=False)
    ra_max_iterations: int = 5
    ra_max_minutes: int = 30
    ra_budget_usd: Decimal = Decimal("5")
    ra_no_progress_iterations: int = 2
    ra_request_limit: int = 50
    ra_coder_request_limit: int = 100
    ra_breaker_failures: int = 3
    ra_breaker_reset_s: int = 60

    @field_validator("openrouter_api_key")
    @classmethod
    def _strip_key(cls, value: str) -> str:
        """Real environment variables are never stripped by anyone else, so do it here."""
        return value.strip()

    def require_api_key(self) -> None:
        """Raise `SettingsError` naming `OPENROUTER_API_KEY` when the key is blank."""
        if not self.openrouter_api_key:
            raise SettingsError(
                f"{API_KEY_VARIABLE} is not set; put it in {ENV_FILENAME} or the environment"
            )


def load_settings(env_file: Path | None = None) -> Settings:
    """Load `Settings` from the environment and `env_file` (default `REPO_ROOT/.env`).

    Exports `OPENROUTER_API_KEY` and `LOGFIRE_TOKEN` into `os.environ` without overwriting
    values already there, so Pydantic AI's OpenRouter provider and Logfire find them. A blank
    variable counts as absent, as it does for `Settings` itself; a blank key or an absent token
    is not exported.
    """
    settings = Settings(_env_file=env_file if env_file is not None else REPO_ROOT / ENV_FILENAME)
    if settings.openrouter_api_key and not os.environ.get(API_KEY_VARIABLE):
        os.environ[API_KEY_VARIABLE] = settings.openrouter_api_key
    if settings.logfire_token is not None and not os.environ.get(LOGFIRE_TOKEN_VARIABLE):
        os.environ[LOGFIRE_TOKEN_VARIABLE] = settings.logfire_token
    return settings
