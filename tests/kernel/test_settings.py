"""Kernel Settings, loaded from the process environment and an explicit env file.

Tests never read the real `.env`: every load names a file under `tmp_path` or no file at all.
The key is compared, never printed.
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest

from recursive_application.kernel.settings import Settings, SettingsError, load_settings


def test_with_no_file_and_no_variables_the_defaults_are_the_spec_literals() -> None:
    settings = Settings(_env_file=None)

    assert settings.openrouter_api_key == ""
    assert settings.ra_model == "openrouter:anthropic/claude-sonnet-5"
    assert settings.ra_judge_model == "openrouter:openai/gpt-5.4-mini"
    assert settings.logfire_token is None
    assert settings.ra_max_iterations == 5
    assert settings.ra_max_minutes == 30
    assert settings.ra_budget_usd == Decimal("5")
    assert settings.ra_no_progress_iterations == 2
    assert settings.ra_request_limit == 50
    assert settings.ra_coder_request_limit == 100
    assert settings.ra_breaker_failures == 3
    assert settings.ra_breaker_reset_s == 60
    assert settings.openai_api_key == ""
    assert settings.codex_home == Path.home() / ".codex"
    assert settings.ra_chatgpt_originator == "recursive_application"


def test_require_api_key_raises_the_settings_error_naming_the_variable_for_a_blank_key() -> None:
    settings = Settings(_env_file=None)

    with pytest.raises(SettingsError, match="OPENROUTER_API_KEY"):
        settings.require_api_key()


def test_require_api_key_passes_for_a_set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    settings = Settings(_env_file=None)

    settings.require_api_key()


def test_an_environment_variable_wins_over_the_file_for_the_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("RA_MAX_ITERATIONS=7\n")
    monkeypatch.setenv("RA_MAX_ITERATIONS", "42")

    settings = load_settings(env_file)

    assert settings.ra_max_iterations == 42


def test_an_unknown_key_in_the_env_file_is_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("UNKNOWN_KEY=zzz\nRA_MAX_ITERATIONS=7\n")

    settings = load_settings(env_file)

    assert settings.ra_max_iterations == 7


def test_a_key_from_the_environment_is_stripped_of_surrounding_whitespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", " sk-or-env ")

    settings = load_settings(tmp_path / "absent.env")

    assert settings.openrouter_api_key == "sk-or-env"


def test_an_env_file_is_parsed_with_whitespace_stripped_and_a_blank_token_as_none(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "OPENROUTER_API_KEY= sk-or-test \n"
        "RA_MODEL=openrouter:x/y\n"
        "LOGFIRE_TOKEN=\n"
        "RA_MAX_ITERATIONS=7\n"
    )

    settings = load_settings(env_file)

    assert settings.openrouter_api_key == "sk-or-test"
    assert settings.ra_model == "openrouter:x/y"
    assert settings.logfire_token is None
    assert settings.ra_max_iterations == 7
    assert settings.ra_judge_model == "openrouter:openai/gpt-5.4-mini"
    assert settings.ra_max_minutes == 30
    assert settings.ra_budget_usd == Decimal("5")
    assert settings.ra_no_progress_iterations == 2
    assert settings.ra_request_limit == 50
    assert settings.ra_coder_request_limit == 100
    assert settings.ra_breaker_failures == 3
    assert settings.ra_breaker_reset_s == 60


def test_an_openai_key_from_the_environment_is_stripped_of_surrounding_whitespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", " sk-test ")

    settings = load_settings(tmp_path / "absent.env")

    assert settings.openai_api_key == "sk-test"


def test_an_env_file_gives_the_openai_key_and_expands_the_tilde_in_codex_home(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENAI_API_KEY= sk-test \nCODEX_HOME=~/codex-alt\n")

    settings = load_settings(env_file)

    assert settings.openai_api_key == "sk-test"
    assert settings.codex_home == Path.home() / "codex-alt"


def test_load_settings_exports_the_key_and_the_token_into_the_process_environment(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENROUTER_API_KEY=sk-or-test\nLOGFIRE_TOKEN=lf-test\n")

    load_settings(env_file)

    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-test"
    assert os.environ["LOGFIRE_TOKEN"] == "lf-test"


def test_load_settings_exports_the_openai_key_into_the_process_environment(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENAI_API_KEY=sk-test\n")

    load_settings(env_file)

    assert os.environ["OPENAI_API_KEY"] == "sk-test"


def test_load_settings_does_not_rewrite_an_openai_key_the_operator_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", " sk-env ")

    settings = load_settings(tmp_path / "absent.env")

    assert settings.openai_api_key == "sk-env"
    assert os.environ["OPENAI_API_KEY"] == " sk-env "


def test_load_settings_leaves_an_already_set_variable_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENROUTER_API_KEY=sk-or-file\nLOGFIRE_TOKEN=lf-file\n")
    monkeypatch.setenv("LOGFIRE_TOKEN", "lf-env")

    load_settings(env_file)

    assert os.environ["LOGFIRE_TOKEN"] == "lf-env"
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-file"


def test_load_settings_does_not_rewrite_a_variable_the_user_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", " sk-or-env ")

    settings = load_settings(tmp_path / "absent.env")

    assert settings.openrouter_api_key == "sk-or-env"
    assert os.environ["OPENROUTER_API_KEY"] == " sk-or-env "


def test_a_blank_variable_in_the_environment_is_filled_from_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENROUTER_API_KEY=sk-or-file\n")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    settings = load_settings(env_file)

    assert settings.openrouter_api_key == "sk-or-file"
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-file"


def test_the_key_and_the_token_never_appear_in_the_settings_repr(tmp_path: Path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-test\nOPENAI_API_KEY=sk-test\nLOGFIRE_TOKEN=lf-test\n"
    )

    settings = load_settings(env_file)

    assert "sk-or-test" not in repr(settings)
    assert "sk-test" not in repr(settings)
    assert "lf-test" not in repr(settings)


def test_load_settings_does_not_export_a_blank_openai_key(tmp_path: Path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENAI_API_KEY=\n")

    load_settings(env_file)

    assert "OPENAI_API_KEY" not in os.environ


def test_load_settings_does_not_export_a_blank_token(tmp_path: Path) -> None:
    env_file = tmp_path / "test.env"
    env_file.write_text("OPENROUTER_API_KEY=sk-or-test\nLOGFIRE_TOKEN=\n")

    load_settings(env_file)

    assert "LOGFIRE_TOKEN" not in os.environ
