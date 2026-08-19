"""HTTP routes for the AI Assistants module.

Mounted at ``/api/v1/ai-assistants`` by ``main.py``. Six endpoints:

  * ``GET  /``               list (paginated).
  * ``GET  /{id}``           read (timing-safe 404).
  * ``POST /``               create.
  * ``PATCH /{id}``          update (OCC via ``version``).
  * ``POST /{id}/archive``   archive (soft — status → ``archived``).
  * ``DELETE /{id}``         hard-delete (requires ``?confirm=true``).

RBAC: GETs need ``ai_assistants.view``; every mutation needs
``ai_assistants.manage``. Every handler resolves ``org_id`` from
the request context (populated by ``TenantContextMiddleware``);
no ``org_id`` in URL paths or request bodies.
"""

from __future__ import annotations

import uuid

import json

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import service as ai_service
from src.app.core.ai_assistants.models import AiAssistantStatus
from src.app.core.ai_assistants.permissions import PERM_MANAGE, PERM_VIEW
from src.app.core.ai_assistants.runtime import ChatRuntime, RuntimeChunk
from src.app.core.ai_assistants.schemas import (
    AiAssistantCreate,
    AiAssistantListItem,
    AiAssistantRead,
    AiAssistantUpdate,
)
from src.app.core.auth.dependencies import require_permissions
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db

router = APIRouter(prefix="/ai-assistants", tags=["ai-assistants"])


def _caller_org_id() -> uuid.UUID:
    ctx = get_context()
    if ctx.org_id is None:  # pragma: no cover — require_permissions ensures this
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no organisation in request context",
        )
    return ctx.org_id


def _user_id(user: User) -> uuid.UUID | None:
    """Extract the user's id. Kept as a helper so a future
    ``created_by`` cross-reference (e.g. staff-portal PIN user vs
    admin JWT user) can diverge here without touching every endpoint."""
    return getattr(user, "id", None)


# --- List ----------------------------------------------------------------


class _ListResponse(AiAssistantListItem):
    """The ``/`` endpoint returns a paginated envelope, not a bare
    list, so a future analytics badge / filter-count widget can grow
    without breaking the wire shape. Item shape is
    :class:`AiAssistantListItem`.
    """


@router.get("", response_model=dict)
async def list_assistants_endpoint(
    filter_status: AiAssistantStatus | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> dict:
    rows, total = await ai_service.list_assistants(
        db,
        filter_status=filter_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    items = [AiAssistantListItem.model_validate(r).model_dump(mode="json") for r in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# --- Read ----------------------------------------------------------------


@router.get("/{assistant_id}", response_model=AiAssistantRead)
async def get_assistant_endpoint(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> AiAssistantRead:
    row = await ai_service.get_assistant(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
    )
    return AiAssistantRead.model_validate(row)


# --- Create --------------------------------------------------------------


@router.post(
    "",
    response_model=AiAssistantRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assistant_endpoint(
    payload: AiAssistantCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_MANAGE)),
) -> AiAssistantRead:
    row = await ai_service.create_assistant(
        db,
        org_id=_caller_org_id(),
        user_id=_user_id(user),
        payload=payload,
    )
    return AiAssistantRead.model_validate(row)


# --- Update --------------------------------------------------------------


@router.patch("/{assistant_id}", response_model=AiAssistantRead)
async def update_assistant_endpoint(
    assistant_id: uuid.UUID,
    payload: AiAssistantUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_MANAGE)),
) -> AiAssistantRead:
    row = await ai_service.update_assistant(
        db,
        org_id=_caller_org_id(),
        user_id=_user_id(user),
        assistant_id=assistant_id,
        payload=payload,
    )
    return AiAssistantRead.model_validate(row)


# --- Archive -------------------------------------------------------------


@router.post(
    "/{assistant_id}/archive",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def archive_assistant_endpoint(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> Response:
    await ai_service.archive_assistant(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Delete --------------------------------------------------------------


@router.delete(
    "/{assistant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_assistant_endpoint(
    assistant_id: uuid.UUID,
    confirm: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> Response:
    if not confirm:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "reason": "confirmation_required",
                "message": "Pass ?confirm=true to hard-delete this assistant.",
            },
        )
    await ai_service.delete_assistant(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Preview (Step 9) ----------------------------------------------------


class _PreviewBody(BaseModel):
    """Operator-preview request. ``session_token`` groups a set of
    messages into one preview conversation on the server; the
    editor pane generates + persists it in the browser."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., min_length=1, max_length=8000)
    session_token: str = Field(..., min_length=1, max_length=120)


@router.post("/{assistant_id}/preview")
async def preview_endpoint(
    assistant_id: uuid.UUID,
    payload: _PreviewBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> StreamingResponse:
    """Stream the assistant's reply to the operator's preview pane.

    JWT-guarded on ``ai_assistants.view`` — the preview surface is
    read-only for Employees but still lets them try out the assistant.
    Streams SSE with per-line ``data: {json}`` events; the frontend
    ``preview-stream.service.ts`` parses them via ``fetch()`` +
    ``ReadableStream`` (not ``EventSource`` — keeps the JWT in the
    ``Authorization`` header rather than the URL query string).

    Client disconnects: FastAPI's ``request.is_disconnected()`` is
    polled by the runtime every N chunks; on true, the OpenAI
    stream is cancelled server-side so an abandoned tab stops
    billing (Attacker C5 defence).
    """
    org_id = _caller_org_id()
    runtime = ChatRuntime(
        db=db,
        org_id=org_id,
        assistant_id=assistant_id,
        user_message=payload.message,
        session_token=payload.session_token,
        is_public=False,
        is_disconnected=_wrap_is_disconnected(request),
    )

    async def _sse_stream():
        async for chunk in runtime.stream_reply():
            payload_dict = _chunk_to_json(chunk)
            yield f"data: {json.dumps(payload_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _sse_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _wrap_is_disconnected(request: Request):
    """Bridge FastAPI's async ``request.is_disconnected()`` to a
    sync-callable interface the runtime expects. Polls the last
    known state — the disconnect signal comes from the ASGI
    layer's own polling."""
    import asyncio

    _state = {"closed": False}

    async def _poll():
        while not _state["closed"]:
            if await request.is_disconnected():
                _state["closed"] = True
                return
            await asyncio.sleep(0.5)

    # Kick off the background poller; it flips the state on
    # disconnect. The runtime reads state via the sync callable.
    asyncio.get_event_loop().create_task(_poll())
    return lambda: _state["closed"]


def _chunk_to_json(chunk: RuntimeChunk) -> dict:
    """Convert a :class:`RuntimeChunk` into a JSON-serialisable
    dict for the SSE wire. ``Decimal`` costs become strings so
    JSON round-trips without float precision loss."""
    out: dict = {"type": chunk.type}
    if chunk.type == "token":
        out["delta"] = chunk.delta
    elif chunk.type == "error":
        out["reason"] = chunk.reason
    elif chunk.type == "done":
        out["total_tokens"] = chunk.total_tokens
        out["cost_usd"] = str(chunk.cost_usd) if chunk.cost_usd is not None else "0"
    return out


__all__ = ["router"]
