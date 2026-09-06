"""The Providers, through `kernel.providers`.

In-process over `Settings(_env_file=None, ...)` built here, never the real `.env`; the Sign-in
file lives under `tmp_path`, never the real `~/.codex`, so every `chatgpt` case sets
`codex_home` explicitly. Models are built with dummy keys set through `monkeypatch`; building one
makes no network call.
"""

from pathlib import Path

import pytest
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.models.test import TestModel

from recursive_application.kernel.providers import (
    ProviderError,
    model_factory,
    require_credentials,
    scheme_of,
    sign_in_path,
)
from recursive_application.kernel.settings import Settings


@pytest.mark.parametrize(
    ("name", "scheme"),
    [("openrouter:anthropic/claude-sonnet-5", "openrouter"), ("chatgpt:gpt-5.4", "chatgpt")],
)
def test_the_scheme_is_the_text_before_the_first_colon(name: str, scheme: str) -> None:
    assert scheme_of(name) == scheme


def test_a_name_without_a_scheme_is_refused_and_shown_the_expected_form() -> None:
    with pytest.raises(ProviderError, match="openrouter:"):
        scheme_of("gpt-5.4")


def test_the_default_models_need_the_openrouter_key_and_the_refusal_names_the_variable() -> None:
    with pytest.raises(ProviderError, match="OPENROUTER_API_KEY"):
        require_credentials(Settings(_env_file=None))


def test_the_default_models_pass_with_the_openrouter_key_set() -> None:
    require_credentials(Settings(_env_file=None, openrouter_api_key="sk-or-test"))


def test_an_openai_primary_needs_the_openai_key_and_the_refusal_names_the_variable() -> None:
    settings = Settings(_env_file=None, ra_model="openai:gpt-5.4", openrouter_api_key="sk-or-test")

    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        require_credentials(settings)


def test_an_openai_primary_passes_with_both_keys_set() -> None:
    settings = Settings(
        _env_file=None,
        ra_model="openai:gpt-5.4",
        openrouter_api_key="sk-or-test",
        openai_api_key="sk-test",
    )

    require_credentials(settings)


def test_the_sign_in_lives_at_auth_json_under_codex_home(tmp_path: Path) -> None:
    assert sign_in_path(Settings(_env_file=None, codex_home=tmp_path)) == tmp_path / "auth.json"


def test_a_chatgpt_judge_without_a_sign_in_is_refused_naming_the_file_and_codex_login(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        ra_judge_model="chatgpt:gpt-5.4-mini",
        openrouter_api_key="sk-or-test",
        codex_home=tmp_path,
    )

    with pytest.raises(ProviderError, match=r"auth\.json(?s:.*)codex login"):
        require_credentials(settings)


def test_a_chatgpt_judge_passes_once_the_sign_in_file_exists(tmp_path: Path) -> None:
    (tmp_path / "auth.json").write_text("{}")
    settings = Settings(
        _env_file=None,
        ra_judge_model="chatgpt:gpt-5.4-mini",
        openrouter_api_key="sk-or-test",
        codex_home=tmp_path,
    )

    require_credentials(settings)


def test_a_scheme_the_kernel_does_not_key_is_not_checked_here() -> None:
    settings = Settings(
        _env_file=None,
        ra_model="anthropic:claude-sonnet-5",
        ra_judge_model="anthropic:claude-sonnet-5",
    )

    require_credentials(settings)


def test_the_factory_builds_an_openrouter_model_from_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    model = model_factory(Settings(_env_file=None))("openrouter:x/y")

    assert model.system == "openrouter"
    assert model.model_name == "x/y"


def test_the_factory_builds_an_openai_responses_model_from_its_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    model = model_factory(Settings(_env_file=None))("openai:gpt-5.4")

    assert isinstance(model, OpenAIResponsesModel)
    assert model.model_name == "gpt-5.4"


def test_the_factory_builds_the_test_model_from_its_name() -> None:
    assert isinstance(model_factory(Settings(_env_file=None))("test"), TestModel)


def test_two_calls_of_the_factory_give_two_objects() -> None:
    build = model_factory(Settings(_env_file=None))

    assert build("test") is not build("test")
