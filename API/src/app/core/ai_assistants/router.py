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

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.ai_assistants import service as ai_service
from src.app.core.ai_assistants.models import AiAssistantStatus
from src.app.core.ai_assistants.permissions import PERM_MANAGE, PERM_VIEW
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


__all__ = ["router"]
