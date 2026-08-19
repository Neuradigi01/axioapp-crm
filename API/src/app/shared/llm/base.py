"""``LLMClient`` protocol + response dataclasses.

Callers program to :class:`LLMClient` — the four methods
(``complete`` / ``stream`` / ``probe`` / ``embed``) are the
provider-agnostic surface. Every adapter implements this shape.

Response dataclasses are frozen + slots-friendly so accidental
mutation from a caller (e.g. patching in a fake ``usage``) is
impossible. Cost math (:mod:`shared.llm.pricing`) works off these
values, never off numbers the widget reports (Attacker M7).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Usage:
    """Token counts returned by the upstream provider.

    All three fields are extracted server-side from the LLM's own
    response — never from anything a widget or caller reports. This
    is the input to :func:`shared.llm.pricing.cost_for`.
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Full non-streaming completion."""

    content: str
    usage: Usage
    model: str
    finish_reason: str | None


@dataclass(frozen=True, slots=True)
class LLMChunk:
    """One step of a streaming completion.

    ``delta`` is the incremental text this chunk carries (may be
    empty for the first / last chunks). ``usage`` populates only on
    the terminal chunk when the upstream includes usage in the
    stream (OpenAI does when ``stream_options={"include_usage": True}``
    is set; the adapter always sets it). ``finish_reason`` populates
    on the terminal chunk (``'stop'`` / ``'length'`` / ``'content_filter'``).
    """

    delta: str
    usage: Usage | None
    finish_reason: str | None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a cheap connectivity check against the provider.
    Used by the operator-facing "Test" button (Step 1's
    ``test_provider_key`` service).
    """

    ok: bool
    provider: str
    detail: str | None = None


# Type aliases for the message shape — kept loose (``dict[str, Any]``)
# because the OpenAI SDK accepts many optional fields (name,
# tool_calls, function_call, refusal) that our v1 caller doesn't
# populate. Adapters pass the messages through unchanged.
Message = dict[str, Any]
Messages = Iterable[Message]


class LLMClient(Protocol):
    """The four methods every LLM adapter must implement.

    Note ``__init__`` intentionally NOT in the protocol — each
    adapter binds its own key resolution (Db session + key id).
    Callers get an ``LLMClient`` back from
    :func:`shared.llm.factory` and use these methods.
    """

    async def complete(
        self,
        messages: Messages,
        *,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """One-shot completion — waits for the full reply."""

    def stream(
        self,
        messages: Messages,
        *,
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 1024,
    ) -> AsyncIterator[LLMChunk]:
        """Streaming completion — yields chunks as they arrive from
        the provider. Callers use ``async for chunk in client.stream(...)``.

        Adapters MUST cancel the upstream stream when the async
        iterator is closed (``aclose()`` on the underlying HTTP body)
        so a client disconnect stops billing. Step 9's chat runtime
        drives this via ``request.is_disconnected()`` polling.
        """

    async def probe(self) -> ProbeResult:
        """Cheap connectivity check. Adapters implement this in the
        cheapest way that verifies auth (OpenAI: ``models.list()``).
        Never spends more than a few tokens."""

    async def embed(
        self,
        texts: list[str],
        *,
        model: str = "text-embedding-3-small",
    ) -> list[list[float]]:
        """Return one vector per input text. Adapters batch as
        needed to stay within provider limits (OpenAI: 100 per call)."""


__all__ = [
    "LLMChunk",
    "LLMClient",
    "LLMResponse",
    "Message",
    "Messages",
    "ProbeResult",
    "Usage",
]
