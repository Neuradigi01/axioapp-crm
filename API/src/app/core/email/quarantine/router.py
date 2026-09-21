"""HTTP endpoints for quarantine + filter-rules.

All Owner/Admin — gated by ``email.accounts.manage``, the same key
the rest of the email settings module uses. Non-Owner Employees get
403 at the dependency layer.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.quarantine import service
from src.app.core.email.quarantine.schemas import (
    BulkReleaseIn,
    BulkReleaseResult,
    FilterRuleIn,
    FilterRuleOut,
    QuarantineListOut,
    QuarantineOut,
    ReasonCode,
    QuarantineStatus,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(tags=["Email Quarantine"])


# ---------------------------------------------------------------------------
# Filter rules
# ---------------------------------------------------------------------------


@router.get(
    "/email-filter-rules",
    response_model=list[FilterRuleOut],
)
async def list_filter_rules_endpoint(
    endpoint_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> list[FilterRuleOut]:
    return await service.list_filter_rules(
        db, org_id=user.org_id, endpoint_id=endpoint_id
    )


@router.post(
    "/email-filter-rules",
    response_model=FilterRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_filter_rule_endpoint(
    payload: FilterRuleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> FilterRuleOut:
    try:
        return await service.create_filter_rule(
            db, org_id=user.org_id, actor_user_id=user.id, payload=payload
        )
    except service.FilterRuleCapExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except service.FilterRuleDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/email-filter-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_filter_rule_endpoint(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    await service.delete_filter_rule(
        db, org_id=user.org_id, actor_user_id=user.id, id=rule_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


@router.get(
    "/email-quarantine",
    response_model=QuarantineListOut,
)
async def list_quarantine_endpoint(
    status_filter: QuarantineStatus | None = Query(default=None, alias="status"),
    reason_code: ReasonCode | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> QuarantineListOut:
    items, total = await service.list_quarantine(
        db,
        org_id=user.org_id,
        status=status_filter,
        reason_code=reason_code,
        limit=limit,
        offset=offset,
    )
    return QuarantineListOut(items=items, total=total)


@router.post(
    "/email-quarantine/{quarantine_id}/release",
    response_model=QuarantineOut,
)
async def release_quarantine_endpoint(
    quarantine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> QuarantineOut:
    try:
        return await service.release(
            db,
            org_id=user.org_id,
            actor_user_id=user.id,
            id=quarantine_id,
        )
    except service.QuarantineReleaseBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


@router.post(
    "/email-quarantine/{quarantine_id}/discard",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def discard_quarantine_endpoint(
    quarantine_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> Response:
    await service.discard(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        id=quarantine_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/email-quarantine/bulk-release",
    response_model=BulkReleaseResult,
)
async def bulk_release_endpoint(
    payload: BulkReleaseIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.manage")),
) -> BulkReleaseResult:
    return await service.bulk_release(
        db,
        org_id=user.org_id,
        actor_user_id=user.id,
        ids=payload.ids,
    )
