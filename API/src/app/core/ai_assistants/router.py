"""HTTP routes for the AI Assistants module.

Mounted at ``/api/v1/ai-assistants`` by ``main.py``. Seven endpoints:

  * ``GET  /``               list (paginated).
  * ``GET  /{id}``           read (timing-safe 404).
  * ``POST /``               create.
  * ``PATCH /{id}``          update (OCC via ``version``).
  * ``POST /{id}/activate``  publish (status → ``active`` — required
    for the public embed widget to serve requests).
  * ``POST /{id}/archive``   archive (soft — status → ``archived``).
  * ``DELETE /{id}``         hard-delete (requires ``?confirm=true``).

RBAC: GETs need ``ai_assistants.view``; every mutation needs
``ai_assistants.manage``. Every handler resolves ``org_id`` from
the request context (populated by ``TenantContextMiddleware``);
no ``org_id`` in URL paths or request bodies.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import service as ai_service
from src.app.core.ai_assistants.models import AiAssistantStatus
from src.app.core.ai_assistants.permissions import PERM_MANAGE, PERM_VIEW
from src.app.core.ai_assistants.runtime import ChatRuntime, RuntimeChunk
from src.app.core.ai_assistants.schemas import (
    AiAssistantAnalytics,
    AiAssistantCreate,
    AiAssistantListItem,
    AiAssistantRead,
    AiAssistantUpdate,
    KnowledgeCreateResponse,
    KnowledgeCreateText,
    KnowledgeCreateUrl,
    KnowledgeRead,
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
    """Extract the user's UUID identity. ``tbl_user_login`` has an
    integer PK (legacy auth heritage) plus a ``legacy_uuid`` UUID
    column; audit trails across the CRM key off the UUID (matches
    ``leads``, ``activities``, ``appointments``, ``dashboard``)."""
    return getattr(user, "legacy_uuid", None)


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


# --- Activate (publish) --------------------------------------------------


@router.post(
    "/{assistant_id}/activate",
    response_model=AiAssistantRead,
)
async def activate_assistant_endpoint(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> AiAssistantRead:
    row = await ai_service.activate_assistant(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
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


# --- Knowledge (Step 10) --------------------------------------------------
#
# Five new endpoints — every knowledge mutation needs
# ``ai_assistants.manage`` (uploading knowledge changes the model's
# behaviour); the list read needs ``ai_assistants.view``.
#
# ``multipart/form-data`` is used for the file upload endpoint; JSON
# for text + url. Reason: browsers can't set custom headers on a
# form-encoded upload, and file bytes shouldn't sit in JSON as
# base64 (2× overhead + memory pressure).

# Cap the multipart upload at the same 90 MB the validation layer
# enforces. Router doesn't trust it — validate_upload() re-checks —
# but a client that submits a 500 MB body eats an entire request
# worker before we can reject it, so surface the cap here first.
_MAX_UPLOAD_BYTES = 90 * 1024 * 1024


@router.post(
    "/{assistant_id}/knowledge/file",
    response_model=KnowledgeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_from_file_endpoint(
    assistant_id: uuid.UUID,
    file: UploadFile = File(..., description="PDF or UTF-8 text, ≤ 90 MB"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> KnowledgeCreateResponse:
    """Upload a file as a knowledge source. Router does no magic-byte
    check itself — the service delegates to
    :func:`~core.ai_assistants.file_upload.validate_upload` which
    sniffs, size-checks, name-checks, and hashes in one pass."""
    data = await file.read()
    # Fast reject before we chase deeper checks — validate_upload
    # will also enforce this, but stopping here saves an allocation
    # on obviously-oversize uploads.
    if len(data) > _MAX_UPLOAD_BYTES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"reason": "file_too_large"},
        )
    row, duplicate = await ai_service.create_knowledge_from_file(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        filename=file.filename or "upload.bin",
        data=data,
    )
    return KnowledgeCreateResponse(
        duplicate=duplicate,
        knowledge=KnowledgeRead.model_validate(row),
    )


@router.post(
    "/{assistant_id}/knowledge/text",
    response_model=KnowledgeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_from_text_endpoint(
    assistant_id: uuid.UUID,
    payload: KnowledgeCreateText,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> KnowledgeCreateResponse:
    row, duplicate = await ai_service.create_knowledge_from_text(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        payload=payload,
    )
    return KnowledgeCreateResponse(
        duplicate=duplicate,
        knowledge=KnowledgeRead.model_validate(row),
    )


@router.post(
    "/{assistant_id}/knowledge/url",
    response_model=KnowledgeCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_from_url_endpoint(
    assistant_id: uuid.UUID,
    payload: KnowledgeCreateUrl,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> KnowledgeCreateResponse:
    """URL scheme + IP-literal + DNS-resolves-public are checked
    up-front so a private-range URL 422s BEFORE the row is inserted.
    Per-hop redirect validation happens again inside the ingest
    task's fetch (belt+braces)."""
    row, duplicate = await ai_service.create_knowledge_from_url(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        payload=payload,
    )
    return KnowledgeCreateResponse(
        duplicate=duplicate,
        knowledge=KnowledgeRead.model_validate(row),
    )


@router.get(
    "/{assistant_id}/knowledge",
    response_model=list[KnowledgeRead],
)
async def list_knowledge_endpoint(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> list[KnowledgeRead]:
    rows = await ai_service.list_knowledge(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
    )
    return [KnowledgeRead.model_validate(r) for r in rows]


@router.post(
    "/{assistant_id}/knowledge/{knowledge_id}/cancel",
    response_model=KnowledgeRead,
)
async def cancel_knowledge_endpoint(
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> KnowledgeRead:
    row = await ai_service.cancel_knowledge(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
    )
    return KnowledgeRead.model_validate(row)


@router.delete(
    "/{assistant_id}/knowledge/{knowledge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_knowledge_endpoint(
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> Response:
    await ai_service.delete_knowledge(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{assistant_id}/knowledge/{knowledge_id}/replace",
    response_model=KnowledgeCreateResponse,
)
async def replace_knowledge_endpoint(
    assistant_id: uuid.UUID,
    knowledge_id: uuid.UUID,
    file: UploadFile = File(..., description="Replacement file, ≤ 90 MB"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> KnowledgeCreateResponse:
    """Ingest a new upload + retire the old row atomically. v1 chunks
    remain retrievable throughout — a mid-replace ``preview`` call
    still gets the pre-replace answers so the operator never sees a
    "no context" gap."""
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"reason": "file_too_large"},
        )
    row, duplicate = await ai_service.replace_knowledge_from_file(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        knowledge_id=knowledge_id,
        filename=file.filename or "upload.bin",
        data=data,
    )
    return KnowledgeCreateResponse(
        duplicate=duplicate,
        knowledge=KnowledgeRead.model_validate(row),
    )


# --- Profile picture (Step 13) ------------------------------------------

# 2 MB matches the ``file_upload._MAX_IMAGE_BYTES`` cap.
_MAX_PROFILE_PICTURE_BYTES = 2 * 1024 * 1024


class _ProfilePictureResponse(BaseModel):
    """Wraps the served URL so the frontend can render the new image
    without a re-fetch of the assistant row."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, max_length=2000)


@router.post(
    "/{assistant_id}/profile-picture",
    response_model=_ProfilePictureResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_profile_picture_endpoint(
    assistant_id: uuid.UUID,
    file: UploadFile = File(..., description="PNG / JPEG / WebP, < 2 MB"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> _ProfilePictureResponse:
    """Upload the header profile picture. Rejects SVG explicitly
    (SVG can carry ``<script>`` payloads that a browser would execute
    if the image is opened directly). Persists the served URL onto
    ``styling_config.header_profile_picture_url`` via ``jsonb_set``."""
    data = await file.read()
    if len(data) > _MAX_PROFILE_PICTURE_BYTES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"reason": "image_too_large"},
        )
    result = await ai_service.upload_profile_picture(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        filename=file.filename or "avatar.png",
        data=data,
    )
    return _ProfilePictureResponse(url=result["url"])


@router.delete(
    "/{assistant_id}/profile-picture",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_profile_picture_endpoint(
    assistant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> Response:
    await ai_service.delete_profile_picture(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Analytics (Step 16) ------------------------------------------------


@router.get(
    "/{assistant_id}/analytics",
    response_model=AiAssistantAnalytics,
)
async def get_analytics_endpoint(
    assistant_id: uuid.UUID,
    window_days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_VIEW)),
) -> AiAssistantAnalytics:
    """Message count + total cost + top-20 questions for one
    assistant over ``window_days`` (default 30). Timing-safe 404
    on wrong-org / nonexistent ids via the shared ``get_assistant``
    pre-check."""
    payload = await ai_service.get_analytics(
        db,
        org_id=_caller_org_id(),
        assistant_id=assistant_id,
        window_days=window_days,
    )
    return AiAssistantAnalytics.model_validate(payload)


__all__ = ["router"]
