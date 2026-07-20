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
4. List endpoint supports both offset pagination (legacy callers,
   ``page`` + ``size``) and cursor pagination (Step 6 FE, ``cursor`` +
   ``limit``). The two modes share the same WHERE pipeline, including
   the new JSON filter DSL.
5. Lead-scoring rule CRUD and the score-recompute hook fired from
   ``create_lead`` and ``update_lead``.

Filtered list joins the `contacts` table so `q` (name/phone/email
search) and `source` (contact.source equality) can apply.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.activities.models import ActivityType
from src.app.core.contacts.models import Contact
from src.app.core.leads import data_access as _da
from src.app.core.leads import filter_dsl, scoring
from src.app.core.leads.csv_export import resolve_custom_columns
from src.app.core.leads.models import (
    Lead,
    LeadScoringRule,
    LeadStatus,
)
from src.app.core.leads.schemas import (
    LOST_REASONS,
    LeadCreate,
    LeadScoringRuleCreate,
    LeadScoringRuleUpdate,
    LeadUpdate,
)
from src.app.core.pipelines import move_card
from src.app.core.pipelines.service import get_pipeline_by_key
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found

# Server-side whitelist for `?sort=` on the list endpoint. Anything
# outside this set is rejected at the router via FastAPI's Literal
# Query validation. `contact_name` sorts via a JOIN to `contacts`.
_SORT_COLUMNS = {
    "created_at": Lead.created_at,
    "last_activity_at": Lead.last_activity_at,
    "lead_score": Lead.lead_score,
    "contact_name": Contact.full_name,
}


# Limits for the cursor-paginated list endpoint. Tightening below 1
# would let a caller spin on empty pages; loosening above 200 stops
# being a "page" and starts being an export — they should use the
# CSV endpoint instead.
_LIMIT_MIN = 1
_LIMIT_MAX = 200
_LIMIT_DEFAULT = 50


_LEAD_ENTITY = "lead"
_LEADS_PIPELINE_KEY = "leads"
_LEADS_CARD_TABLE = "tbl_leads"


_SNAPSHOT_FIELDS = (
    "id",
    "contact_id",
    "pipeline_stage",
    "status",
    "source",
    "assigned_to_id",
    "budget",
    "currency",
    "expected_close_date",
    "custom_data",
    "attribution",
    "lost_reason",
    "lost_reason_other",
    "won_value",
    "close_date",
    "won_reason",
    "won_at",
    "lost_at",
)


def _snapshot(lead: Lead) -> dict[str, Any]:
    return snapshot(lead, fields=_SNAPSHOT_FIELDS)


# --- pipeline stage helpers ---


async def _resolve_initial_stage(
    session: AsyncSession,
    *,
    requested: str | None,
) -> str:
    """Pick the lead's starting stage. Caller-supplied wins if valid;
    otherwise we default to the first stage by display_order."""
    pipeline = await get_pipeline_by_key(session, key=_LEADS_PIPELINE_KEY)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("no 'leads' pipeline configured for this org — install the pack first"),
        )
    stage_keys = {s.key for s in pipeline.stages}
    if requested:
        if requested not in stage_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"pipeline_stage {requested!r} is not part of the leads pipeline"),
            )
        return requested
    if not pipeline.stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="the leads pipeline has no stages defined",
        )
    return min(pipeline.stages, key=lambda s: s.display_order).key


# --- CRUD ---


async def get_lead(session: AsyncSession, lead_id: uuid.UUID) -> Lead | None:
    return await _da.get_lead_by_id(session, lead_id)


async def get_lead_visible_to(session: AsyncSession, *, caller, lead_id: uuid.UUID) -> Lead:
    """Fetch a lead with row-level visibility enforced.

    Raises 404 when the lead doesn't exist OR when the caller lacks
    `users.read` and the lead isn't theirs. Returning 404 (not 403)
    on the visibility miss avoids leaking the existence of leads in
    other reps' books.
    """
    from src.app.core.permissions.service import role_has_permission

    lead = await _da.get_lead_by_id(session, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")
    if lead.assigned_to_id != caller.legacy_uuid and not await role_has_permission(
        session, caller.role_id, "users.read"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")
    return lead


async def _ensure_contact_in_scope(session: AsyncSession, contact_id: uuid.UUID) -> None:
    if not await _da.contact_exists_in_org(session, contact_id):
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
    stage_key = await _resolve_initial_stage(session, requested=payload.pipeline_stage)
    cleaned_custom = await validate_custom_data(
        session,
        entity_type=_LEAD_ENTITY,
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
    _da.insert_lead(session, lead)
    await session.flush()
    # Score the freshly inserted row before the commit so the persisted
    # value matches what the caller will see when they next GET the lead.
    await scoring.recompute_lead(session, lead=lead)
    # Bump the linked contact's ``last_activity_at`` so the contacts
    # list (sorted by activity) surfaces the just-touched customer at
    # the top — matches the standard CRM expectation of "new activity
    # brings the record forward". Also nudges ``updated_at`` via the
    # ORM's ``onupdate`` clause.
    from datetime import UTC, datetime

    from src.app.core.contacts.models import Contact

    await session.execute(
        Contact.__table__.update()
        .where(Contact.id == payload.contact_id)
        .values(last_activity_at=datetime.now(UTC))
    )
    await session.commit()
    await session.refresh(lead)

    await log_entity_change(
        action="leads.created",
        entity_type="lead",
        entity_id=lead.id,
        after=_snapshot(lead),
    )

    # tasks/automation-engine Step 6 — every lead-creation source
    # (manual / API, embed widget, Google Ads, Meta Ads, bulk CSV
    # import) lands here through `ingest_lead → create_lead`, so a
    # single publish at this chokepoint fires the seeded "Lead
    # Confirmation" trigger uniformly regardless of source. The
    # helper swallows any subscriber failure — the lead is already
    # committed; a misbehaving handler can't roll it back.
    await _publish_lead_created(session, org_id=org_id, lead=lead)

    return lead


async def _publish_lead_created(session: AsyncSession, *, org_id: uuid.UUID, lead: Lead) -> None:
    """Build the ``lead.created`` envelope + publish via the bus.
    Snapshot's the contact + org so the recipient resolver + the
    template renderer have everything they need without per-handler
    DB hits."""
    try:
        from sqlalchemy import select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        contact = (
            await session.execute(select(Contact).where(Contact.id == lead.contact_id))
        ).scalar_one_or_none()
        org = (
            await session.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

        payload: dict = {
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "source": str(lead.source) if lead.source else None,
            "created_at": (lead.created_at.isoformat() if lead.created_at else None),
            "lead": {
                "id": str(lead.id),
                "source": str(lead.source) if lead.source else None,
                "status": (
                    lead.status.value if hasattr(lead.status, "value") else str(lead.status)
                ),
                "pipeline_stage": lead.pipeline_stage,
                "assigned_to_id": (str(lead.assigned_to_id) if lead.assigned_to_id else None),
                "budget": float(lead.budget) if lead.budget is not None else None,
                "attribution": lead.attribution or {},
            },
        }
        if contact is not None:
            payload["contact"] = {
                "id": str(contact.id),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
            }

        await events_publish(
            "lead.created",
            payload,
            org_id=org_id,
            event_id=f"lead_created:{lead.id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "leads.create publish_lead_created_failed org=%s lead=%s",
            org_id,
            lead.id,
        )


async def update_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    payload: LeadUpdate,
) -> Lead:
    lead = ensure_found(await get_lead(session, lead_id), entity="lead")

    before = _snapshot(lead)
    changes = payload.model_dump(exclude_unset=True)

    if "contact_id" in changes and changes["contact_id"] is not None:
        await _ensure_contact_in_scope(session, changes["contact_id"])

    if "custom_data" in changes:
        changes["custom_data"] = await validate_custom_data(
            session,
            entity_type=_LEAD_ENTITY,
            payload=changes["custom_data"] or {},
            require_all_required=False,
        )

    for key, value in changes.items():
        setattr(lead, key, value)
    await session.flush()
    # Recompute the score iff a column referenced by any active rule
    # changed — keeps the hot path cheap when reps update freeform
    # notes / custom_data that no rule cares about.
    changed_fields = set(changes.keys())
    relevant = await scoring.rule_relevant_fields(session, org_id=lead.org_id)
    if relevant and changed_fields & relevant:
        await scoring.recompute_lead(session, lead=lead)
    await session.commit()
    await session.refresh(lead)

    await log_entity_change(
        action="leads.updated",
        entity_type="lead",
        entity_id=lead.id,
        before=before,
        after=_snapshot(lead),
    )
    return lead


async def delete_lead(session: AsyncSession, *, lead_id: uuid.UUID) -> None:
    lead = ensure_found(await get_lead(session, lead_id), entity="lead")
    before = _snapshot(lead)
    lead_uuid = lead.id
    await _da.delete_lead_row(session, lead)
    await session.commit()

    await log_entity_change(
        action="leads.deleted",
        entity_type="lead",
        entity_id=lead_uuid,
        before=before,
    )


async def _build_list_query(
    session: AsyncSession,
    *,
    stage: str | None,
    status_filter: LeadStatus | None,
    assigned_to: uuid.UUID | None,
    q: str | None,
    source: str | None,
    last_activity_lt: datetime | None,
    last_activity_gt: datetime | None,
    custom_filters: Iterable[tuple[str, str]],
    filter_dsl_payload: dict[str, Any] | None,
    sort: str,
) -> tuple[Any, list[Any], bool]:
    """Translate the union of convenience filters + DSL into a single
    boolean WHERE clause + the JOIN hint.

    Returned tuple: ``(where_clause_or_None, filters_list, needs_contact_join)``.
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

    if filter_dsl_payload:
        try:
            parsed = filter_dsl.parse(filter_dsl_payload)
            allowed_custom = set(await resolve_custom_columns(session))
            dsl_clause, dsl_needs_join = filter_dsl.to_sqlalchemy(
                parsed, allowed_custom_keys=allowed_custom
            )
        except filter_dsl.FilterDslError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"invalid filter: {exc}",
            ) from exc
        if dsl_clause is not None:
            filters.append(dsl_clause)
        needs_contact_join = needs_contact_join or dsl_needs_join

    if sort == "contact_name":
        needs_contact_join = True

    where = and_(*filters) if filters else None
    return where, filters, needs_contact_join


def _order_clause(sort: str, order: str):
    sort_col = _SORT_COLUMNS[sort]
    if sort == "last_activity_at":
        return sort_col.asc().nulls_last() if order == "asc" else sort_col.desc().nulls_last()
    return sort_col.asc() if order == "asc" else sort_col.desc()


def _encode_cursor(sort_value: Any, lead_id: uuid.UUID) -> str:
    """Base64-encode the keyset cursor."""
    if isinstance(sort_value, datetime):
        payload_v: Any = sort_value.isoformat()
    elif isinstance(sort_value, date):
        payload_v = sort_value.isoformat()
    elif sort_value is None:
        payload_v = None
    else:
        payload_v = sort_value if isinstance(sort_value, (int, float, str)) else str(sort_value)
    raw = json.dumps({"v": payload_v, "id": str(lead_id)})
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str, sort: str) -> tuple[Any, uuid.UUID]:
    """Inverse of ``_encode_cursor``. Tampering → 400."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        v_raw = payload["v"]
        id_str = payload["id"]
        lead_id = uuid.UUID(id_str)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid cursor",
        ) from exc
    if v_raw is None:
        return None, lead_id
    if sort in ("created_at", "last_activity_at"):
        try:
            return datetime.fromisoformat(v_raw), lead_id
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid cursor",
            ) from exc
    if sort == "lead_score":
        try:
            return int(v_raw), lead_id
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid cursor",
            ) from exc
    return str(v_raw), lead_id


async def list_leads_visible_to(
    session: AsyncSession,
    *,
    caller,
    stage: str | None = None,
    status_filter: LeadStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    q: str | None = None,
    source: str | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    page: int = 1,
    size: int = _LIMIT_DEFAULT,
    cursor: str | None = None,
    limit: int | None = None,
    with_total: bool = True,
) -> tuple[list[Lead], int | None, str | None]:
    """Row-level visibility wrapper.

    Callers without `users.read` (employees vs. managers) only see
    leads assigned to them. Any `assigned_to=<other>` they pass is
    silently clamped to self. Business rule — moved out of the
    router so this is the single point of enforcement.
    """
    from src.app.core.permissions.service import role_has_permission

    if not await role_has_permission(session, caller.role_id, "users.read"):
        assigned_to = caller.legacy_uuid
    return await list_leads(
        session,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        sort=sort,
        order=order,
        custom_filters=custom_filters,
        filter_dsl_payload=filter_dsl_payload,
        page=page,
        size=size,
        cursor=cursor,
        limit=limit,
        with_total=with_total,
    )


async def list_leads(
    session: AsyncSession,
    *,
    stage: str | None = None,
    status_filter: LeadStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    q: str | None = None,
    source: str | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    page: int = 1,
    size: int = _LIMIT_DEFAULT,
    cursor: str | None = None,
    limit: int | None = None,
    with_total: bool = True,
) -> tuple[list[Lead], int | None, str | None]:
    """Filtered list of leads, supporting two pagination modes."""
    where, _filters, needs_contact_join = await _build_list_query(
        session,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        custom_filters=custom_filters,
        filter_dsl_payload=filter_dsl_payload,
        sort=sort,
    )

    primary = _order_clause(sort, order)
    # Secondary key on `Lead.id` makes the keyset bound unambiguous on
    # ties and matches the composite indexes added in migration 0070.
    secondary = Lead.id.desc() if order == "desc" else Lead.id.asc()

    total: int | None = None
    if with_total:
        total = await _da.count_leads_with_where(
            session, where=where, needs_contact_join=needs_contact_join
        )

    cursor_eligible_sorts = {"created_at", "last_activity_at", "lead_score"}
    if cursor is not None and sort not in cursor_eligible_sorts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"cursor pagination does not support sort={sort!r}; use page/size mode instead"
            ),
        )

    if cursor is not None:
        # --- cursor mode ---
        effective_limit = max(_LIMIT_MIN, min(_LIMIT_MAX, limit or _LIMIT_DEFAULT))
        sort_value, last_id = _decode_cursor(cursor, sort)
        sort_col = _SORT_COLUMNS[sort]
        keyset = _da.build_keyset_clause(
            sort_col=sort_col,
            sort_value=sort_value,
            last_id=last_id,
            order=order,
        )
        # Fetch limit+1 to determine whether there's a next page
        # without a separate COUNT.
        rows = await _da.list_leads_with_where(
            session,
            where=where,
            needs_contact_join=needs_contact_join,
            primary_order=primary,
            secondary_order=secondary,
            keyset_clause=keyset,
            offset=0,
            limit=effective_limit + 1,
        )
        has_more = len(rows) > effective_limit
        page_rows = list(rows[:effective_limit])
        next_cursor: str | None = None
        if has_more and page_rows:
            tail = page_rows[-1]
            next_cursor = _encode_cursor(getattr(tail, sort), tail.id)
        return page_rows, total, next_cursor

    # --- offset mode (default / legacy) ---
    effective_size = max(_LIMIT_MIN, min(_LIMIT_MAX, size))
    effective_page = max(1, page)
    rows = await _da.list_leads_with_where(
        session,
        where=where,
        needs_contact_join=needs_contact_join,
        primary_order=primary,
        secondary_order=secondary,
        keyset_clause=None,
        offset=(effective_page - 1) * effective_size,
        limit=effective_size + 1,
    )
    has_more = len(rows) > effective_size
    page_rows = list(rows[:effective_size])
    next_cursor = None
    if has_more and page_rows and sort in cursor_eligible_sorts:
        tail = page_rows[-1]
        next_cursor = _encode_cursor(getattr(tail, sort), tail.id)
    return page_rows, total, next_cursor


async def list_leads_where(
    session: AsyncSession,
    *,
    stage: str | None = None,
    status_filter: LeadStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    q: str | None = None,
    source: str | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = "created_at",
) -> tuple[Any, bool]:
    """Companion to ``list_leads`` used by the CSV export: builds and
    returns the same combined WHERE clause + JOIN hint, without
    executing it."""
    where, _filters, needs_join = await _build_list_query(
        session,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        custom_filters=custom_filters,
        filter_dsl_payload=filter_dsl_payload,
        sort=sort,
    )
    return where, needs_join


# --- move-stage with status auto-sync ---


async def move_stage_for_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    to_stage: str,
    user_id: uuid.UUID,
    lost_reason: str | None = None,
    lost_reason_other: str | None = None,
    won_value: Any = None,
    close_date: Any = None,
    won_reason: str | None = None,
) -> Lead:
    """Move a lead to a new stage and keep `status` in sync.

    On move-to-Lost: ``lost_reason`` (picklist) is required. On
    move-to-Won: ``won_value`` / ``close_date`` / ``won_reason`` are
    all optional at the API layer — the frontend prompts and enforces.
    First entry into an is_won / is_lost stage stamps ``won_at`` /
    ``lost_at`` respectively (F22 lifecycle timestamps); re-entry
    doesn't re-stamp so the timeline shows the *first* close, not the
    latest kanban shuffle.

    Publishes ``lead.status_changed`` on every actual transition so
    automations / workflows can subscribe. No-op moves (target stage
    equals current stage) skip the publish.
    """
    lead = ensure_found(await get_lead(session, lead_id), entity="lead")
    from_stage = lead.pipeline_stage
    from_status = (
        lead.status.value if hasattr(lead.status, "value") else str(lead.status)
    )

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
                detail=("lost_reason is required when moving a lead to a Lost stage"),
            )
        if lost_reason not in LOST_REASONS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"lost_reason must be one of {list(LOST_REASONS)}",
            )
        if lost_reason == "other" and not (lost_reason_other and lost_reason_other.strip()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="lost_reason_other is required when lost_reason='other'",
            )

    await move_card(
        session,
        pipeline_key=_LEADS_PIPELINE_KEY,
        card_table=_LEADS_CARD_TABLE,
        card_id=lead_id,
        to_stage_key=to_stage,
        user_id=user_id,
    )

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
        # F22 lifecycle timestamp — stamp first-lost only.
        if lead.lost_at is None:
            from datetime import UTC, datetime as _dt

            lead.lost_at = _dt.now(UTC)
            needs_commit = True
    if new_stage is not None and new_stage.is_won:
        # F2 won-capture — only overwrite when the caller supplies a
        # value; a re-drag to Won without new metadata keeps the
        # earlier close info intact.
        if won_value is not None and lead.won_value != won_value:
            lead.won_value = won_value
            needs_commit = True
        if close_date is not None and lead.close_date != close_date:
            lead.close_date = close_date
            needs_commit = True
        if won_reason is not None and lead.won_reason != won_reason:
            lead.won_reason = won_reason
            needs_commit = True
        # F22 lifecycle timestamp — stamp first-won only.
        if lead.won_at is None:
            from datetime import UTC, datetime as _dt

            lead.won_at = _dt.now(UTC)
            needs_commit = True

    if needs_commit:
        await session.commit()
        await session.refresh(lead)

    # Only publish on a real transition — a same-stage "move" is a
    # UI no-op and should not fan out to subscribers.
    if from_stage != lead.pipeline_stage:
        await _publish_lead_status_changed(
            session,
            org_id=lead.org_id,
            lead=lead,
            from_stage=from_stage,
            from_status=from_status,
        )
    return lead


async def _publish_lead_status_changed(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    lead: Lead,
    from_stage: str,
    from_status: str,
) -> None:
    """Emit the ``lead.status_changed`` envelope. Mirrors the
    ``lead.created`` publisher's contact + org snapshotting so
    automation / workflow handlers have everything without a
    per-handler DB hit. Failures are swallowed + logged — an event-bus
    hiccup must never bubble back to the operator who just moved a
    kanban card.
    """
    try:
        from sqlalchemy import select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization

        contact = (
            await session.execute(select(Contact).where(Contact.id == lead.contact_id))
        ).scalar_one_or_none()
        org = (
            await session.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()

        to_stage = lead.pipeline_stage
        to_status = (
            lead.status.value if hasattr(lead.status, "value") else str(lead.status)
        )

        payload: dict = {
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "from_stage": from_stage,
            "to_stage": to_stage,
            "from_status": from_status,
            "to_status": to_status,
            "lead": {
                "id": str(lead.id),
                "pipeline_stage": to_stage,
                "status": to_status,
                "source": str(lead.source) if lead.source else None,
                "assigned_to_id": (
                    str(lead.assigned_to_id) if lead.assigned_to_id else None
                ),
                "budget": float(lead.budget) if lead.budget is not None else None,
                "lost_reason": lead.lost_reason,
            },
        }
        if contact is not None:
            # Derive first / last name from ``full_name`` so templates
            # using ``{{contact.first_name}}`` render out of the box.
            full = contact.full_name or ""
            parts = full.split(None, 1) if full else []
            first = parts[0] if parts else ""
            last = parts[1] if len(parts) > 1 else ""
            payload["contact"] = {
                "id": str(contact.id),
                "first_name": first,
                "last_name": last,
                "full_name": full,
                "email": contact.email,
                "phone": contact.phone,
            }
        if org is not None:
            payload["org"] = {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "support_email": getattr(org, "support_email", "") or "",
            }

        await events_publish(
            "lead.status_changed",
            payload,
            org_id=org_id,
            # Include both stages so consecutive fires on the same
            # lead land as distinct event_ids — otherwise dedup would
            # collapse the second transition into a replay.
            event_id=f"lead_status_changed:{lead.id}:{from_stage}->{to_stage}:"
            f"{lead.updated_at.isoformat() if lead.updated_at else ''}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "leads.move_stage publish_lead_status_changed_failed org=%s lead=%s",
            org_id,
            lead.id,
        )


# --- Reassign / bulk actions -------------------------------------------------


async def _assert_user_in_org(
    session: AsyncSession, *, org_id: uuid.UUID, user_uuid: uuid.UUID
) -> None:
    """422 if the target user has no active membership in this org."""
    if not await _da.user_has_active_membership(session, org_id=org_id, user_uuid=user_uuid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="target user is not a member of this organisation",
        )


def _reassign_payload(
    *, from_id: uuid.UUID | None, to_id: uuid.UUID | None, note: str | None
) -> dict[str, Any]:
    return {
        "from": str(from_id) if from_id is not None else None,
        "to": str(to_id) if to_id is not None else None,
        "note": note,
    }


async def reassign_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> Lead:
    """Single-row reassign. Writes an `Activity(type=reassign)` on the
    same session so the lead update + the timeline row commit atomically."""
    lead = ensure_found(await get_lead(session, lead_id), entity="lead")
    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    before_id = lead.assigned_to_id
    if before_id == assigned_to_id:
        # Identity reassign — no-op; don't pollute the timeline.
        return lead

    before = _snapshot(lead)
    lead.assigned_to_id = assigned_to_id
    await activities.record_in_session(
        session,
        org_id=org_id,
        entity_type="lead",
        entity_id=lead.id,
        type=ActivityType.reassign,
        payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
        user_id=actor_user_id,
    )
    await session.commit()
    await session.refresh(lead)

    await audit.log(
        "leads.reassigned",
        entity_type="lead",
        entity_id=lead.id,
        before=before,
        after=_snapshot(lead),
    )
    return lead


async def bulk_reassign_leads(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
    assigned_to_id: uuid.UUID | None,
    note: str | None,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Reassign N leads in one transaction. Returns rows actually touched
    (identity-reassign rows are silently skipped)."""
    if assigned_to_id is not None:
        await _assert_user_in_org(session, org_id=org_id, user_uuid=assigned_to_id)

    reassigned = 0
    for lid in ids:
        lead = await get_lead(session, lid)
        if lead is None:
            continue
        if lead.assigned_to_id == assigned_to_id:
            continue
        before_id = lead.assigned_to_id
        lead.assigned_to_id = assigned_to_id
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type="lead",
            entity_id=lead.id,
            type=ActivityType.reassign,
            payload=_reassign_payload(from_id=before_id, to_id=assigned_to_id, note=note),
            user_id=actor_user_id,
        )
        reassigned += 1

    await session.commit()
    return reassigned


async def bulk_delete_leads(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete N leads. Belt + suspenders: `org_id` in WHERE alongside
    the per-tenant RLS policy."""
    rowcount = await _da.bulk_delete_leads_by_ids(session, ids=ids, org_id=org_id)
    await session.commit()
    return rowcount


# --- Scoring rule CRUD ------------------------------------------------------


def _scoring_snapshot(rule: LeadScoringRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "condition": rule.condition,
        "points": rule.points,
        "active": rule.active,
    }


def _validate_scoring_condition(condition: dict[str, Any]) -> None:
    """Parse + validate that a rule condition is scorable in-memory."""
    try:
        parsed = filter_dsl.parse(condition)
        filter_dsl.validate_scorable(parsed)
    except filter_dsl.FilterDslError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid rule condition: {exc}",
        ) from exc


async def list_scoring_rules(session: AsyncSession, *, org_id: uuid.UUID) -> list[LeadScoringRule]:
    """All rules (active + inactive) for the tenant, oldest first."""
    return await _da.list_scoring_rules_for_org(session, org_id)


async def get_scoring_rule(session: AsyncSession, *, rule_id: uuid.UUID) -> LeadScoringRule | None:
    return await _da.get_scoring_rule_by_id(session, rule_id)


async def create_scoring_rule(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    payload: LeadScoringRuleCreate,
) -> LeadScoringRule:
    _validate_scoring_condition(payload.condition)
    rule = LeadScoringRule(
        org_id=org_id,
        name=payload.name,
        condition=payload.condition,
        points=payload.points,
        active=payload.active,
    )
    _da.insert_scoring_rule(session, rule)
    await session.commit()
    await session.refresh(rule)

    scoring.invalidate_rule_field_cache(org_id)
    await log_entity_change(
        action="leads.scoring_rule.created",
        entity_type="lead_scoring_rule",
        entity_id=rule.id,
        after=_scoring_snapshot(rule),
    )
    return rule


async def update_scoring_rule(
    session: AsyncSession,
    *,
    rule_id: uuid.UUID,
    payload: LeadScoringRuleUpdate,
) -> LeadScoringRule:
    rule = ensure_found(await get_scoring_rule(session, rule_id=rule_id), entity="scoring rule")
    before = _scoring_snapshot(rule)
    changes = payload.model_dump(exclude_unset=True)
    if "condition" in changes and changes["condition"] is not None:
        _validate_scoring_condition(changes["condition"])
    for key, value in changes.items():
        setattr(rule, key, value)
    await session.commit()
    await session.refresh(rule)

    scoring.invalidate_rule_field_cache(rule.org_id)
    await log_entity_change(
        action="leads.scoring_rule.updated",
        entity_type="lead_scoring_rule",
        entity_id=rule.id,
        before=before,
        after=_scoring_snapshot(rule),
    )
    return rule


async def delete_scoring_rule(session: AsyncSession, *, rule_id: uuid.UUID) -> None:
    rule = ensure_found(await get_scoring_rule(session, rule_id=rule_id), entity="scoring rule")
    before = _scoring_snapshot(rule)
    org_id = rule.org_id
    rule_uuid = rule.id
    await _da.delete_scoring_rule_row(session, rule)
    await session.commit()

    scoring.invalidate_rule_field_cache(org_id)
    await log_entity_change(
        action="leads.scoring_rule.deleted",
        entity_type="lead_scoring_rule",
        entity_id=rule_uuid,
        before=before,
    )


# --- Pipeline value roll-up (F23) -----------------------------------------


async def pipeline_value_rollup(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    assigned_to: uuid.UUID | None,
) -> dict[str, Any]:
    """Header-strip roll-up: open pipeline value + this-month won/lost.

    Scope: when ``assigned_to`` is supplied, the roll-up sums only
    that user's leads (personal roll-up). When None, org-wide. Caller
    (router) decides which based on ``users.read`` — matches the same
    visibility rule as the list endpoint.

    Fires 4 folded aggregate queries in one round-trip via ``COUNT(*)
    FILTER (WHERE ...)`` / ``SUM(...) FILTER (WHERE ...)`` — same
    fold-per-table pattern the dashboard summary refactor established.
    """
    from calendar import monthrange
    from datetime import UTC, datetime

    from sqlalchemy import text

    from src.app.core.tenants.service import get_organization_by_id

    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    # Exclusive upper bound = first day of the next month.
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        month_end = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    _ = monthrange  # keep import; used implicitly by month math above

    params: dict[str, Any] = {
        "org_id": org_id,
        "month_start": month_start,
        "month_end": month_end,
    }
    scope_clause = ""
    if assigned_to is not None:
        scope_clause = " AND assigned_to_id = :assigned_to"
        params["assigned_to"] = assigned_to

    sql = text(
        f"""
        SELECT
          COALESCE(SUM(budget) FILTER (WHERE status = 'active'), 0) AS open_value,
          COUNT(*) FILTER (WHERE status = 'active') AS open_count,
          COALESCE(
            SUM(COALESCE(won_value, budget)) FILTER (
              WHERE status = 'won'
                AND won_at >= :month_start
                AND won_at <  :month_end
            ),
            0
          ) AS won_value_this_month,
          COUNT(*) FILTER (
            WHERE status = 'won'
              AND won_at >= :month_start
              AND won_at <  :month_end
          ) AS won_count_this_month,
          COUNT(*) FILTER (
            WHERE status = 'lost'
              AND lost_at >= :month_start
              AND lost_at <  :month_end
          ) AS lost_count_this_month
        FROM tbl_leads
        WHERE org_id = :org_id{scope_clause}
        """
    )
    row = (await session.execute(sql, params)).one()

    org = await get_organization_by_id(session, org_id)
    currency = org.currency if org is not None else "INR"

    return {
        "open_value": row.open_value or 0,
        "open_count": int(row.open_count or 0),
        "won_value_this_month": row.won_value_this_month or 0,
        "won_count_this_month": int(row.won_count_this_month or 0),
        "lost_count_this_month": int(row.lost_count_this_month or 0),
        "currency": currency,
    }


__all__ = [
    "bulk_delete_leads",
    "bulk_move_stage",
    "bulk_reassign_leads",
    "create_lead",
    "create_scoring_rule",
    "delete_lead",
    "delete_scoring_rule",
    "get_lead",
    "get_scoring_rule",
    "list_leads",
    "list_leads_where",
    "list_scoring_rules",
    "move_stage_for_lead",
    "pipeline_value_rollup",
    "reassign_lead",
    "update_lead",
    "update_scoring_rule",
]


# --- Bulk move-stage (F4) --------------------------------------------------


async def bulk_move_stage(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    to_stage: str,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    lost_reason: str | None = None,
    lost_reason_other: str | None = None,
    won_value: Any = None,
    close_date: Any = None,
    won_reason: str | None = None,
) -> int:
    """Move N leads to ``to_stage`` in one transaction. Returns rows
    actually touched (already-in-stage rows are silently skipped).

    Reuses ``move_stage_for_lead`` per row so the same status-sync +
    lifecycle-timestamp + audit-log semantics apply. Each per-row
    failure is surfaced as-is (422 for missing lost_reason on a Lost
    move, etc.) — bulk callers should validate the payload once at
    the modal and know every id will succeed or fail identically.
    """
    moved = 0
    for lid in ids:
        lead = await get_lead(session, lid)
        if lead is None or str(lead.org_id) != str(org_id):
            continue
        if lead.pipeline_stage == to_stage:
            continue
        await move_stage_for_lead(
            session,
            lead_id=lid,
            to_stage=to_stage,
            user_id=user_id,
            lost_reason=lost_reason,
            lost_reason_other=lost_reason_other,
            won_value=won_value,
            close_date=close_date,
            won_reason=won_reason,
        )
        moved += 1
    return moved
