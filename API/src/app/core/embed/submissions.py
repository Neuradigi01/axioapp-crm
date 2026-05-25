"""Service layer for the public widget submission endpoint.

`submit()` is the single entry point — the router does nothing but
extract HTTP details (key from header, IP from request) and call this.

Pipeline:

  1. Honeypot check — non-empty → silent 200, no lead created. Bots
     learn nothing about being detected.
  2. Key required (header or body field). Missing → 401.
  3. Key lookup via `embed.service.find_by_plain_key`. Missing /
     revoked / garbage → 401 with a generic message (don't leak
     which keys exist).
  4. Per-key + per-IP rate limit (sliding window, in-memory). Either
     overage → 429 with `Retry-After` set to the longer of the two.
  5. Open a tenant context for the key's org (since the public endpoint
     has no JWT, this is what authorises the dedup query + lead/contact
     writes against RLS).
  6. Dedup-by-phone-or-email. If existing contact found, reuse its id.
     Otherwise create a new contact.
  7. Create a lead with `source='widget'`, `actor_user_id=None`,
     and the `attribution` payload from the request.
  8. Emit `embed.submission.accepted` audit event.

`actor_user_id=None` is correct: there's no logged-in CRM user driving
this — it's an anonymous form submission from a customer's website.
Audit rows for these submissions correctly show `user_id=NULL`.
"""
from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status

from src.app.core import audit
from src.app.core.contacts.schemas import ContactCreate
from src.app.core.contacts.service import create_contact
from src.app.core.embed.rate_limit import check_per_ip, check_per_key
from src.app.core.embed.schemas import EmbedSubmission
from src.app.core.embed.service import find_by_plain_key
from src.app.core.leads.imports.dedup import find_existing_contact
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate
from src.app.core.leads.service import create_lead
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """What the router converts to a `EmbedSubmissionResponse`."""

    accepted: bool                       # True = lead created
    lead_id: Optional[uuid.UUID]         # None for silent-drop / honeypot
    thank_you_url: Optional[str]         # Step 3's widget config will populate


async def submit(
    *,
    payload: EmbedSubmission,
    header_key: Optional[str],
    ip: str,
) -> SubmissionResult:
    """Process one widget submission. Raises HTTPException on auth /
    rate-limit failures; returns SubmissionResult otherwise.

    A silent-drop (honeypot triggered) returns a result with
    `accepted=False, lead_id=None` and the caller responds with a
    200 — bots don't learn they were caught.
    """
    # 1. Honeypot — bots fill every field, including hidden ones.
    if payload.honeypot:
        logger.info(
            "embed.submission.silent_drop honeypot from ip=%s", ip
        )
        # Step 8 wires the `embed.submission.rejected_spam` audit
        # event with the org context. We don't have org context here
        # (lookup hasn't happened yet) so just log and return.
        return SubmissionResult(
            accepted=False, lead_id=None, thank_you_url=None
        )

    # 2. Resolve the embed key. Header wins over body.
    plain_key = header_key or payload.embed_key
    if not plain_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing embed key.",
        )

    # 3. Key lookup. find_by_plain_key opens its own session and
    # bypasses tenant-context (no context set yet on this request).
    key_row = await find_by_plain_key(plain_key, ip=ip)
    if key_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked embed key.",
        )

    # 4. Rate limit per-key + per-IP. Either trip → 429.
    rl_key = check_per_key(key_row.prefix)
    rl_ip = check_per_ip(ip)
    if not rl_key.allowed or not rl_ip.allowed:
        retry_after = max(rl_key.retry_after, rl_ip.retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": str(math.ceil(retry_after))},
        )

    org_id = key_row.org_id
    key_id = key_row.id

    # 5. Set tenant context so RLS + audit `org_id` derive correctly.
    ctx_token = set_context(RequestContext(org_id=org_id, user_id=None))
    try:
        async with async_session() as session:
            # 6. Dedup-by-phone-or-email — reuse the same helper the
            # bulk-import processor uses. If the visitor already exists
            # as a contact, we don't create a second contact row; we
            # do create a new lead so the rep sees a fresh inquiry.
            existing_id = await find_existing_contact(
                session,
                org_id=org_id,
                phone=payload.phone,
                email=payload.email,
            )
            if existing_id is not None:
                contact_id = existing_id
            else:
                # Combine interest + notes into the contact's notes
                # field so we don't lose the data Step 3's widget
                # config hasn't decided where to land yet.
                combined_notes = _combine_notes(
                    payload.interest, payload.notes
                )
                contact = await create_contact(
                    session,
                    org_id=org_id,
                    payload=ContactCreate(
                        full_name=payload.full_name,
                        phone=payload.phone,
                        email=payload.email,
                        source="widget",
                        notes=combined_notes,
                    ),
                )
                contact_id = contact.id

            # 7. Create the lead.
            lead = await create_lead(
                session,
                org_id=org_id,
                payload=LeadCreate(
                    contact_id=contact_id,
                    source=LeadSource.widget,
                    attribution=payload.attribution.model_dump(
                        exclude_none=False
                    ),
                ),
            )

        # 8. Audit. The org context is still set so audit.log derives
        # org_id from it; user_id stays None (anonymous submission).
        await audit.log(
            "embed.submission.accepted",
            entity_type="lead",
            entity_id=lead.id,
            after={
                "lead_id": str(lead.id),
                "contact_id": str(contact_id),
                "key_id": str(key_id),
                "key_prefix": key_row.prefix,
                "referrer": payload.attribution.referrer,
            },
        )
        return SubmissionResult(
            accepted=True, lead_id=lead.id, thank_you_url=None
        )
    finally:
        reset_context(ctx_token)


def _combine_notes(
    interest: Optional[str], notes: Optional[str]
) -> Optional[str]:
    """Fold the widget's `interest` + `notes` into a single notes
    string so neither value is lost in v1. Step 3 will let orgs
    route these to dedicated standard / custom fields.
    """
    pieces: list[str] = []
    if interest:
        pieces.append(f"Interest: {interest}")
    if notes:
        pieces.append(notes)
    return "\n\n".join(pieces) if pieces else None


__all__ = ["SubmissionResult", "submit"]
