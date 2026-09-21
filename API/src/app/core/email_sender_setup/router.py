"""HTTP endpoints for the sender-setup module.

Two routers exported side by side:

  * :data:`router` — the legacy campaigns-only path mounted at
    ``/api/v1/email-sender-setup``. Gated by ``email.accounts.admin``.

  * :data:`sender_domains_router` — the Mailgun-managed sending-domain
    flow mounted at ``/api/v1/sender-domains``. Gated by the
    Owner-only ``email.sending_domains.manage`` permission (Owner
    template only — Admin does NOT carry it, so a workspace admin
    cannot claim / verify / release a sending domain).

Legacy endpoints:

  * ``GET  /domains``                   — list all rows
  * ``POST /domains``                   — add a new pending row
  * ``GET  /domains/{id}/dns-records``  — copy-paste DNS records
  * ``POST /domains/{id}/verify``       — re-check SPF/DKIM/DMARC
  * ``DELETE /domains/{id}``            — remove (if no active campaign)

Sending-domains endpoints:

  * ``POST   /``                        — claim a new domain
  * ``GET    /``                        — list org's domains
  * ``POST   /{id}/verify``             — trigger re-verify against Mailgun
  * ``DELETE /{id}``                    — release + Mailgun DELETE + cascade
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.email.mailgun.api_client_errors import (
    MailgunAuthError,
    MailgunNotFound,
    MailgunProviderError,
    MailgunRateLimited,
)
from src.app.core.email_sender_setup import data_access, service
from src.app.core.email_sender_setup.schemas import (
    ClaimDomainIn,
    DnsRecordsResponse,
    DomainCreate,
    DomainOut,
    DomainRead,
    VerifyResponse,
)
from src.app.core.email_sender_setup.service import DomainAlreadyClaimedError
from src.app.core.users.models import User
from src.app.shared.db import get_db

# Owner-only permission for the Mailgun-managed sending-domains flow.
# Not the same as ``email.accounts.admin`` (which the legacy campaigns
# domains + connect-mailbox flows use): claiming an org-wide sending
# domain is a workspace-ownership decision, so Admin does NOT carry it.
_SENDING_DOMAINS_PERM = "email.sending_domains.manage"


router = APIRouter(prefix="/email-sender-setup", tags=["Email Sender Setup"])

sender_domains_router = APIRouter(
    prefix="/sender-domains",
    tags=["Sending Domains"],
)


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


# ---------------------------------------------------------------------------
# tasks/email-sending-domains Step 4 — Sending-domains endpoints.
#
# Kept in this file (not a fresh router.py) so the module boundary
# stays one folder even though the two routers are mounted at different
# prefixes. Both share the same permission-registry startup sweep.
# ---------------------------------------------------------------------------


def _map_mailgun_error(exc: Exception) -> HTTPException:
    """Translate a Mailgun API-client exception into an HTTPException.

    Kept in the router (not the service) because HTTP status codes are
    an interface-layer concern — the service raises typed exceptions
    and the router owns the transport mapping. Layered pin-test allows
    ``HTTPException`` in router.py, forbids it in DAL.
    """
    if isinstance(exc, MailgunAuthError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Mailgun API credentials are misconfigured.",
        )
    if isinstance(exc, MailgunNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mailgun does not recognise this domain.",
        )
    if isinstance(exc, MailgunRateLimited):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Mailgun is rate-limiting requests. Retry shortly.",
        )
    if isinstance(exc, MailgunProviderError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Mailgun API is currently unavailable. Try again shortly.",
        )
    # Unknown Mailgun-side failure — surface as 502.
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Upstream email-domain provider error.",
    )


@sender_domains_router.post(
    "",
    response_model=DomainOut,
    status_code=status.HTTP_201_CREATED,
)
async def claim_sender_domain_endpoint(
    payload: ClaimDomainIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(_SENDING_DOMAINS_PERM)),
) -> DomainOut:
    """Claim ``payload.domain`` for the caller's org.

    Global uniqueness enforced service-side — collisions return 409
    without revealing the owning org.
    """
    try:
        row = await service.claim_domain(
            db,
            org_id=user.org_id,
            actor_user_id=user.id,
            payload=payload,
        )
    except DomainAlreadyClaimedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (
        MailgunAuthError,
        MailgunNotFound,
        MailgunProviderError,
        MailgunRateLimited,
    ) as exc:
        raise _map_mailgun_error(exc) from exc
    return DomainOut.model_validate(row)


@sender_domains_router.get(
    "",
    response_model=list[DomainOut],
)
async def list_sender_domains_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(_SENDING_DOMAINS_PERM)),
) -> list[DomainOut]:
    """List every domain claim (any status) the org has ever made.

    Includes released rows so the frontend can render the historical
    timeline. ``mailgun_domain_id`` is deliberately omitted from
    :class:`DomainOut`.
    """
    rows = await data_access.list_organization_domains_for_org(db, org_id=user.org_id)
    return [DomainOut.model_validate(r) for r in rows]


@sender_domains_router.post(
    "/{domain_id}/verify",
    response_model=DomainOut,
)
async def verify_sender_domain_endpoint(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(_SENDING_DOMAINS_PERM)),
) -> DomainOut:
    """Force a fresh ``PUT /v4/domains/{name}/verify`` against Mailgun
    and return the updated row.

    Cross-org (or missing) domain_id → 404. Mailgun 5xx surfaces as
    502; the domain's ``consecutive_failed_checks`` is untouched on
    5xx (per Step 3 service contract).
    """
    try:
        row = await service.verify_organization_email_domain(
            db,
            org_id=user.org_id,
            id=domain_id,
            actor_user_id=user.id,
        )
    except (
        MailgunAuthError,
        MailgunNotFound,
        MailgunProviderError,
        MailgunRateLimited,
    ) as exc:
        raise _map_mailgun_error(exc) from exc
    return DomainOut.model_validate(row)


@sender_domains_router.delete(
    "/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_sender_domain_endpoint(
    domain_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(_SENDING_DOMAINS_PERM)),
) -> Response:
    """Release a claimed domain.

    Calls Mailgun DELETE, marks the row ``released``, and cascades
    ``tbl_email_endpoint_details.domain_id`` to NULL for endpoints
    that pointed at this domain. Idempotent w.r.t. Mailgun — a
    Mailgun-side 404 is treated as success by the client wrapper.
    """
    try:
        await service.release_domain(
            db,
            org_id=user.org_id,
            id=domain_id,
            actor_user_id=user.id,
        )
    except (
        MailgunAuthError,
        MailgunNotFound,
        MailgunProviderError,
        MailgunRateLimited,
    ) as exc:
        raise _map_mailgun_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "sender_domains_router"]
