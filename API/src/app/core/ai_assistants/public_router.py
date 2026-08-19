"""Public-widget router for AI Assistants
(``tasks/ai-assistants`` Step 14).

Mounted at ``/api/v1/public/ai-assistants/*``. Every handler takes
:class:`~core.ai_assistants.public_context.PublicContext` — the
sole authority for ``(org_id, assistant_id, embed_key_id)``. Body
fields for any of those are IGNORED (Attacker isolation defence:
body cannot elevate scope beyond the bearer key).

**Never** imports the operator JWT auth machinery. The pin-test
:file:`API/tests/test_public_router_no_jwt.py` walks this file via
``ast`` and fails CI if any symbol from ``core.auth.dependencies``
sneaks in.

Three endpoints:

  * ``POST /session/init`` — issue a session token + tell the widget
    whether Turnstile is required (yes on first message; no on
    subsequent).
  * ``POST /message`` — SSE stream of the assistant's reply.
  * ``GET /assistant`` — public-safe metadata for widget bootstrap
    (never returns ``instructions`` / ``key_id`` / audit).
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import data_access as _da
from src.app.core.ai_assistants.public_context import PublicContext, public_context
from src.app.core.ai_assistants.runtime import ChatRuntime, RuntimeChunk
from src.app.core.embed.rate_limit import check_ai_public_rate_limits
from src.app.shared.db import get_db
from src.app.shared.turnstile import verify_turnstile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/ai-assistants", tags=["public-ai-assistants"])


# In-process cache of session tokens that have already passed
# Turnstile verification. 5-min TTL keeps the memory footprint
# bounded even under sustained traffic; a session that idles longer
# than 5 min will re-challenge on the next message, which is fine
# for anti-abuse.
_SESSION_TTL_SECONDS = 5 * 60
_session_verified: dict[str, float] = {}


def _session_is_verified(session_token: str) -> bool:
    exp = _session_verified.get(session_token)
    if exp is None:
        return False
    if exp < time.time():
        _session_verified.pop(session_token, None)
        return False
    return True


def _mark_session_verified(session_token: str) -> None:
    _session_verified[session_token] = time.time() + _SESSION_TTL_SECONDS


# --- Session init --------------------------------------------------------


class _SessionInitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(..., min_length=8, max_length=120)
    requires_captcha: bool


@router.post("/session/init", response_model=_SessionInitResponse)
async def session_init(
    ctx: PublicContext = Depends(public_context),
) -> _SessionInitResponse:
    """Mint a fresh session token and tell the widget whether the
    first message will need a Turnstile token.

    Session tokens are process-local opaque strings — the widget
    passes them back on ``/message`` so we can group turns into one
    conversation on the backend + skip Turnstile verification on
    subsequent messages in the same session."""
    session_token = f"pub-{secrets.token_urlsafe(24)}"
    _ = ctx  # scope proof — the key was resolvable, this is a valid caller
    return _SessionInitResponse(
        session_token=session_token,
        requires_captcha=True,
    )


# --- Assistant metadata --------------------------------------------------


class _PublicAssistantMeta(BaseModel):
    """Trimmed shape the widget needs to render itself. Never
    includes ``instructions`` (prompt-injection surface) /
    ``key_id`` (provider-key leak) / audit rows."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    interface_config: dict
    styling_config: dict


@router.get("/assistant", response_model=_PublicAssistantMeta)
async def get_assistant_meta(
    ctx: PublicContext = Depends(public_context),
    db: AsyncSession = Depends(get_db),
) -> _PublicAssistantMeta:
    """Widget-bootstrap metadata. Reads via the tenant-agnostic
    ``get_assistant_by_id_no_org_filter`` because the public path
    has no JWT / TenantScoped context — the caller's org context
    lives on ``ctx.org_id`` and we cross-check it manually so a
    key can only ever surface its own org's assistant."""
    from sqlalchemy import text as _sql_text

    result = await db.execute(
        _sql_text(
            """
            SELECT id, org_id, name, interface_config, styling_config, status::text
            FROM tbl_ai_assistants
            WHERE id = :id
            LIMIT 1
            """
        ),
        {"id": str(ctx.assistant_id)},
    )
    row = result.first()
    if row is None or uuid.UUID(str(row.org_id)) != ctx.org_id:
        # Same 404 shape for wrong-org + nonexistent — no side channel.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "assistant_not_found"},
        )
    if row.status != "active":
        # Public path never accepts drafts / archived assistants.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "assistant_not_found"},
        )

    return _PublicAssistantMeta(
        id=uuid.UUID(str(row.id)),
        name=row.name,
        interface_config=row.interface_config or {},
        styling_config=row.styling_config or {},
    )


# --- Message stream ------------------------------------------------------


class _PublicMessageBody(BaseModel):
    """Body the widget sends on each turn. ``org_id`` / ``assistant_id``
    / ``embed_key_id`` are intentionally NOT accepted (Attacker
    isolation) — the context derives them from the bearer key.
    ``conversation_id`` is accepted but ignored in v1 (we always
    create a fresh conversation per session token; Step 16 wires
    persistence)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=8000)
    session_token: str = Field(..., min_length=8, max_length=120)
    captcha_token: str | None = Field(default=None, max_length=2000)


@router.post("/message")
async def send_message(
    payload: _PublicMessageBody,
    ctx: PublicContext = Depends(public_context),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream the assistant's reply. Rate-limits per-IP + per-key +
    per-org (fail-closed on Redis outage). First message per session
    requires a valid Turnstile token; subsequent messages within the
    5-min TTL skip the check."""
    # 1. Fail-closed rate-limit BEFORE any expensive work.
    rl = await check_ai_public_rate_limits(
        ip=ctx.caller_ip,
        key_id=ctx.embed_key_id,
        org_id=ctx.org_id,
        per_key_limit=ctx.per_key_rate_limit,
    )
    if not rl.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"reason": rl.reason},
            headers={"Retry-After": str(rl.retry_after_seconds)},
        )

    # 2. Turnstile on first message per session. Subsequent messages
    # in the same 5-min window skip verification.
    if not _session_is_verified(payload.session_token):
        ok = await verify_turnstile(
            payload.captcha_token, remote_ip=ctx.caller_ip
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"reason": "captcha_required"},
            )
        _mark_session_verified(payload.session_token)

    # 3. Run the streaming pipeline.
    runtime = ChatRuntime(
        db=db,
        org_id=ctx.org_id,
        assistant_id=ctx.assistant_id,
        user_message=payload.message,
        session_token=payload.session_token,
        is_public=True,
        embed_key_id=ctx.embed_key_id,
    )

    async def _sse_stream():
        try:
            async for chunk in runtime.stream_reply():
                yield f"data: {json.dumps(_chunk_to_json(chunk))}\n\n"
        except Exception:  # pragma: no cover — defensive
            logger.exception(
                "public_router.message stream_crash key=%s session=%s",
                ctx.embed_key_id,
                payload.session_token,
            )
            yield f"data: {json.dumps({'type': 'error', 'reason': 'internal_error'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _chunk_to_json(chunk: RuntimeChunk) -> dict:
    out: dict = {"type": chunk.type}
    if chunk.type == "token":
        out["delta"] = chunk.delta
    elif chunk.type == "error":
        out["reason"] = chunk.reason
    elif chunk.type == "done":
        out["total_tokens"] = chunk.total_tokens
        out["cost_usd"] = str(chunk.cost_usd) if chunk.cost_usd is not None else "0"
    return out


# Silence "unused DAL import" — retained so the pin-test's ast walker
# also flags dead JWT imports if a future refactor lands one here.
_ = _da


__all__ = ["router"]
