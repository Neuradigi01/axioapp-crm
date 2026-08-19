"""Provider-agnostic typed exceptions for the LLM client.

Every adapter (``openai.py`` today; ``anthropic.py`` / ``google.py``
tomorrow) MUST map upstream SDK exceptions to these classes so
callers can write handler code without importing the SDK.

Every exception carries three fields the runtime + observability
surfaces care about:

  * ``provider`` — string tag for the adapter (``'openai'``).
  * ``status_code`` — the HTTP status the upstream returned, when
    known. ``None`` for connection / timeout errors.
  * ``request_id`` — from the upstream response header when
    available (OpenAI: ``x-request-id``). Correlates with the
    provider's own logs during a support incident.

Callers should catch these specific classes, never plain
:class:`Exception` — the chat runtime translates each to a distinct
user-visible outcome (Step 9: ``budget_cap_hit`` vs
``provider_error`` vs the fallback message).
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for every adapter-surfaced exception."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.request_id = request_id


class ProviderAuthError(ProviderError):
    """The stored API key is invalid, revoked, or lacks the required
    scope. Chat runtime marks the assistant temporarily disabled and
    surfaces a "reconnect your key" prompt to the operator."""


class ProviderQuotaExceeded(ProviderError):
    """Upstream returned a 429 (rate limit hit OR org's OpenAI
    monthly quota exhausted). Chat runtime returns the fallback
    message and records the failure on the meta row."""


class ProviderTimeout(ProviderError):
    """Adapter's per-request timeout elapsed. Never a bill on the
    org's OpenAI account when raised before response bytes arrive.
    Chat runtime retries once for streaming, then surfaces the
    fallback."""


class ProviderBadRequest(ProviderError):
    """Malformed request — usually a model that no longer exists or
    a payload that violates the provider's constraints. Non-retryable;
    the operator has to change the assistant config."""


class ProviderServerError(ProviderError):
    """Upstream 5xx or unclassified :class:`openai.APIError`. Retryable
    once; surfaces the fallback after retry exhausts."""


__all__ = [
    "ProviderAuthError",
    "ProviderBadRequest",
    "ProviderError",
    "ProviderQuotaExceeded",
    "ProviderServerError",
    "ProviderTimeout",
]
