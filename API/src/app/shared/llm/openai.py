"""OpenAI adapter — the ONLY file in ``src/app/`` allowed to import
the ``openai`` SDK.

The boundary is enforced by
``tests/test_llm_adapter_boundary.py`` which walks every ``.py`` under
``src/app/`` via ``ast`` and fails CI if it finds ``import openai`` /
``from openai`` anywhere else. This keeps provider-specific code
contained — future adapters (Anthropic, Google, OpenRouter) will
each own a single file under ``shared/llm/`` with the same isolation.

SSRF defence (Attacker review C1): the client is constructed with
``base_url`` hardcoded inside this file — the wrapper's constructor
does NOT accept ``base_url``, ``organization``, ``custom_headers``,
or any other host-adjacent field. An operator adding a "test URL"
that points at ``http://169.254.169.254/latest/meta-data/…`` cannot
reroute traffic — the AddKey schema rejects those fields at 422
(Step 1) and this adapter never reads them.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import openai
from openai import AsyncOpenAI

from src.app.shared.llm.base import (
    LLMChunk,
    LLMResponse,
    Messages,
    ProbeResult,
    Usage,
)
from src.app.shared.llm.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderServerError,
    ProviderTimeout,
)

# Hardcoded — no override path. Do not accept from any caller.
_OPENAI_BASE_URL: str = "https://api.openai.com/v1"
_OPENAI_TIMEOUT_SECONDS: float = 30.0
_OPENAI_MAX_EMBED_BATCH: int = 100
_PROVIDER: str = "openai"


def _map_exception(exc: BaseException) -> ProviderError:
    """Translate an OpenAI SDK exception → our typed provider error.

    Order matters — subclass checks must come before their parents.
    ``APIError`` is the SDK's broad base; we route it to
    :class:`ProviderServerError` after all specific classes have been
    tried.
    """
    request_id = getattr(exc, "request_id", None)
    status_code = getattr(exc, "status_code", None)
    message = str(exc)

    if isinstance(exc, openai.AuthenticationError):
        return ProviderAuthError(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    if isinstance(exc, openai.RateLimitError):
        return ProviderQuotaExceeded(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeout(
            message,
            provider=_PROVIDER,
            status_code=None,
            request_id=request_id,
        )
    if isinstance(exc, openai.BadRequestError):
        return ProviderBadRequest(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    # 5xx first — InternalServerError inherits from APIStatusError,
    # so this MUST be checked before the APIStatusError catch-all
    # below or every 500 would be mis-mapped to ProviderBadRequest.
    if isinstance(exc, openai.InternalServerError):
        return ProviderServerError(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    # NotFoundError / ConflictError / UnprocessableEntityError /
    # PermissionDeniedError all inherit from APIStatusError; treat
    # as bad-request (non-retryable — client mis-configuration).
    if isinstance(exc, openai.APIStatusError):
        return ProviderBadRequest(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    # APIConnectionError inherits from APIError but is transient —
    # bump to ProviderServerError (retryable in the caller).
    if isinstance(exc, (openai.APIConnectionError, openai.APIError, openai.OpenAIError)):
        return ProviderServerError(
            message,
            provider=_PROVIDER,
            status_code=status_code,
            request_id=request_id,
        )
    return ProviderServerError(
        message,
        provider=_PROVIDER,
        status_code=status_code,
        request_id=request_id,
    )


def _usage_from_openai(raw: object | None) -> Usage:
    """Extract usage from OpenAI's response.usage object. Handles the
    common case where fields might be None (defensive — the SDK
    guarantees them on chat.completions but not on every endpoint)."""
    if raw is None:
        return Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return Usage(
        prompt_tokens=int(getattr(raw, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(raw, "completion_tokens", 0) or 0),
        total_tokens=int(getattr(raw, "total_tokens", 0) or 0),
    )


class OpenAiClient:
    """LLM client bound to a stored OpenAI provider key.

    Constructor takes only what's needed to resolve the key — no
    ``base_url`` / ``organization`` / ``custom_headers`` fields
    (SSRF defence).
    """

    def __init__(self, *, db, org_id: uuid.UUID, key_id: uuid.UUID) -> None:  # noqa: ANN001
        self._db = db
        self._org_id = org_id
        self._key_id = key_id
        self._api_key: str | None = None
        self._client: AsyncOpenAI | None = None

    async def _get_client(self) -> AsyncOpenAI:
        """Lazily decrypt the key + build the client. Memoised per
        instance — one adapter = one client = one HTTP connection
        pool for the lifetime of the caller (typically one request)."""
        if self._client is not None:
            return self._client
        # Local import to avoid a module-load-time cycle:
        # openai.py → integrations.ai.service → this file (via factory).
        from src.app.core.integrations.ai import service as ai_service

        self._api_key = await ai_service.get_decrypted_key(
            self._db,
            org_id=self._org_id,
            key_id=self._key_id,
        )
        self._client = AsyncOpenAI(
            api_key=self._api_key,
            base_url=_OPENAI_BASE_URL,
            timeout=_OPENAI_TIMEOUT_SECONDS,
        )
        return self._client

    async def complete(
        self,
        messages: Messages,
        *,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        client = await self._get_client()
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
        except Exception as exc:  # noqa: BLE001 — mapping bounds it
            raise _map_exception(exc) from exc

        choice = response.choices[0] if response.choices else None
        content = ""
        finish_reason: str | None = None
        if choice is not None:
            content = (choice.message.content or "") if choice.message else ""
            finish_reason = choice.finish_reason
        return LLMResponse(
            content=content,
            usage=_usage_from_openai(response.usage),
            model=response.model,
            finish_reason=finish_reason,
        )

    async def stream(
        self,
        messages: Messages,
        *,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> AsyncIterator[LLMChunk]:
        client = await self._get_client()
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=list(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as exc:  # noqa: BLE001
            raise _map_exception(exc) from exc

        try:
            async for raw_chunk in stream:
                delta = ""
                finish_reason: str | None = None
                usage: Usage | None = None
                if raw_chunk.choices:
                    ch = raw_chunk.choices[0]
                    delta = (ch.delta.content or "") if ch.delta else ""
                    finish_reason = ch.finish_reason
                # OpenAI attaches usage only on the terminal chunk
                # when include_usage=True is set.
                if getattr(raw_chunk, "usage", None) is not None:
                    usage = _usage_from_openai(raw_chunk.usage)
                yield LLMChunk(delta=delta, usage=usage, finish_reason=finish_reason)
        except Exception as exc:  # noqa: BLE001
            raise _map_exception(exc) from exc

    async def probe(self) -> ProbeResult:
        """Cheap connectivity check — ``models.list`` is free (no
        tokens billed). Falls back to a 1-token completion if the
        key lacks ``models.list`` scope."""
        client = await self._get_client()
        try:
            iterator = await client.models.list()
            # AsyncPage; iterate the first entry to confirm auth actually
            # worked (a rejected auth raises here, not during list()).
            async for _ in iterator:
                return ProbeResult(ok=True, provider=_PROVIDER)
            # Empty page still means auth worked (unusual but possible).
            return ProbeResult(ok=True, provider=_PROVIDER)
        except openai.AuthenticationError as exc:
            return ProbeResult(
                ok=False,
                provider=_PROVIDER,
                detail=f"auth: {exc}",
            )
        except openai.PermissionDeniedError:
            # Key exists + is authenticated but lacks models.list scope.
            # Fall back to a 1-token completion for the definitive check.
            try:
                await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=1,
                    stream=False,
                )
            except Exception as exc:  # noqa: BLE001
                mapped = _map_exception(exc)
                return ProbeResult(
                    ok=False,
                    provider=_PROVIDER,
                    detail=str(mapped),
                )
            return ProbeResult(ok=True, provider=_PROVIDER)
        except Exception as exc:  # noqa: BLE001
            mapped = _map_exception(exc)
            return ProbeResult(
                ok=False,
                provider=_PROVIDER,
                detail=str(mapped),
            )

    async def embed(
        self,
        texts: list[str],
        *,
        model: str = "text-embedding-3-small",
    ) -> list[list[float]]:
        client = await self._get_client()
        results: list[list[float]] = []
        for start in range(0, len(texts), _OPENAI_MAX_EMBED_BATCH):
            batch = texts[start : start + _OPENAI_MAX_EMBED_BATCH]
            try:
                response = await client.embeddings.create(model=model, input=batch)
            except Exception as exc:  # noqa: BLE001
                raise _map_exception(exc) from exc
            results.extend([list(item.embedding) for item in response.data])
        return results


__all__ = ["OpenAiClient"]
