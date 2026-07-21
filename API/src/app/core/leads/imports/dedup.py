"""Duplicate-contact detection for the bulk-import processor.

A row is treated as a duplicate when a contact in the same org has
either a matching normalised phone OR a matching lowercased email.
The match is OR (not AND) because real-world CSV exports often supply
only one of the two for any given person, and creating a second
contact row when one of those keys collides causes downstream pain.

Normalisation is intentionally simple:

  phone → strip every non-digit character (`re.sub(r"\\D", "", s)`)
          → "+91 98765-43210" becomes "919876543210"
  email → strip whitespace + lowercase

The lookup runs against the existing `contacts.phone` / `.email`
columns with on-the-fly normalisation. No `phone_normalized` /
`email_lower` indexed columns are added — for the per-import 50k-row
ceiling against typical few-hundred-contact orgs, a sequential scan
is microseconds. A follow-up perf task can add functional indexes
when a real customer hits the limit.

The dedup key set is hardcoded here for v1 (phone OR email). Making
it per-org configurable is a known follow-up.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NON_DIGIT = re.compile(r"\D")


def normalize_phone(value: str | None) -> str:
    """Strip every non-digit. Empty string if input is None/blank."""
    if not value:
        return ""
    return _NON_DIGIT.sub("", value)


def lowercase_email(value: str | None) -> str:
    """Trim + lowercase. Empty string if input is None/blank."""
    if not value:
        return ""
    return value.strip().lower()


@dataclass(frozen=True, slots=True)
class ExistingContactMatch:
    """Result of an importer contact-dedup lookup.

    ``matched_by_phone`` / ``matched_by_email`` describe which key(s)
    caused the hit — both may be True when the incoming row's phone
    AND email both matched the existing contact. The result-page
    reason breakdown uses these to tell operators *why* their row
    collapsed onto an existing contact.
    """

    contact_id: uuid.UUID
    matched_by_phone: bool
    matched_by_email: bool


async def find_existing_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str | None,
    email: str | None,
) -> uuid.UUID | None:
    """Return the id of an existing contact in `org_id` matching by
    phone OR email; None if no match (or if both inputs are blank).

    Slim companion to :func:`resolve_existing_contact` — callers that
    only need the id (Google/Meta webhooks, embed submissions) stay
    on this shape so the return type doesn't force the rich match
    dataclass on paths that would just discard it.
    """
    match = await resolve_existing_contact(
        session, org_id=org_id, phone=phone, email=email
    )
    return match.contact_id if match is not None else None


async def resolve_existing_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: str | None,
    email: str | None,
) -> ExistingContactMatch | None:
    """Return the match record for an existing contact in `org_id`
    matching by phone OR email; None if no match (or if both inputs
    are blank). Callers that need to know *which* key matched (the
    bulk-import result page) use this shape; callers that just need
    the id use :func:`find_existing_contact`.

    `org_id` is passed explicitly even though RLS + the ORM tenant
    filter scope reads to the active org — this function runs raw
    SQL via `text()`, which the ORM filter does NOT apply to, so we
    belt-and-suspenders the org column in the WHERE clause.
    """
    phone_norm = normalize_phone(phone)
    email_low = lowercase_email(email)
    if not phone_norm and not email_low:
        return None

    sql = text(
        """
        SELECT
            id,
            (:phone_norm <> '' AND regexp_replace(coalesce(phone, ''), '\\D', '', 'g') = :phone_norm) AS matched_phone,
            (:email_low  <> '' AND lower(coalesce(email, '')) = :email_low)                            AS matched_email
        FROM tbl_contacts
        WHERE org_id = :org_id
          AND (
              (:phone_norm <> '' AND regexp_replace(coalesce(phone, ''), '\\D', '', 'g') = :phone_norm)
              OR (:email_low <> '' AND lower(coalesce(email, '')) = :email_low)
          )
        LIMIT 1
        """
    )
    result = await session.execute(
        sql,
        {
            "org_id": str(org_id),
            "phone_norm": phone_norm,
            "email_low": email_low,
        },
    )
    row = result.first()
    if row is None:
        return None
    return ExistingContactMatch(
        contact_id=row[0],
        matched_by_phone=bool(row[1]),
        matched_by_email=bool(row[2]),
    )


__all__ = [
    "ExistingContactMatch",
    "find_existing_contact",
    "lowercase_email",
    "normalize_phone",
    "resolve_existing_contact",
]
