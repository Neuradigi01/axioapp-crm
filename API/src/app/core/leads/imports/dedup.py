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
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


_NON_DIGIT = re.compile(r"\D")


def normalize_phone(value: Optional[str]) -> str:
    """Strip every non-digit. Empty string if input is None/blank."""
    if not value:
        return ""
    return _NON_DIGIT.sub("", value)


def lowercase_email(value: Optional[str]) -> str:
    """Trim + lowercase. Empty string if input is None/blank."""
    if not value:
        return ""
    return value.strip().lower()


async def find_existing_contact(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    phone: Optional[str],
    email: Optional[str],
) -> Optional[uuid.UUID]:
    """Return the id of an existing contact in `org_id` matching by
    phone OR email; None if no match (or if both inputs are blank).

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
        SELECT id FROM contacts
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
    return result.scalar()


__all__ = ["find_existing_contact", "lowercase_email", "normalize_phone"]
