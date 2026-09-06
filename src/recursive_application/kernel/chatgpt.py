"""The ChatGPT Sign-in and the backend adapter.

The Operator signs in with the Codex CLI (`codex login`), which writes `$CODEX_HOME/auth.json`.
The Kernel reads that file and never writes it: refreshing the tokens is Codex's job. Nothing
here prints, logs, traces, or `repr`s a token.
"""

import base64
import importlib.metadata
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
from openai import AsyncOpenAI
from openai._streaming import SSEDecoder
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from recursive_application.kernel.settings import SettingsError

SIGN_IN_FILENAME = "auth.json"
"""The Codex CLI's Sign-in file, under `CODEX_HOME`."""

MODELS_CACHE_FILENAME = "models_cache.json"
"""The Codex CLI's cache of the models the backend serves, under `CODEX_HOME`."""

BACKEND_URL = "https://chatgpt.com/backend-api/codex"
"""The ChatGPT backend the subscription Provider talks to."""

AUTH_CLAIM = "https://api.openai.com/auth"
"""The id token's claim object holding `chatgpt_account_id` and `chatgpt_plan_type`."""

CHATGPT_AUTH_MODES = frozenset({"chatgpt", "chatgptAuthTokens"})
"""The `auth_mode` values of a Sign-in made with a ChatGPT account."""

SIGN_IN_COMMAND = "codex login"
"""What the Operator runs to make or renew the Sign-in."""

_PACKAGE_NAME = "recursive-application"
"""The distribution whose version the `User-Agent` header carries."""

_PLACEHOLDER_API_KEY = "replaced-per-request"
"""What the SDK is given as a key; the transport replaces the bearer it computes from it."""


class SignInError(SettingsError):
    """The Sign-in cannot be used; the message names the path and `codex login`, never a token."""


@dataclass(frozen=True)
class SignIn:
    """The Operator's ChatGPT Sign-in, as read from the Codex CLI's file.

    Only what a request and `ra status` need is kept: the refresh token and the id token stay
    in the file, because the Kernel never refreshes.
    """

    access_token: str = field(repr=False)
    account_id: str
    plan_type: str | None
    last_refresh: datetime | None

    @property
    def expires_at(self) -> datetime | None:
        """When the access token expires, from its `exp` claim; `None` when absent or unreadable."""
        exp = _jwt_payload(self.access_token).get("exp")
        if isinstance(exp, bool) or not isinstance(exp, int | float):
            return None
        try:
            return datetime.fromtimestamp(exp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    def valid_for(self, now: datetime, minutes: int) -> bool:
        """Whether the token outlives a run of `minutes` starting at `now`.

        A token without an `exp` claim counts as valid: Codex then decides by `last_refresh`,
        and the backend has the last word.
        """
        expires_at = self.expires_at
        return expires_at is None or expires_at > now + timedelta(minutes=minutes)


def load_sign_in(path: Path) -> SignIn:
    """Read the Sign-in from the Codex CLI's file at `path`."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SignInError(
            f"no readable Sign-in at {path} ({type(error).__name__}); run {SIGN_IN_COMMAND}"
        ) from error
    if not isinstance(document, dict):
        raise SignInError(f"the Sign-in at {path} is not a JSON object; run {SIGN_IN_COMMAND}")
    auth_mode = document.get("auth_mode")
    if auth_mode is not None and auth_mode not in CHATGPT_AUTH_MODES:
        raise SignInError(
            f"the Sign-in at {path} is not a ChatGPT one (auth_mode {auth_mode!r}); "
            f"run {SIGN_IN_COMMAND}"
        )
    tokens = document.get("tokens")
    if not isinstance(tokens, dict):
        raise SignInError(f"the Sign-in at {path} holds no tokens; run {SIGN_IN_COMMAND}")
    claims = _jwt_payload(str(tokens.get("id_token", ""))).get(AUTH_CLAIM)
    if not isinstance(claims, dict):
        claims = {}
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id") or claims.get("chatgpt_account_id")
    if not isinstance(access_token, str) or not isinstance(account_id, str):
        raise SignInError(
            f"the Sign-in at {path} holds no access token or names no account; "
            f"run {SIGN_IN_COMMAND}"
        )
    return SignIn(
        access_token=access_token,
        account_id=account_id,
        plan_type=claims.get("chatgpt_plan_type"),
        last_refresh=_instant(document.get("last_refresh")),
    )


def served_models(codex_home: Path) -> list[str]:
    """The model slugs the backend served, from the Codex CLI's cache under `codex_home`.

    For `ra status` and the Operator's choice of `RA_MODEL`; never a network call. `[]` when
    the cache is missing or unreadable.
    """
    try:
        cache = json.loads((codex_home / MODELS_CACHE_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = cache.get("models") if isinstance(cache, dict) else None
    if not isinstance(entries, list):
        return []
    return [
        entry["slug"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("slug"), str)
    ]


def chatgpt_model(
    model_name: str,
    *,
    sign_in_path: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    transport: httpx2.AsyncBaseTransport | None = None,
    originator: str,
    session_id: str | None = None,
) -> Model:
    """pydantic-ai's OpenAI Responses model, pointed at the ChatGPT backend through the Sign-in.

    The model is the library's own; the adaptation sits in the HTTP transport, which reads the
    Sign-in at `sign_in_path` fresh for every request. `transport` is what finally carries the
    request (the network by default; a mock in tests). `model.system` is `openai`, so pricing
    follows the OpenAI list. The SDK never retries (seams document of 2026-09-06, decision 8):
    a 429 is one model error.
    """
    identity = {
        "originator": originator,
        "user-agent": f"{originator}/{importlib.metadata.version(_PACKAGE_NAME)}",
        "session-id": session_id or str(uuid.uuid4()),
    }
    backend = _BackendTransport(
        sign_in_path=sign_in_path,
        clock=clock,
        inner=transport if transport is not None else httpx2.AsyncHTTPTransport(),
        identity=identity,
    )
    client = AsyncOpenAI(
        base_url=BACKEND_URL,
        api_key=_PLACEHOLDER_API_KEY,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=backend),
    )
    return OpenAIResponsesModel(model_name, provider=OpenAIProvider(openai_client=client))


class _BackendTransport(httpx2.AsyncBaseTransport):
    """Turns the SDK's Responses request into the one the ChatGPT backend accepts, and back.

    Per request: the Sign-in is read fresh (a refresh by the Codex CLI between two requests is
    picked up), the bearer, the account, and the Kernel's identity go on the headers, a
    non-streaming JSON body is rewritten to the streaming `store: false` one Codex sends, and
    the event stream is read to its `response.completed` event, whose `response` goes back as a
    plain JSON body. Never raises for a Sign-in or stream failure: the SDK would wrap an
    exception as a connection error and lose the message, so those are answered as responses;
    the inner transport's own connection errors pass through.
    """

    def __init__(
        self,
        *,
        sign_in_path: Path,
        clock: Callable[[], datetime],
        inner: httpx2.AsyncBaseTransport,
        identity: Mapping[str, str],
    ) -> None:
        self._sign_in_path = sign_in_path
        self._clock = clock
        self._inner = inner
        self._identity = dict(identity)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        try:
            sign_in = load_sign_in(self._sign_in_path)
        except SignInError as error:
            return _error_response(401, str(error), "sign_in_unavailable")
        expires_at = sign_in.expires_at
        if expires_at is not None and expires_at <= self._clock():
            return _error_response(
                401,
                f"the ChatGPT Sign-in at {self._sign_in_path} expired at "
                f"{expires_at.isoformat()}; run {SIGN_IN_COMMAND}",
                "sign_in_expired",
            )
        raw = await request.aread()
        headers = httpx2.Headers(request.headers)
        headers.update(self._identity)
        headers["authorization"] = f"Bearer {sign_in.access_token}"
        headers["chatgpt-account-id"] = sign_in.account_id
        body = _json_object(raw)
        if body is None or body.get("stream") is True:
            return await self._inner.handle_async_request(_rebuilt(request, headers, raw))
        body["stream"] = True
        body["store"] = False
        headers["accept"] = "text/event-stream"
        response = await self._inner.handle_async_request(
            _rebuilt(request, headers, json.dumps(body).encode())
        )
        await response.aread()
        if response.status_code != 200:
            return response
        completed = _completed_response(response.content)
        if completed is None:
            return _error_response(
                502, "the backend's stream ended without response.completed", "incomplete_stream"
            )
        return httpx2.Response(200, json=completed)

    async def aclose(self) -> None:
        await self._inner.aclose()


def _rebuilt(request: httpx2.Request, headers: httpx2.Headers, content: bytes) -> httpx2.Request:
    """`request` with `headers` and `content`; the length is recomputed for the new body."""
    for name in ("content-length", "transfer-encoding"):
        headers.pop(name, None)
    return httpx2.Request(
        request.method,
        request.url,
        headers=headers,
        content=content,
        extensions=request.extensions,
    )


def _json_object(raw: bytes) -> dict[str, Any] | None:
    """The body as a JSON object, or `None` when it is not one."""
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _completed_response(stream: bytes) -> dict[str, Any] | None:
    """The `response` of the stream's `response.completed` event, or `None` without one."""
    completed = None
    try:
        for event in SSEDecoder().iter_bytes(iter([stream])):
            try:
                data = event.json()
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("type") == "response.completed":
                completed = data.get("response")
    except UnicodeDecodeError:
        return None
    return completed if isinstance(completed, dict) else None


def _error_response(status: int, message: str, code: str) -> httpx2.Response:
    """A JSON error in the shape the SDK maps to its typed status errors."""
    return httpx2.Response(
        status,
        json={"error": {"message": message, "type": "invalid_request_error", "code": code}},
    )


def _instant(value: object) -> datetime | None:
    """An RFC 3339 timestamp as an aware UTC datetime; `None` when absent or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _jwt_payload(token: str) -> dict[str, Any]:
    """The claims of a JWT, decoded without verification; `{}` when they cannot be read."""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    encoded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
