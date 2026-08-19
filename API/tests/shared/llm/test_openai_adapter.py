"""Behavioural tests for :mod:`src.app.shared.llm.openai`.

Uses ``respx`` to intercept OpenAI HTTP calls at the httpx layer —
no network access, no real API key required. Every test decrypts
via a monkeypatched ``get_decrypted_key`` so no DB session is
needed.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import uuid

import httpx
import pytest


def _install_test_kek() -> None:
    os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode()
    import config as app_config
    app_config.AI_PROVIDER_KEY_KEK = os.environ["AI_PROVIDER_KEY_KEK"]


_install_test_kek()


# All tests below rebind ``ai_service.get_decrypted_key`` to a fake
# so the adapter's ``_get_client`` succeeds without a DB session.
@pytest.fixture(autouse=True)
def _stub_decrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_decrypt(db, *, org_id, key_id):  # noqa: ANN001,ARG001
        return "sk-test-fake-key"

    from src.app.core.integrations.ai import service as ai_service

    monkeypatch.setattr(ai_service, "get_decrypted_key", _fake_decrypt)


def _new_client():
    from src.app.shared.llm.openai import OpenAiClient

    return OpenAiClient(db=None, org_id=uuid.uuid4(), key_id=uuid.uuid4())


# --- Pricing (pure) -------------------------------------------------------


def test_cost_for_gpt_4o_mini() -> None:
    from decimal import Decimal
    from src.app.shared.llm.base import Usage
    from src.app.shared.llm.pricing import cost_for

    usage = Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
    cost = cost_for(usage, "gpt-4o-mini")
    # 1000/1000 * 0.00015  +  500/1000 * 0.0006  =  0.00015 + 0.00030 = 0.00045
    assert cost == Decimal("0.00045")


def test_cost_for_embedding_ignores_completion_tokens() -> None:
    from decimal import Decimal
    from src.app.shared.llm.base import Usage
    from src.app.shared.llm.pricing import cost_for

    usage = Usage(prompt_tokens=10_000, completion_tokens=999_999, total_tokens=999_999)
    cost = cost_for(usage, "text-embedding-3-small")
    # 10000/1000 * 0.00002 = 0.00020  — completion is ignored.
    assert cost == Decimal("0.00020")


def test_cost_for_unknown_model_raises() -> None:
    from src.app.shared.llm.base import Usage
    from src.app.shared.llm.pricing import cost_for

    with pytest.raises(KeyError):
        cost_for(Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2), "gpt-9000")


def test_known_models_includes_expected() -> None:
    from src.app.shared.llm.pricing import known_models

    m = set(known_models())
    assert {"gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "text-embedding-3-small"} <= m


# --- Constructor SSRF defence --------------------------------------------


def test_adapter_constructor_rejects_base_url() -> None:
    from src.app.shared.llm.openai import OpenAiClient

    with pytest.raises(TypeError):
        OpenAiClient(  # type: ignore[call-arg]
            db=None,
            org_id=uuid.uuid4(),
            key_id=uuid.uuid4(),
            base_url="http://evil.example",
        )


def test_adapter_constructor_rejects_organization_and_headers() -> None:
    from src.app.shared.llm.openai import OpenAiClient

    for kw in ("organization", "custom_headers", "proxy"):
        with pytest.raises(TypeError):
            OpenAiClient(  # type: ignore[call-arg]
                db=None,
                org_id=uuid.uuid4(),
                key_id=uuid.uuid4(),
                **{kw: "junk"},
            )


# --- complete() -----------------------------------------------------------


async def test_complete_happy_path() -> None:
    import respx
    from src.app.shared.llm.base import LLMResponse

    body = {
        "id": "chatcmpl-abc",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello there!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
    }
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(200, json=body))
        client = _new_client()
        result = await client.complete(
            [{"role": "user", "content": "Hi"}],
            model="gpt-4o-mini",
        )

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello there!"
    assert result.usage.prompt_tokens == 11
    assert result.usage.completion_tokens == 3
    assert result.usage.total_tokens == 14
    assert result.model == "gpt-4o-mini"
    assert result.finish_reason == "stop"


async def test_complete_401_maps_to_provider_auth_error() -> None:
    import respx
    from src.app.shared.llm.errors import ProviderAuthError

    err_body = {"error": {"message": "Invalid key", "type": "invalid_request_error", "code": "invalid_api_key"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(401, json=err_body))
        client = _new_client()
        with pytest.raises(ProviderAuthError) as exc_info:
            await client.complete([{"role": "user", "content": "Hi"}], model="gpt-4o-mini")

    exc = exc_info.value
    assert exc.provider == "openai"
    assert exc.status_code == 401


async def test_complete_429_maps_to_provider_quota_exceeded() -> None:
    import respx
    from src.app.shared.llm.errors import ProviderQuotaExceeded

    err_body = {"error": {"message": "Rate limit reached", "type": "requests"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(429, json=err_body))
        client = _new_client()
        with pytest.raises(ProviderQuotaExceeded) as exc_info:
            await client.complete([{"role": "user", "content": "Hi"}], model="gpt-4o-mini")

    assert exc_info.value.status_code == 429


async def test_complete_500_maps_to_server_error() -> None:
    import respx
    from src.app.shared.llm.errors import ProviderServerError

    err_body = {"error": {"message": "Server had an oops", "type": "server_error"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(500, json=err_body))
        client = _new_client()
        with pytest.raises(ProviderServerError):
            await client.complete([{"role": "user", "content": "Hi"}], model="gpt-4o-mini")


async def test_complete_400_maps_to_bad_request() -> None:
    import respx
    from src.app.shared.llm.errors import ProviderBadRequest

    err_body = {"error": {"message": "Model not found", "type": "invalid_request_error"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(400, json=err_body))
        client = _new_client()
        with pytest.raises(ProviderBadRequest):
            await client.complete([{"role": "user", "content": "Hi"}], model="gpt-9000")


# --- stream() -------------------------------------------------------------


async def test_stream_yields_chunks_in_order() -> None:
    import respx

    lines = [
        b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"role":"assistant","content":"He"},"finish_reason":null}]}\n\n',
        b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"llo"},"finish_reason":null}]}\n\n',
        b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"},"finish_reason":"stop"}]}\n\n',
        b'data: {"id":"c1","object":"chat.completion.chunk","choices":[],"usage":{"prompt_tokens":5,"completion_tokens":3,"total_tokens":8}}\n\n',
        b"data: [DONE]\n\n",
    ]
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"".join(lines),
            )
        )
        client = _new_client()
        collected = [c async for c in client.stream(
            [{"role": "user", "content": "Hi"}], model="gpt-4o-mini"
        )]

    deltas = [c.delta for c in collected]
    assert "".join(deltas) == "Hello!"
    # Terminal-ish chunks carry finish_reason + usage.
    assert any(c.finish_reason == "stop" for c in collected)
    usage_chunks = [c for c in collected if c.usage is not None]
    assert len(usage_chunks) == 1
    assert usage_chunks[0].usage.total_tokens == 8


async def test_stream_401_raises_before_first_chunk() -> None:
    import respx
    from src.app.shared.llm.errors import ProviderAuthError

    err_body = {"error": {"message": "Invalid key"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/chat/completions").mock(return_value=httpx.Response(401, json=err_body))
        client = _new_client()
        with pytest.raises(ProviderAuthError):
            async for _ in client.stream(
                [{"role": "user", "content": "Hi"}], model="gpt-4o-mini"
            ):
                pass  # pragma: no cover — raise happens on the first .create()


# --- probe() --------------------------------------------------------------


async def test_probe_success_via_models_list() -> None:
    import respx

    body = {"object": "list", "data": [{"id": "gpt-4o-mini", "object": "model", "created": 1, "owned_by": "openai"}]}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.get("/models").mock(return_value=httpx.Response(200, json=body))
        client = _new_client()
        result = await client.probe()

    assert result.ok is True
    assert result.provider == "openai"


async def test_probe_returns_fail_on_401() -> None:
    import respx

    err_body = {"error": {"message": "Invalid key"}}
    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.get("/models").mock(return_value=httpx.Response(401, json=err_body))
        client = _new_client()
        result = await client.probe()

    assert result.ok is False
    assert result.provider == "openai"
    assert result.detail is not None
    assert "auth" in result.detail.lower()


# --- embed() --------------------------------------------------------------


async def test_embed_batches_250_into_three_calls() -> None:
    import respx

    call_counter = {"n": 0, "batch_sizes": []}

    def _handler(request: httpx.Request) -> httpx.Response:
        call_counter["n"] += 1
        payload = json.loads(request.content.decode())
        batch = payload["input"]
        call_counter["batch_sizes"].append(len(batch))
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [0.0, 0.1, 0.2]}
                    for i in range(len(batch))
                ],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": len(batch), "total_tokens": len(batch)},
            },
        )

    async with respx.mock(base_url="https://api.openai.com/v1") as router:
        router.post("/embeddings").mock(side_effect=_handler)
        client = _new_client()
        vectors = await client.embed([f"text {i}" for i in range(250)])

    assert call_counter["n"] == 3
    assert call_counter["batch_sizes"] == [100, 100, 50]
    assert len(vectors) == 250
    assert all(len(v) == 3 for v in vectors)


# --- base_url is truly hardcoded -----------------------------------------


def test_base_url_constant_is_openai() -> None:
    """Reads the module-level constant directly — any future edit
    that swaps it for a runtime lookup fails this test and forces
    the change to be explicit."""
    from src.app.shared.llm import openai as adapter

    assert adapter._OPENAI_BASE_URL == "https://api.openai.com/v1"
