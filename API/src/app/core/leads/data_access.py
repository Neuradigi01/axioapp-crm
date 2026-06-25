"""Data-access layer for the leads module.

Pure query helpers — no transactions, no audit, no business rules.
Leaf module; never imports a ``service.py``.

Operations grouped by entity:

  * Leads (``tbl_leads``)
      get_lead_by_id, count_leads_with_where,
      list_leads_with_where, bulk_delete_leads_by_ids,
      insert_lead, delete_lead_row
  * Scoring rules (``tbl_lead_scoring_rules``)
      get_scoring_rule_by_id, list_scoring_rules_for_org,
      insert_scoring_rule, delete_scoring_rule_row
  * Cross-module verifiers
      contact_exists_in_org — narrow projection check against
        ``tbl_contacts``; needed by the lead-create validator that
        rejects out-of-org contact ids
      user_has_active_membership — User ⋈ OrganizationMember check
        used by the reassign target validator (same shape as
        appointments DAL's version)

The WHERE-clause composition + sort-column whitelisting stays in
``service.py`` because the filter-DSL parsing + custom-field
validation are business-layer concerns. DAL accepts already-built
SQLAlchemy clause / column expressions and just executes them.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BinaryExpression, ClauseElement

from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead, LeadScoringRule
from src.app.core.users.models import OrganizationMember, User


# --- Leads --------------------------------------------------------------


async def get_lead_by_id(
    session: AsyncSession, lead_id: uuid.UUID
) -> Optional[Lead]:
    """Single-row read by PK. ``None`` on miss (or cross-tenant — the
    ORM filter applies)."""
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def count_leads_with_where(
    session: AsyncSession,
    *,
    where: Optional[ClauseElement] = None,
    needs_contact_join: bool = False,
) -> int:
    """COUNT against the leads table with an optional pre-built WHERE
    clause and optional contacts JOIN. Used by the list endpoint's
    ``with_total`` mode."""
    base = select(func.count()).select_from(Lead)
    if needs_contact_join:
        base = base.join(Contact, Lead.contact_id == Contact.id)
    if where is not None:
        base = base.where(where)
    return int((await session.execute(base)).scalar_one())


async def list_leads_with_where(
    session: AsyncSession,
    *,
    where: Optional[ClauseElement] = None,
    needs_contact_join: bool = False,
    primary_order: Any,
    secondary_order: Any,
    keyset_clause: Optional[ClauseElement] = None,
    offset: int = 0,
    limit: int,
) -> list[Lead]:
    """Paginated SELECT against the leads table.

    Accepts already-built order expressions (the service whitelists
    sort columns + handles NULLS LAST semantics) plus an optional
    ``keyset_clause`` for cursor-mode pagination. When ``keyset_clause``
    is supplied the caller typically passes ``offset=0`` and uses
    cursor-only semantics; offset-mode callers pass
    ``keyset_clause=None``.
    """
    base = select(Lead)
    if needs_contact_join:
        base = base.join(Contact, Lead.contact_id == Contact.id)
    if where is not None:
        base = base.where(where)
    if keyset_clause is not None:
        base = base.where(keyset_clause)
    base = base.order_by(primary_order, secondary_order)
    if offset:
        base = base.offset(offset)
    base = base.limit(limit)
    return list((await session.execute(base)).scalars().all())


async def bulk_delete_leads_by_ids(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """DELETE ``WHERE id IN (...) AND org_id = ...``. The ``org_id``
    predicate is belt-and-braces alongside the per-tenant RLS policy.
    Returns the row count deleted. Caller commits."""
    result = await session.execute(
        delete(Lead).where(Lead.id.in_(ids), Lead.org_id == org_id)
    )
    return int(result.rowcount or 0)


def insert_lead(session: AsyncSession, lead: Lead) -> None:
    """Register an already-constructed Lead for INSERT."""
    session.add(lead)


async def delete_lead_row(session: AsyncSession, lead: Lead) -> None:
    """Mark a Lead row for DELETE. Caller commits."""
    await session.delete(lead)


# --- Scoring rules ------------------------------------------------------


async def get_scoring_rule_by_id(
    session: AsyncSession, rule_id: uuid.UUID
) -> Optional[LeadScoringRule]:
    """Single-row read by PK."""
    result = await session.execute(
        select(LeadScoringRule).where(LeadScoringRule.id == rule_id)
    )
    return result.scalar_one_or_none()


async def list_scoring_rules_for_org(
    session: AsyncSession, org_id: uuid.UUID
) -> list[LeadScoringRule]:
    """All scoring rules (active + inactive) for the tenant, oldest
    first. The settings page surfaces both so an admin can re-enable
    an inactive rule without losing its history."""
    result = await session.execute(
        select(LeadScoringRule)
        .where(LeadScoringRule.org_id == org_id)
        .order_by(LeadScoringRule.created_at.asc())
    )
    return list(result.scalars())


def insert_scoring_rule(
    session: AsyncSession, rule: LeadScoringRule
) -> None:
    """Register an already-constructed LeadScoringRule for INSERT."""
    session.add(rule)


async def delete_scoring_rule_row(
    session: AsyncSession, rule: LeadScoringRule
) -> None:
    """Mark a LeadScoringRule row for DELETE. Caller commits."""
    await session.delete(rule)


# --- Cross-module verifiers ---------------------------------------------


async def contact_exists_in_org(
    session: AsyncSession, contact_id: uuid.UUID
) -> bool:
    """Narrow-column existence check used by the lead-create validator
    to reject out-of-org contact ids. The tenant ORM filter ensures
    only in-org contacts are visible; missing → caller raises 422."""
    contact = (
        await session.execute(
            select(Contact.id).where(Contact.id == contact_id)
        )
    ).scalar_one_or_none()
    return contact is not None


async def user_has_active_membership(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> bool:
    """True when ``user_uuid`` resolves to a User whose
    ``OrganizationMember`` row is active in ``org_id``. Used by the
    reassign target validator — same join + check the contacts /
    appointments / walk-ins reassigners use."""
    result = await session.execute(
        select(OrganizationMember.id)
        .join(User, User.id == OrganizationMember.user_member_id)
        .where(
            User.legacy_uuid == user_uuid,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.is_active.is_(True),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# --- Cursor-mode keyset helper -----------------------------------------


def build_keyset_clause(
    *,
    sort_col: Any,
    sort_value: Any,
    last_id: uuid.UUID,
    order: str,
) -> BinaryExpression:
    """Construct the ``tuple_(sort_col, Lead.id) < tuple_(value, id)``
    keyset bound for cursor-mode pagination. ``order='desc'`` produces
    ``<`` semantics; ``'asc'`` produces ``>``. The service decodes the
    cursor and chooses the sort column from its whitelist before
    calling here."""
    if order == "desc":
        return tuple_(sort_col, Lead.id) < tuple_(sort_value, last_id)
    return tuple_(sort_col, Lead.id) > tuple_(sort_value, last_id)


__all__ = [
    "build_keyset_clause",
    "bulk_delete_leads_by_ids",
    "contact_exists_in_org",
    "count_leads_with_where",
    "delete_lead_row",
    "delete_scoring_rule_row",
    "get_lead_by_id",
    "get_scoring_rule_by_id",
    "insert_lead",
    "insert_scoring_rule",
    "list_leads_with_where",
    "list_scoring_rules_for_org",
    "user_has_active_membership",
]
