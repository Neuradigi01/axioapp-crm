"""HTTP routes for the BYOK provider-key store.

Mounted at ``/api/v1/integrations/ai`` by ``main.py``. Every endpoint
requires the ``ai_providers.manage`` permission (Owner + Admin only;
Employee never sees this surface). The router never runs SQL — every
read + write goes through :mod:`core.integrations.ai.service`.

Endpoints:

  * ``POST /providers``          create a new key
  * ``GET  /providers``          list (masked; excludes revoked)
  * ``POST /providers/{id}/test``  probe upstream (rate-limited)
  * ``POST /providers/reassign``   swap references K1 → K2
  * ``DELETE /providers/{id}``   hard-delete (blocked if referenced)
  * ``GET  /budget``             read org's daily/monthly caps + spent
  * ``PATCH /budget``            update caps
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.integrations.ai import service as ai_service
from src.app.core.integrations.ai.models import AiProvider
from src.app.core.integrations.ai.permissions import PERM_MANAGE
from src.app.core.integrations.ai.schemas import (
    AiProviderKeyCreate,
    AiProviderKeyReassign,
    AiProviderKeyRead,
    OrgAiCostBudgetRead,
    OrgAiCostBudgetUpdate,
)
from src.app.core.users.models import User
from src.app.shared.context import get_context
from src.app.shared.db import get_db

router = APIRouter(prefix="/integrations/ai", tags=["integrations-ai"])


def _caller_org_id() -> uuid.UUID:
    ctx = get_context()
    if ctx.org_id is None:  # pragma: no cover — require_permissions ensures this
        raise RuntimeError("org_id missing from request context")
    return ctx.org_id


# --- Provider keys -------------------------------------------------------


@router.post(
    "/providers",
    response_model=AiProviderKeyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_key(
    payload: AiProviderKeyCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> AiProviderKeyRead:
    row = await ai_service.create_provider_key(
        db,
        org_id=_caller_org_id(),
        payload=payload,
    )
    return AiProviderKeyRead.model_validate(row)


@router.get(
    "/providers",
    response_model=list[AiProviderKeyRead],
)
async def list_provider_keys(
    provider: AiProvider | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> list[AiProviderKeyRead]:
    rows = await ai_service.list_provider_keys(db, provider=provider)
    return [AiProviderKeyRead.model_validate(r) for r in rows]


@router.post(
    "/providers/{key_id}/test",
    response_model=AiProviderKeyRead,
)
async def test_provider_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_MANAGE)),
) -> AiProviderKeyRead:
    row = await ai_service.test_provider_key(
        db,
        org_id=_caller_org_id(),
        user_id=user.id,
        key_id=key_id,
    )
    return AiProviderKeyRead.model_validate(row)


@router.post(
    "/providers/reassign",
    status_code=status.HTTP_200_OK,
)
async def reassign_provider_key(
    payload: AiProviderKeyReassign,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> dict[str, int]:
    reassigned = await ai_service.reassign_provider_key(
        db,
        org_id=_caller_org_id(),
        payload=payload,
    )
    return {"reassigned_count": reassigned}


@router.delete(
    "/providers/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_provider_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> Response:
    await ai_service.delete_provider_key(
        db,
        org_id=_caller_org_id(),
        key_id=key_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Budget --------------------------------------------------------------


@router.get(
    "/budget",
    response_model=OrgAiCostBudgetRead,
)
async def read_budget(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> OrgAiCostBudgetRead:
    row = await ai_service.get_or_create_budget(db, org_id=_caller_org_id())
    return OrgAiCostBudgetRead.model_validate(row)


@router.patch(
    "/budget",
    response_model=OrgAiCostBudgetRead,
)
async def update_budget(
    payload: OrgAiCostBudgetUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions(PERM_MANAGE)),
) -> OrgAiCostBudgetRead:
    row = await ai_service.update_budget(
        db,
        org_id=_caller_org_id(),
        payload=payload,
    )
    return OrgAiCostBudgetRead.model_validate(row)


__all__ = ["router"]
