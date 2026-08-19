"""Provider-agnostic LLM client for the AI Assistants track.

Callers never import ``openai`` directly. They call :func:`factory`
with a provider name + a stored-key id, and get back an
:class:`~src.app.shared.llm.base.LLMClient` protocol object whose
methods (``complete`` / ``stream`` / ``probe`` / ``embed``) are the
same regardless of which upstream provider is behind them.

v1 ships a single adapter — OpenAI — with ``base_url`` hardcoded
inside the adapter file (SSRF defence, Attacker review C1). The
architecture supports Anthropic / Google / OpenRouter but those
adapters are deferred to a future track.

Boundary rule: **`openai` is ONLY imported inside
``shared/llm/openai.py``.** A CI pin-test
(``tests/test_llm_adapter_boundary.py``) walks every file under
``src/app/`` via ``ast`` and fails the build if any other file
imports it. This keeps provider-specific code contained.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.app.shared.llm.base import LLMClient, LLMChunk, LLMResponse, ProbeResult, Usage
from src.app.shared.llm.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderServerError,
    ProviderTimeout,
)


def factory(provider: str, *, db: AsyncSession, org_id: uuid.UUID, key_id: uuid.UUID) -> LLMClient:
    """Return an :class:`LLMClient` bound to a stored provider key.

    Only ``openai`` is supported in v1. Unknown providers raise
    :class:`ValueError` — callers should never hit this in practice
    because the ``ai_provider`` ENUM restricts stored keys to known
    values at DB-level.
    """
    if provider == "openai":
        # Local import to keep the ``openai`` symbol out of this
        # module's namespace — the boundary pin-test walks every
        # file under src/app/ except ``shared/llm/openai.py`` and
        # rejects any ``import openai`` it finds.
        from src.app.shared.llm.openai import OpenAiClient

        return OpenAiClient(db=db, org_id=org_id, key_id=key_id)
    raise ValueError(f"unknown LLM provider: {provider!r}")


__all__ = [
    "LLMChunk",
    "LLMClient",
    "LLMResponse",
    "ProbeResult",
    "ProviderAuthError",
    "ProviderBadRequest",
    "ProviderError",
    "ProviderQuotaExceeded",
    "ProviderServerError",
    "ProviderTimeout",
    "Usage",
    "factory",
]
