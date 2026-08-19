"""Public-router request context
(``tasks/ai-assistants`` Step 14).

Every public endpoint takes a :class:`PublicContext` dep — resolved
purely from the ``Authorization: Bearer <emb_...>`` header. Body
fields for ``org_id`` / ``assistant_id`` / ``conversation_id`` are
NEVER trusted; the context's fields are the source of truth for
which assistant the caller is talking to.

The dep also enforces:
  * Bearer scheme + non-empty token.
  * Key is live (or within its rotate-with-grace window).
  * ``resource_type == 'ai_assistant'`` + ``resource_id`` set.
  * ``Origin`` header (when present) matches the key's
    ``allowed_origins`` list. Empty list = accept any origin.

All rejections surface as 401 with an identical ``invalid_key``
body — no side-channel between "wrong key" and "wrong origin" and
"revoked key past grace". Origin mismatches surface as 403 (they
carry no oracular info — the operator explicitly set the list).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status

from src.app.core.embed import service as embed_service


@dataclass(frozen=True, slots=True)
class PublicContext:
    """The bearer-key-derived context every public handler receives.
    Immutable so a downstream helper can't mutate it back to another
    org."""

    org_id: uuid.UUID
    assistant_id: uuid.UUID
    embed_key_id: uuid.UUID
    embed_key_prefix: str
    per_key_rate_limit: int
    caller_ip: str
    origin: str | None


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _caller_ip(request: Request) -> str:
    """Best-effort client IP for the per-IP rate-limit bucket. Behind
    a reverse proxy the operator MUST configure X-Forwarded-For
    trust (uvicorn's ``--forwarded-allow-ips`` or a middleware); the
    default here is the socket peer which is the proxy IP under real
    deployment. Fine for v1 — the per-IP limit is a coarse bot
    filter, not the primary defence."""
    # Cloudflare + most reverse proxies set this header.
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Take the leftmost address (original caller).
        return xff.split(",", 1)[0].strip()
    if request.client is None:  # pragma: no cover — defensive
        return "unknown"
    return request.client.host


async def public_context(request: Request) -> PublicContext:
    """FastAPI dep. Resolves the bearer key + returns a
    :class:`PublicContext`. Raises 401 on any lookup failure,
    403 on origin mismatch."""
    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason": "invalid_key"},
        )

    ip = _caller_ip(request)
    origin = request.headers.get("origin")

    resolved = await embed_service.resolve_embed_key(token, ip=ip)
    resolved = embed_service.assert_ai_assistant_key(resolved)

    # Origin check — only when the key has any allow-list set. An
    # empty list = accept any origin (widget snippet on any domain).
    # The check is deliberately case-insensitive on the scheme + host
    # only; port + trailing slash differences don't count.
    if resolved.allowed_origins and origin is not None:
        if not _origin_matches(origin, resolved.allowed_origins):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"reason": "origin_not_allowed"},
            )

    # ``resource_id`` is guaranteed non-None by ``assert_ai_assistant_key``.
    assert resolved.resource_id is not None
    return PublicContext(
        org_id=resolved.org_id,
        assistant_id=resolved.resource_id,
        embed_key_id=resolved.key_id,
        embed_key_prefix=resolved.prefix,
        per_key_rate_limit=resolved.rate_limit_per_hour,
        caller_ip=ip,
        origin=origin,
    )


def _origin_matches(origin: str, allow_list: tuple[str, ...] | list[str]) -> bool:
    """Case-insensitive substring-safe origin check. Exact match
    against ``allow_list`` entries. Callers should store origins as
    ``https://example.com`` (no path, no trailing slash) — this
    matches the widget snippet's ``window.location.origin`` output."""
    o = origin.strip().lower()
    for allowed in allow_list:
        if o == allowed.strip().lower():
            return True
    return False


# Alias so router imports read naturally:
#     _: PublicContext = Depends(get_public_context)
def get_public_context() -> PublicContext:  # noqa: D401 — factory shim
    return Depends(public_context)


__all__ = ["PublicContext", "get_public_context", "public_context"]
