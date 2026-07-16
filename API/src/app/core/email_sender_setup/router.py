"""HTTP endpoints for the sender-setup module.

Mounted at ``/api/v1/email-sender-setup``. Gated by the
``email.accounts.admin`` permission (Owner + Admin templates carry it —
seed via the RBAC roles migration; Rep templates do not so a regular
rep can't see or mutate the org's DNS-verification state).

Endpoints:

  * ``GET  /domains``                   — list all rows
  * ``POST /domains``                   — add a new pending row
  * ``GET  /domains/{id}/dns-records``  — copy-paste DNS records
  * ``POST /domains/{id}/verify``       — re-check SPF/DKIM/DMARC
  * ``DELETE /domains/{id}``            — remove (if no active campaign)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email_sender_setup import data_access, service
from src.app.core.email_sender_setup.schemas import (
    DnsRecordsResponse,
    DomainCreate,
    DomainRead,
    VerifyResponse,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/email-sender-setup", tags=["Email Sender Setup"])


@router.get("/domains", response_model=list[DomainRead])
async def list_domains_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.admin")),
) -> list[DomainRead]:
    rows = await data_access.list_domains(db, org_id=user.org_id)
    return [DomainRead.model_validate(r) for r in rows]


@router.post(
    "/domains",
    response_model=DomainRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_domain_endpoint(
    payload: DomainCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.admin")),
) -> DomainRead:
    row = await service.create_domain(db, org_id=user.org_id, domain=payload.domain)
    return DomainRead.model_validate(row)


@router.get("/domains/{domain_id}/dns-records", response_model=DnsRecordsResponse)
async def dns_records_endpoint(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.admin")),
) -> DnsRecordsResponse:
    row = await data_access.get_domain_by_id(db, org_id=user.org_id, domain_id=domain_id)
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Domain not found.")
    return DnsRecordsResponse(domain=row.domain, records=service.dns_records_for(row))


@router.post("/domains/{domain_id}/verify", response_model=VerifyResponse)
async def verify_domain_endpoint(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.admin")),
) -> VerifyResponse:
    row = await service.verify_domain(db, org_id=user.org_id, domain_id=domain_id)
    return VerifyResponse(
        id=row.id,
        domain=row.domain,
        spf_verified=row.spf_verified,
        dkim_verified=row.dkim_verified,
        dmarc_verified=row.dmarc_verified,
        fully_verified=row.fully_verified,
        # Any of the three timestamps is fine — verify() stamps them
        # all in the same tick.
        last_checked_at=row.spf_last_checked_at,
    )


@router.delete(
    "/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_domain_endpoint(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("email.accounts.admin")),
) -> Response:
    await service.delete_domain(db, org_id=user.org_id, domain_id=domain_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
