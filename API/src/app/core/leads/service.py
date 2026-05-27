"""Service layer for the leads module.

Responsibilities:

1. CRUD against the leads row, with two extra cross-cutting concerns
   handled here so the router stays thin:
   - `contact_id` is verified to belong to the active tenant (the ORM
     filter on `contacts` makes a foreign-org id appear as "not found",
     which we surface as a 422 rather than letting it FK-cascade).
   - `pipeline_stage` is validated against the `leads` pipeline's
     stage keys. Omitted on create → defaults to the first stage by
     `display_order`.
2. `custom_data` validation against `custom_field_definitions` rows
   with `entity_type='lead'`. Same pattern as contacts: unknown keys
   rejected, types coerced, required keys enforced on create.
3. `move_stage_for_lead` — thin wrapper around `pipelines.move_card`
   that also auto-syncs `Lead.status` with the destination stage's
   `is_won` / `is_lost` flags. The pipeline engine writes the audit
   row + status_change activity; this wrapper just stamps the status
   field afterwards.

Filtered list joins the `contacts` table so `q` (name/phone/email
search) and `source` (contact.source equality) can apply.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Literal, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.contacts.models import Contact
from src.app.core.custom_fields.models import (
    CustomFieldDefinition,
    FieldType,
)
from src.app.core.leads.models import Lead, LeadSource, LeadStatus
from src.app.core.leads.schemas import LOST_REASONS, LeadCreate, LeadUpdate
from src.app.core.pipelines import move_card
from src.app.core.pipelines.service import get_pipeline_by_key


# Server-side whitelist for `?sort=` on the list endpoint. Anything
# outside this set is rejected at the router via FastAPI's Literal
# Query validation. `contact_name` sorts via a JOIN to `contacts`.
_SORT_COLUMNS = {
    "created_at": Lead.created_at,
    "last_activity_at": Lead.last_activity_at,
    "contact_name": Contact.full_name,
}


_LEAD_ENTITY = "lead"
_LEADS_PIPELINE_KEY = "leads"
_LEADS_CARD_TABLE = "leads"


def _snapshot(lead: Lead) -> dict[str, Any]:
    return {
        "id": str(lead.id),
        "contact_id": str(lead.contact_id),
        "pipeline_stage": lead.pipeline_stage,
        "status": lead.status.value,
        "source": lead.source.value,
        "assigned_to_id": (
            str(lead.assigned_to_id)
            if lead.assigned_to_id is not None
            else None
        ),
        "budget": str(lead.budget) if lead.budget is not None else None,
        "expected_close_date": (
            lead.expected_close_date.isoformat()
            if lead.expected_close_date is not None
            else None
        ),
        "custom_data": lead.custom_data,
        "attribution": lead.attribution,
        "lost_reason": lead.lost_reason,
        "lost_reason_other": lead.lost_reason_other,
    }


# --- custom_data validation (mirrors `contacts.service` — intentionally
# duplicated for now; will be extracted into a shared helper when a
# third entity needs the same logic). ---


async def _load_field_defs(
    session: AsyncSession,
) -> dict[str, CustomFieldDefinition]:
    result = await session.execute(
        select(CustomFieldDefinition).where(
            CustomFieldDefinition.entity_type == _LEAD_ENTITY
        )
    )
    return {row.field_key: row for row in result.scalars()}


def _coerce_value(field_type: FieldType, key: str, value: Any) -> Any:
    if value is None:
        return None
    if field_type in (FieldType.text, FieldType.phone, FieldType.email, FieldType.select):
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected string",
            )
        return value
    if field_type is FieldType.multiselect:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected list of strings",
            )
        return value
    if field_type in (FieldType.number, FieldType.currency):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected number",
            )
        return value
    if field_type is FieldType.boolean:
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected boolean",
            )
        return value
    if field_type is FieldType.date:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO date string",
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO date",
            ) from exc
        return value
    if field_type is FieldType.datetime:
        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: expected ISO datetime string",
            )
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data.{key}: invalid ISO datetime",
            ) from exc
        return value
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"unhandled field_type {field_type!r}",
    )


async def _validate_custom_data(
    session: AsyncSession,
    *,
    payload: dict[str, Any],
    require_all_required: bool,
) -> dict[str, Any]:
    defs = await _load_field_defs(session)

    unknown = set(payload) - set(defs)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "custom_data contains keys not defined for entity "
                f"'lead': {sorted(unknown)}"
            ),
        )

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        cleaned[key] = _coerce_value(defs[key].field_type, key, value)

    if require_all_required:
        missing = [
            key
            for key, defn in defs.items()
            if defn.is_required and (key not in cleaned or cleaned[key] is None)
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"custom_data missing required keys: {sorted(missing)}",
            )
    return cleaned


# --- pipeline stage helpers ---


async def _resolve_initial_stage(
    session: AsyncSession,
    *,
    requested: Optional[str],
) -> str:
    """Pick the lead's starting stage. Caller-supplied wins if valid;
    otherwise we default to the first stage by display_order."""
    pipeline = await get_pipeline_by_key(session, key=_LEADS_PIPELINE_KEY)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "no 'leads' pipeline configured for this org — install the "
                "pack first"
            ),
        )
    stage_keys = {s.key for s in pipeline.stages}
    if requested:
        if requested not in stage_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"pipeline_stage {requested!r} is not part of the leads "
                    "pipeline"
                ),
            )
        return requested
    if not pipeline.stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the leads pipeline has no stages defined",
        )
    return min(pipeline.stages, key=lambda s: s.display_order).key


# --- CRUD ---


async def get_lead(session: AsyncSession, lead_id: uuid.UUID) -> Optional[Lead]:
    result = await session.execute(select(Lead).where(Lead.id == lead_id))
    return result.scalar_one_or_none()


async def _ensure_contact_in_scope(
    session: AsyncSession, contact_id: uuid.UUID
) -> None:
    # The tenant ORM filter ensures we only see in-org contacts; a missing
    # row therefore means either nonexistent or foreign-org → 422 either way.
    contact = (
        await session.execute(select(Contact.id).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"contact_id {contact_id} not found in this org",
        )


async def create_lead(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: LeadCreate,
    require_all_required: bool = True,
) -> Lead:
    """Create a lead.

    `require_all_required=True` (default) enforces every required
    custom-field definition — the right behaviour for staff-driven
    forms where the operator knows the org's schema.

    Public ingestion paths (embed widget, ad-form webhooks, bulk
    imports of unknown shape) pass `False` because the submitter
    can't possibly know the org's custom-field requirements;
    staff fill in the blanks afterwards via the edit form.
    """
    await _ensure_contact_in_scope(session, payload.contact_id)
    stage_key = await _resolve_initial_stage(
        session, requested=payload.pipeline_stage
    )
    cleaned_custom = await _validate_custom_data(
        session,
        payload=payload.custom_data,
        require_all_required=require_all_required,
    )

    lead = Lead(
        org_id=org_id,
        contact_id=payload.contact_id,
        pipeline_stage=stage_key,
        status=LeadStatus.active,
        source=payload.source,
        assigned_to_id=payload.assigned_to_id,
        budget=payload.budget,
        expected_close_date=payload.expected_close_date,
        custom_data=cleaned_custom,
        attribution=payload.attribution,
    )
    session.add(lead)
    await session.commit()
    await session.refresh(lead)

    await audit.log(
        "leads.created",
        entity_type="lead",
        entity_id=lead.id,
        after=_snapshot(lead),
    )
    return lead


async def update_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    payload: LeadUpdate,
) -> Lead:
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )

    before = _snapshot(lead)
    changes = payload.model_dump(exclude_unset=True)

    if "contact_id" in changes and changes["contact_id"] is not None:
        await _ensure_contact_in_scope(session, changes["contact_id"])

    if "custom_data" in changes:
        changes["custom_data"] = await _validate_custom_data(
            session,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )

    for key, value in changes.items():
        setattr(lead, key, value)
    await session.commit()
    await session.refresh(lead)

    await audit.log(
        "leads.updated",
        entity_type="lead",
        entity_id=lead.id,
        before=before,
        after=_snapshot(lead),
    )
    return lead


async def delete_lead(session: AsyncSession, *, lead_id: uuid.UUID) -> None:
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )
    before = _snapshot(lead)
    lead_uuid = lead.id
    await session.delete(lead)
    await session.commit()

    await audit.log(
        "leads.deleted",
        entity_type="lead",
        entity_id=lead_uuid,
        before=before,
    )


async def list_leads(
    session: AsyncSession,
    *,
    stage: Optional[str] = None,
    status_filter: Optional[LeadStatus] = None,
    assigned_to: Optional[uuid.UUID] = None,
    q: Optional[str] = None,
    source: Optional[str] = None,
    last_activity_lt: Optional[datetime] = None,
    last_activity_gt: Optional[datetime] = None,
    sort: Literal["created_at", "last_activity_at", "contact_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    custom_filters: Iterable[tuple[str, str]] = (),
    page: int = 1,
    size: int = 50,
) -> tuple[list[Lead], int]:
    """Filtered list of leads.

    `q` and `source` join `contacts` so the caller can search by the
    person's name / phone / email / source without first looking up
    contact ids on the client. All other filters apply directly to the
    leads row.

    `last_activity_lt` powers the "no activity in N days" chip — the FE
    passes `now() - 7d` to get leads gone cold. `last_activity_gt` is
    the inverse for "recently touched" if a future filter needs it.

    `sort` keys are whitelisted via `_SORT_COLUMNS`; `contact_name`
    forces the contacts JOIN even when `q`/`source` are absent.
    `last_activity_at` desc appends `NULLS LAST` so never-touched
    leads sink to the bottom.
    """
    filters: list[Any] = []
    needs_contact_join = False

    if stage:
        filters.append(Lead.pipeline_stage == stage)
    if status_filter is not None:
        filters.append(Lead.status == status_filter)
    if assigned_to is not None:
        filters.append(Lead.assigned_to_id == assigned_to)
    if last_activity_lt is not None:
        # Treat NULL last_activity_at as "very old" so the no-activity
        # chip surfaces never-touched leads, which is what reps want.
        filters.append(
            or_(
                Lead.last_activity_at < last_activity_lt,
                Lead.last_activity_at.is_(None),
            )
        )
    if last_activity_gt is not None:
        filters.append(Lead.last_activity_at > last_activity_gt)
    if q:
        like = f"%{q}%"
        filters.append(
            or_(
                Contact.full_name.ilike(like),
                Contact.phone.ilike(like),
                Contact.email.ilike(like),
            )
        )
        needs_contact_join = True
    if source:
        filters.append(Contact.source == source)
        needs_contact_join = True
    for key, value in custom_filters:
        filters.append(Lead.custom_data[key].astext == value)

    if sort == "contact_name":
        needs_contact_join = True

    where = and_(*filters) if filters else None

    base = select(Lead)
    count_stmt = select(func.count()).select_from(Lead)
    if needs_contact_join:
        base = base.join(Contact, Lead.contact_id == Contact.id)
        count_stmt = count_stmt.join(Contact, Lead.contact_id == Contact.id)
    if where is not None:
        base = base.where(where)
        count_stmt = count_stmt.where(where)

    sort_col = _SORT_COLUMNS[sort]
    if sort == "last_activity_at":
        primary = sort_col.asc().nulls_last() if order == "asc" else sort_col.desc().nulls_last()
    else:
        primary = sort_col.asc() if order == "asc" else sort_col.desc()
    base = base.order_by(primary, Lead.id.desc())
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(base.offset((page - 1) * size).limit(size))
    ).scalars().all()
    return list(rows), int(total)


# --- move-stage with status auto-sync ---


async def move_stage_for_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    to_stage: str,
    user_id: uuid.UUID,
    lost_reason: Optional[str] = None,
    lost_reason_other: Optional[str] = None,
) -> Lead:
    """Move a lead to a new stage and keep `status` in sync.

    Delegates the actual UPDATE + audit + activity to
    `pipelines.move_card`, then re-fetches the lead and stamps
    `status` based on the destination stage's `is_won` / `is_lost`
    flags. The two writes are separate transactions; that's acceptable
    because the lead's `status` is derived state, not authoritative —
    the pipeline_stage column is the source of truth.

    When the destination stage has `is_lost=true`, `lost_reason` is
    required (picklist enforced by `LOST_REASONS`). The FE collects
    it in the move-to-Lost modal and passes it through here in a
    single API call, so the timeline shows "moved to <stage> with
    reason=<x>" instead of two disconnected events.
    """
    lead = await get_lead(session, lead_id)
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )

    # Resolve the destination stage's flags up-front so we can reject
    # an incomplete move-to-Lost call before any DB mutation.
    pipeline = await get_pipeline_by_key(session, key=_LEADS_PIPELINE_KEY)
    new_stage = (
        next((s for s in pipeline.stages if s.key == to_stage), None)
        if pipeline is not None
        else None
    )
    if new_stage is not None and new_stage.is_lost:
        if lost_reason is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "lost_reason is required when moving a lead to a "
                    "Lost stage"
                ),
            )
        if lost_reason not in LOST_REASONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"lost_reason must be one of {list(LOST_REASONS)}",
            )
        if lost_reason == "other" and not (
            lost_reason_other and lost_reason_other.strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="lost_reason_other is required when lost_reason='other'",
            )

    # `move_card` validates pipeline + stage + card-table-allowlist and
    # raises HTTPException with the right status code on any problem.
    await move_card(
        session,
        pipeline_key=_LEADS_PIPELINE_KEY,
        card_table=_LEADS_CARD_TABLE,
        card_id=lead_id,
        to_stage_key=to_stage,
        user_id=user_id,
    )

    # `move_card` updates the row via raw SQL and commits, so the ORM's
    # cached attributes on `lead` are stale. Force a re-read before we
    # decide whether `status` needs syncing.
    await session.refresh(lead)

    new_status = (
        LeadStatus.won
        if new_stage and new_stage.is_won
        else LeadStatus.lost
        if new_stage and new_stage.is_lost
        else LeadStatus.active
    )

    needs_commit = False
    if lead.status != new_status:
        lead.status = new_status
        needs_commit = True
    if new_stage is not None and new_stage.is_lost:
        if lead.lost_reason != lost_reason:
            lead.lost_reason = lost_reason
            needs_commit = True
        if lead.lost_reason_other != lost_reason_other:
            lead.lost_reason_other = lost_reason_other
            needs_commit = True

    if needs_commit:
        await session.commit()
        await session.refresh(lead)
    return lead


__all__ = [
    "create_lead",
    "delete_lead",
    "get_lead",
    "list_leads",
    "move_stage_for_lead",
    "update_lead",
]
