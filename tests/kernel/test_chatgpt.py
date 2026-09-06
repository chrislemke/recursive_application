"""The ChatGPT Sign-in and the backend adapter, through `kernel.chatgpt`.

Every Sign-in file is written by the test under `tmp_path` with fake JWTs built here; the real
`~/.codex` is never read. The backend is an `httpx2.MockTransport` handler that records what it
receives and answers an event stream, so nothing reaches the network. Time is the injected clock.
"""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import ModelHTTPError

from recursive_application.kernel.chatgpt import (
    SignIn,
    SignInError,
    chatgpt_model,
    load_sign_in,
    served_models,
)

ACCOUNT_ID = "acct_test_0001"
PLAN_TYPE = "plus"
EXP = 1_788_775_200
"""The access token's `exp`, which is 2026-09-07T10:00:00Z."""
ONE_HOUR_BEFORE_EXPIRY = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
LAST_REFRESH = "2026-09-06T08:00:00Z"
REFRESH_TOKEN = "rt_fake_refresh_token_0001"
ORIGINATOR = "recursive_application"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwt(payload: dict[str, Any]) -> str:
    """A fake JWT: base64url header and payload with a signature nobody verifies."""
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    return f"{header}.{_b64url(json.dumps(payload).encode())}.fake-signature"


ID_TOKEN = _jwt(
    {
        "https://api.openai.com/auth": {
            "chatgpt_account_id": ACCOUNT_ID,
            "chatgpt_plan_type": PLAN_TYPE,
        }
    }
)
ACCESS_TOKEN = _jwt({"exp": EXP, "sub": "user_0001"})


def _sign_in_document(
    *,
    access_token: str = ACCESS_TOKEN,
    account_id: str | None = ACCOUNT_ID,
    auth_mode: str | None = "chatgpt",
) -> dict[str, Any]:
    """A file in the Codex CLI's `auth.json` schema; `auth_mode=None` leaves the key out."""
    document: dict[str, Any] = {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": ID_TOKEN,
            "access_token": access_token,
            "refresh_token": REFRESH_TOKEN,
            "account_id": account_id,
        },
        "last_refresh": LAST_REFRESH,
    }
    if auth_mode is not None:
        document = {"auth_mode": auth_mode, **document}
    return document


def _write_sign_in(path: Path, **overrides: Any) -> bytes:
    """Write a Sign-in file and return the exact bytes written."""
    data = json.dumps(_sign_in_document(**overrides), indent=2).encode()
    path.write_bytes(data)
    return data


def _completed_response(text: str, *, model: str) -> dict[str, Any]:
    """A Responses API `Response` object with one message and the usage the tests assert."""
    return {
        "id": "resp_test_0001",
        "object": "response",
        "created_at": 1_788_771_600,
        "status": "completed",
        "model": model,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "id": "msg_0001",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 12,
            "output_tokens": 3,
            "total_tokens": 15,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _event_stream(text: str, *, model: str) -> bytes:
    """The backend's event stream for one turn, ending in `response.completed`."""
    completed = _completed_response(text, model=model)
    events = [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {**completed, "status": "in_progress", "output": [], "usage": None},
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "item_id": "msg_0001",
            "output_index": 0,
            "content_index": 0,
            "delta": text,
            "logprobs": [],
        },
        {"type": "response.completed", "sequence_number": 2, "response": completed},
    ]
    return b"".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode() for event in events
    )


def _streaming_backend(seen: list[httpx2.Request]) -> httpx2.MockTransport:
    """A backend that records every request and answers the event stream for `hello`."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        model = json.loads(request.content)["model"]
        return httpx2.Response(
            200,
            content=_event_stream("hello", model=model),
            headers={"content-type": "text/event-stream"},
        )

    return httpx2.MockTransport(handle)


def _failing_backend(
    seen: list[httpx2.Request], status: int, error: dict[str, Any]
) -> httpx2.MockTransport:
    """A backend that records every request and answers `status` with the JSON `error`."""

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            status, json={"error": error}, headers={"x-codex-primary-used-percent": "100"}
        )

    return httpx2.MockTransport(handle)


def _model(
    sign_in_path: Path, transport: httpx2.MockTransport, *, now: datetime = ONE_HOUR_BEFORE_EXPIRY
) -> models.Model:
    return chatgpt_model(
        "gpt-5.5",
        sign_in_path=sign_in_path,
        clock=lambda: now,
        transport=transport,
        originator=ORIGINATOR,
        session_id="s1",
    )


def test_load_sign_in_reads_the_codex_file_and_keeps_no_token_in_its_repr(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path)

    sign_in = load_sign_in(path)

    assert isinstance(sign_in, SignIn)
    assert sign_in.access_token == ACCESS_TOKEN
    assert sign_in.account_id == "acct_test_0001"
    assert sign_in.plan_type == "plus"
    assert sign_in.last_refresh == datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
    shown = repr(sign_in)
    assert ACCESS_TOKEN not in shown
    assert ID_TOKEN not in shown
    assert REFRESH_TOKEN not in shown


def test_a_null_account_id_is_taken_from_the_id_tokens_claim(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path, account_id=None)

    assert load_sign_in(path).account_id == "acct_test_0001"


def test_a_logged_out_file_without_tokens_raises_the_sign_in_error(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    path.write_text('{"OPENAI_API_KEY": null}')

    with pytest.raises(SignInError, match="codex login"):
        load_sign_in(path)


def test_a_missing_file_raises_the_sign_in_error_naming_the_path_and_codex_login(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auth.json"

    with pytest.raises(SignInError) as error:
        load_sign_in(path)

    assert str(path) in str(error.value)
    assert "codex login" in str(error.value)


def test_an_api_key_sign_in_is_refused_as_not_a_chatgpt_one(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path, auth_mode="apikey")

    with pytest.raises(SignInError, match="not a ChatGPT"):
        load_sign_in(path)


def test_an_older_file_without_auth_mode_loads(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path, auth_mode=None)

    assert load_sign_in(path).account_id == "acct_test_0001"


def test_expires_at_is_the_access_tokens_exp_and_valid_for_measures_the_run_against_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path)

    sign_in = load_sign_in(path)

    assert sign_in.expires_at == datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    assert sign_in.valid_for(datetime(2026, 9, 7, 9, 0, tzinfo=UTC), 30) is True
    assert sign_in.valid_for(datetime(2026, 9, 7, 9, 40, tzinfo=UTC), 30) is False


def test_a_token_without_exp_has_no_expiry_and_is_valid_for_any_run(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path, access_token=_jwt({"sub": "user_0001"}))

    sign_in = load_sign_in(path)

    assert sign_in.expires_at is None
    assert sign_in.valid_for(datetime(2026, 9, 7, 9, 40, tzinfo=UTC), 30) is True


def test_served_models_lists_the_slugs_of_the_codex_models_cache_in_file_order(
    tmp_path: Path,
) -> None:
    cache = {
        "fetched_at": "2026-09-06T08:18:49Z",
        "etag": 'W/"abc"',
        "client_version": "0.153.4",
        "models": [
            {"slug": "gpt-6-astra", "display_name": "GPT-6 Astra", "priority": 1},
            {"slug": "gpt-5.5", "display_name": "GPT-5.5", "priority": 12},
        ],
    }
    (tmp_path / "models_cache.json").write_text(json.dumps(cache))

    assert served_models(tmp_path) == ["gpt-6-astra", "gpt-5.5"]


def test_served_models_is_empty_without_a_cache_file(tmp_path: Path) -> None:
    assert served_models(tmp_path) == []


def test_a_run_sends_the_codex_headers_and_the_streaming_body_and_gets_the_completed_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    model = _model(path, _streaming_backend(seen))

    result = Agent(model, output_type=str, instructions="Answer briefly.").run_sync("hi")

    assert result.output == "hello"
    assert result.usage.requests == 1
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 3
    assert model.model_name == "gpt-5.5"
    assert model.system == "openai"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://chatgpt.com/backend-api/codex/responses"
    assert request.headers["authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert request.headers["chatgpt-account-id"] == "acct_test_0001"
    assert request.headers["originator"] == "recursive_application"
    assert request.headers["session-id"] == "s1"
    assert request.headers["user-agent"].startswith("recursive_application/")
    assert request.headers["accept"] == "text/event-stream"
    assert int(request.headers["content-length"]) == len(request.content)
    body = json.loads(request.content)
    assert body["stream"] is True
    assert body["store"] is False
    assert body["model"] == "gpt-5.5"
    assert body["instructions"] == "Answer briefly."


def test_a_sign_in_rewritten_between_two_runs_is_used_by_the_second_and_never_written_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    agent = Agent(_model(path, _streaming_backend(seen)), output_type=str)
    renewed_token = _jwt({"exp": EXP + 3600, "sub": "user_0001"})

    agent.run_sync("hi")
    written = _write_sign_in(path, access_token=renewed_token)
    agent.run_sync("hi again")

    assert [request.headers["authorization"] for request in seen] == [
        f"Bearer {ACCESS_TOKEN}",
        f"Bearer {renewed_token}",
    ]
    assert path.read_bytes() == written


def test_an_expired_sign_in_answers_a_synthetic_401_naming_codex_login_without_a_backend_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    one_second_after_expiry = datetime(2026, 9, 7, 10, 0, 1, tzinfo=UTC)
    model = _model(path, _streaming_backend(seen), now=one_second_after_expiry)

    with pytest.raises(ModelHTTPError) as error:
        Agent(model, output_type=str).run_sync("hi")

    assert error.value.status_code == 401
    body = error.value.body
    assert isinstance(body, dict)
    assert "codex login" in body["message"]
    assert ACCESS_TOKEN not in str(error.value)
    assert seen == []


def test_a_401_from_the_backend_is_one_model_http_error_after_one_call_with_no_token_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    backend = _failing_backend(
        seen,
        401,
        {"message": "token expired", "type": "invalid_request_error", "code": "token_expired"},
    )

    with pytest.raises(ModelHTTPError) as error:
        Agent(_model(path, backend), output_type=str).run_sync("hi")

    assert error.value.status_code == 401
    assert len(seen) == 1
    assert ACCESS_TOKEN not in str(error.value)


def test_a_usage_limit_429_from_the_backend_is_one_model_http_error_with_the_backends_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    backend = _failing_backend(
        seen, 429, {"type": "usage_limit_reached", "resets_at": 1_789_000_000, "plan_type": "plus"}
    )

    with pytest.raises(ModelHTTPError) as error:
        Agent(_model(path, backend), output_type=str).run_sync("hi")

    assert error.value.status_code == 429
    assert len(seen) == 1
    body = error.value.body
    assert isinstance(body, dict)
    assert body["type"] == "usage_limit_reached"
    assert body["resets_at"] == 1_789_000_000
    assert error.value.headers is not None
    assert error.value.headers["x-codex-primary-used-percent"] == "100"
    assert ACCESS_TOKEN not in str(error.value)


def test_a_sign_in_removed_between_runs_answers_a_synthetic_401_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []
    agent = Agent(_model(path, _streaming_backend(seen)), output_type=str)
    agent.run_sync("hi")

    path.unlink()
    with pytest.raises(ModelHTTPError) as error:
        agent.run_sync("hi again")

    assert error.value.status_code == 401
    body = error.value.body
    assert isinstance(body, dict)
    assert "codex login" in body["message"]
    assert len(seen) == 1


def test_a_stream_that_ends_without_response_completed_is_a_502_model_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)
    seen: list[httpx2.Request] = []

    def truncated(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        created = {"type": "response.created", "sequence_number": 0, "response": {}}
        return httpx2.Response(
            200,
            content=f"event: response.created\ndata: {json.dumps(created)}\n\n".encode(),
            headers={"content-type": "text/event-stream"},
        )

    with pytest.raises(ModelHTTPError) as error:
        Agent(_model(path, httpx2.MockTransport(truncated)), output_type=str).run_sync("hi")

    assert error.value.status_code == 502
    body = error.value.body
    assert isinstance(body, dict)
    assert "response.completed" in body["message"]
    assert len(seen) == 1


def test_a_sign_in_file_that_is_not_a_json_object_raises_the_sign_in_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "auth.json"
    path.write_text("[]")

    with pytest.raises(SignInError, match="codex login") as error:
        load_sign_in(path)

    assert str(path) in str(error.value)


def test_served_models_is_empty_when_the_cache_holds_no_list(tmp_path: Path) -> None:
    (tmp_path / "models_cache.json").write_text('{"models": null}')

    assert served_models(tmp_path) == []


def test_an_exp_claim_outside_the_calendar_reads_as_no_expiry(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    _write_sign_in(path, access_token=_jwt({"exp": 1e300}))

    assert load_sign_in(path).expires_at is None


def test_a_stream_that_is_not_utf8_is_a_502_model_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    path = tmp_path / "auth.json"
    _write_sign_in(path)

    def garbled(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=b"data: \xff\xfe\n\n", headers={"content-type": "text/event-stream"}
        )

    with pytest.raises(ModelHTTPError) as error:
        Agent(_model(path, httpx2.MockTransport(garbled)), output_type=str).run_sync("hi")

    assert error.value.status_code == 502
