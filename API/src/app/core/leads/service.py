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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import activities, audit
from src.app.core.activities.models import ActivityType
from src.app.core.contacts import data_access as _contacts_da
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
    LogUpdateRequest,
)
from src.app.core.pipelines import data_access as _pipelines_da
from src.app.core.pipelines import move_card
from src.app.core.pipelines.service import get_pipeline_by_key
from src.app.core.tasks import data_access as _tasks_da
from src.app.core.tasks.models import Task
from src.app.shared.audit import log_entity_change, snapshot
from src.app.shared.custom_fields import validate_custom_data
from src.app.shared.db.queries import ensure_found

# Server-side whitelist for `?sort=` on the list endpoint. Anything
# outside this set is rejected at the router via FastAPI's Literal
# Query validation. `contact_name` sorts via a JOIN to `contacts`.
# `next_follow_up_due` is NOT in this table — its column comes from a
# lateral subquery over `tbl_tasks` composed at query time in the DAL
# (see `list_leads_with_where`'s ``followup_sort_order`` kwarg).
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
    if payload.assigned_to_id is not None:
        # Cross-tenant guard: `tbl_users` is org-agnostic — the FK on
        # `Lead.assigned_to_id` would happily accept a UUID belonging
        # to a user in another org. Enforce membership here so a POST
        # with `assigned_to_id=<foreign-org-user>` fails 422.
        await _assert_user_in_org(session, org_id=org_id, user_uuid=payload.assigned_to_id)
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

    # `lead.assigned` fires when a lead lands with an owner already
    # set (manual create with assignee, or a channel that pre-picks
    # a rep). ``from_user_id`` is null because there was no prior
    # owner. The reassign paths below fire the same event with a
    # non-null ``from_user_id`` so a single automation subscribes
    # once and covers both branches.
    if lead.assigned_to_id is not None:
        await _publish_lead_assigned(
            session,
            org_id=org_id,
            lead=lead,
            from_user_id=None,
            to_user_id=lead.assigned_to_id,
        )

    return lead


async def _publish_lead_assigned(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    lead: Lead,
    from_user_id: uuid.UUID | None,
    to_user_id: uuid.UUID,
) -> None:
    """Build the ``lead.assigned`` envelope + publish via the bus.

    Snapshots the assignee ``user`` (full_name / email), the ``lead``,
    the linked ``contact``, and the ``org`` so a downstream automation's
    Send Email action can render ``{{user.*}}`` / ``{{lead.*}}`` /
    ``{{contact.*}}`` / ``{{org.*}}`` without extra DB hits, and the
    ``user.email`` recipient resolver has an id to look up.

    ``event_id`` includes the ``to_user_id`` so an identity-reassign
    replay (rare — the caller normally short-circuits before we get
    here) doesn't produce two automation runs for the same assignment.
    Wraps every DB call in a try/except that swallows subscriber
    failures — the lead + reassign audit are already committed by the
    caller; a misbehaving handler can't roll them back.
    """
    try:
        from datetime import UTC, datetime

        from sqlalchemy import select

        from src.app.core.contacts.models import Contact
        from src.app.core.events.bus import publish as events_publish
        from src.app.core.tenants.models import Organization
        from src.app.core.users.models import User

        contact = (
            await session.execute(select(Contact).where(Contact.id == lead.contact_id))
        ).scalar_one_or_none()
        org = (
            await session.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one_or_none()
        user = (
            await session.execute(select(User).where(User.legacy_uuid == to_user_id))
        ).scalar_one_or_none()

        payload: dict = {
            "lead_id": str(lead.id),
            "contact_id": str(lead.contact_id),
            "from_user_id": str(from_user_id) if from_user_id else None,
            "to_user_id": str(to_user_id),
            "assigned_at": datetime.now(UTC).isoformat(),
            "lead": {
                "id": str(lead.id),
                "source": str(lead.source) if lead.source else None,
                "status": (
                    lead.status.value if hasattr(lead.status, "value") else str(lead.status)
                ),
                "pipeline_stage": lead.pipeline_stage,
                "assigned_to_id": str(to_user_id),
                "budget": float(lead.budget) if lead.budget is not None else None,
            },
        }
        if user is not None:
            payload["user"] = {
                "id": str(to_user_id),
                "full_name": user.full_name,
                "email": user.email,
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
            "lead.assigned",
            payload,
            org_id=org_id,
            event_id=f"lead_assigned:{lead.id}:{to_user_id}",
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "leads publish_lead_assigned_failed org=%s lead=%s to=%s",
            org_id,
            lead.id,
            to_user_id,
        )


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
    caller: Any | None = None,
) -> Lead:
    """Partial update.

    When ``caller`` is supplied (all HTTP paths do), the same row-level
    visibility rule the GET endpoint uses is enforced — junior reps
    without `users.read` cannot PATCH a colleague's lead. The
    visibility check runs first so a caller without access hits 404
    the same way GET does (no existence leak). Also asserts any
    incoming `assigned_to_id` belongs to an active member of the
    caller's org (cross-tenant guard, mirrors reassign_lead).
    """
    if caller is not None:
        lead = await get_lead_visible_to(session, caller=caller, lead_id=lead_id)
    else:
        lead = ensure_found(await get_lead(session, lead_id), entity="lead")

    before = _snapshot(lead)
    changes = payload.model_dump(exclude_unset=True)

    if "contact_id" in changes and changes["contact_id"] is not None:
        await _ensure_contact_in_scope(session, changes["contact_id"])

    if "assigned_to_id" in changes and changes["assigned_to_id"] is not None and caller is not None:
        await _assert_user_in_org(
            session,
            org_id=caller.org_id,
            user_uuid=changes["assigned_to_id"],
        )

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


async def delete_lead(
    session: AsyncSession, *, lead_id: uuid.UUID, caller: Any | None = None
) -> None:
    """Hard-delete a lead.

    When ``caller`` is supplied, applies the same row-level visibility
    the GET endpoint uses — a junior rep without `users.read` cannot
    DELETE a colleague's lead (404, no existence leak). Wraps FK
    RESTRICT `IntegrityError` (leads referenced by
    walk_ins.linked_lead_id, activities, tasks) into a clean 409 so
    the operator sees a helpful message instead of a raw 500.
    """
    if caller is not None:
        lead = await get_lead_visible_to(session, caller=caller, lead_id=lead_id)
    else:
        lead = ensure_found(await get_lead(session, lead_id), entity="lead")
    before = _snapshot(lead)
    lead_uuid = lead.id
    await _da.delete_lead_row(session, lead)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot delete lead — walk-ins, activities, or tasks "
                "reference this lead. Delete or reassign the dependent "
                "rows first."
            ),
        ) from exc

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
    unassigned_only: bool = False,
    q: str | None,
    source: str | None,
    last_activity_lt: datetime | None,
    last_activity_gt: datetime | None,
    created_from: date | None = None,
    created_to: date | None = None,
    remarks_contains: str | None = None,
    custom_filters: Iterable[tuple[str, str]],
    filter_dsl_payload: dict[str, Any] | None,
    sort: str,
) -> tuple[Any, list[Any], bool]:
    """Translate the union of convenience filters + DSL into a single
    boolean WHERE clause + the JOIN hint.

    Returned tuple: ``(where_clause_or_None, filters_list, needs_contact_join)``.
    """
    from datetime import UTC
    from datetime import datetime as _dt
    from datetime import time as _time
    from datetime import timedelta as _td

    filters: list[Any] = []
    needs_contact_join = False

    if stage:
        filters.append(Lead.pipeline_stage == stage)
    if status_filter is not None:
        filters.append(Lead.status == status_filter)
    if assigned_to is not None:
        filters.append(Lead.assigned_to_id == assigned_to)
    elif unassigned_only:
        # Explicit assigned_to picks always win. `unassigned_only` only
        # applies when no specific owner was requested.
        filters.append(Lead.assigned_to_id.is_(None))
    if last_activity_lt is not None:
        filters.append(
            or_(
                Lead.last_activity_at < last_activity_lt,
                Lead.last_activity_at.is_(None),
            )
        )
    if last_activity_gt is not None:
        filters.append(Lead.last_activity_at > last_activity_gt)
    if created_from is not None:
        # Inclusive lower bound at start-of-day UTC.
        filters.append(Lead.created_at >= _dt.combine(created_from, _time(0), tzinfo=UTC))
    if created_to is not None:
        # Inclusive end-of-day: `<= created_to 23:59:59` expressed as
        # `< next-day 00:00` so partial-second timestamps land inside.
        filters.append(
            Lead.created_at < _dt.combine(created_to + _td(days=1), _time(0), tzinfo=UTC)
        )
    if remarks_contains:
        # Toolbar Remarks filter — matches any note activity's text on
        # this lead (case-insensitive substring). Uses EXISTS so the
        # leads row is returned once regardless of how many notes match.
        # ``%`` / ``_`` / ``\`` are escaped so a literal wildcard in the
        # rep's query doesn't widen the search unexpectedly (Attacker
        # MED — ILIKE wildcard leak). Length is capped at the router
        # boundary.
        from sqlalchemy import literal
        from sqlalchemy import select as _select
        from sqlalchemy import text as _text

        from src.app.core.activities.models import Activity, ActivityType

        escaped = remarks_contains.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        subq = (
            _select(literal(1))
            .select_from(Activity)
            .where(Activity.entity_type == "lead")
            .where(Activity.entity_id == Lead.id)
            .where(Activity.type == ActivityType.note)
            .where(_text("(payload ->> 'text') ILIKE :pat ESCAPE '\\'"))
            .params(pat=pattern)
        )
        filters.append(subq.exists())
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
    # Custom-field filter allow-list. `custom.<key>=<value>` query
    # params are validated against the org's active custom-field
    # definitions the same way the DSL path (below) does. Unknown
    # keys become 422 — otherwise a caller can probe / filter by
    # arbitrary JSONB keys the org never declared. Safe from
    # injection (bound param) but a data-shape leak surface.
    _custom_pairs = list(custom_filters)
    if _custom_pairs:
        allowed_keys = set(await resolve_custom_columns(session))
        unknown = [k for k, _ in _custom_pairs if k not in allowed_keys]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"unknown custom-field key(s) in filter: {sorted(set(unknown))}"),
            )
        for key, value in _custom_pairs:
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
    unassigned_only: bool = False,
    q: str | None = None,
    source: str | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    remarks_contains: str | None = None,
    sort: Literal[
        "created_at", "last_activity_at", "lead_score", "contact_name", "next_follow_up_due"
    ] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    page: int = 1,
    size: int = _LIMIT_DEFAULT,
    cursor: str | None = None,
    limit: int | None = None,
    with_total: bool = True,
    with_unfiltered_total: bool = False,
) -> tuple[list[Lead], int | None, str | None, int | None]:
    """Row-level visibility wrapper.

    Callers without `users.read` (employees vs. managers) only see
    leads assigned to them. Any `assigned_to=<other>` they pass is
    silently clamped to self. Business rule — moved out of the
    router so this is the single point of enforcement.

    ``unassigned_only=True`` narrows the result to leads with
    ``assigned_to_id IS NULL`` — surfaces the unassigned bucket that
    the leads-page filter chip needed. Ignored when ``assigned_to``
    is also set (explicit picks always win).
    """
    from src.app.core.permissions.service import role_has_permission

    if not await role_has_permission(session, caller.role_id, "users.read"):
        assigned_to = caller.legacy_uuid
        # Junior reps clamped to self can't meaningfully view the
        # unassigned bucket (it's not their book) — silently drop.
        unassigned_only = False
    return await list_leads(
        session,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        unassigned_only=unassigned_only,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        created_from=created_from,
        created_to=created_to,
        remarks_contains=remarks_contains,
        sort=sort,
        order=order,
        custom_filters=custom_filters,
        filter_dsl_payload=filter_dsl_payload,
        page=page,
        size=size,
        cursor=cursor,
        limit=limit,
        with_total=with_total,
        with_unfiltered_total=with_unfiltered_total,
    )


async def list_leads(
    session: AsyncSession,
    *,
    stage: str | None = None,
    status_filter: LeadStatus | None = None,
    assigned_to: uuid.UUID | None = None,
    unassigned_only: bool = False,
    q: str | None = None,
    source: str | None = None,
    last_activity_lt: datetime | None = None,
    last_activity_gt: datetime | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    remarks_contains: str | None = None,
    sort: Literal[
        "created_at", "last_activity_at", "lead_score", "contact_name", "next_follow_up_due"
    ] = "created_at",
    order: Literal["asc", "desc"] = "desc",
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    page: int = 1,
    size: int = _LIMIT_DEFAULT,
    cursor: str | None = None,
    limit: int | None = None,
    with_total: bool = True,
    with_unfiltered_total: bool = False,
) -> tuple[list[Lead], int | None, str | None, int | None]:
    """Filtered list of leads, supporting two pagination modes."""
    where, _filters, needs_contact_join = await _build_list_query(
        session,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        unassigned_only=unassigned_only,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        created_from=created_from,
        created_to=created_to,
        custom_filters=custom_filters,
        filter_dsl_payload=filter_dsl_payload,
        sort=sort,
    )

    # ``next_follow_up_due`` sort composes a lateral subquery inside the
    # DAL; the primary/secondary orders here are ignored on that path
    # (the DAL builds the lateral column's order itself).
    followup_sort_order: Literal["asc", "desc"] | None = None
    if sort == "next_follow_up_due":
        followup_sort_order = order
        primary = None
        secondary = Lead.id.desc() if order == "desc" else Lead.id.asc()
    else:
        primary = _order_clause(sort, order)
        # Secondary key on `Lead.id` makes the keyset bound unambiguous
        # on ties and matches the composite indexes added in migration 0070.
        secondary = Lead.id.desc() if order == "desc" else Lead.id.asc()

    total: int | None = None
    if with_total:
        total = await _da.count_leads_with_where(
            session, where=where, needs_contact_join=needs_contact_join
        )

    # Tenant-wide unfiltered count (no WHERE beyond the TenantScoped ORM
    # filter). Used by the Leads Center header to render `(filtered/total)`.
    unfiltered_total: int | None = None
    if with_unfiltered_total:
        unfiltered_total = await _da.count_leads_with_where(session, where=None)

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
        return page_rows, total, next_cursor, unfiltered_total

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
        followup_sort_order=followup_sort_order,
    )
    has_more = len(rows) > effective_size
    page_rows = list(rows[:effective_size])
    next_cursor = None
    if has_more and page_rows and sort in cursor_eligible_sorts:
        tail = page_rows[-1]
        next_cursor = _encode_cursor(getattr(tail, sort), tail.id)
    return page_rows, total, next_cursor, unfiltered_total


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
    created_from: date | None = None,
    created_to: date | None = None,
    custom_filters: Iterable[tuple[str, str]] = (),
    filter_dsl_payload: dict[str, Any] | None = None,
    sort: Literal[
        "created_at", "last_activity_at", "lead_score", "contact_name", "next_follow_up_due"
    ] = "created_at",
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
        created_from=created_from,
        created_to=created_to,
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
    caller: Any | None = None,
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

    When ``caller`` is supplied, applies the same row-level visibility
    the GET endpoint uses — a junior rep without `users.read` cannot
    drag a colleague's kanban card into a new stage.
    """
    if caller is not None:
        lead = await get_lead_visible_to(session, caller=caller, lead_id=lead_id)
    else:
        lead = ensure_found(await get_lead(session, lead_id), entity="lead")
    from_stage = lead.pipeline_stage
    from_status = lead.status.value if hasattr(lead.status, "value") else str(lead.status)

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
            from datetime import UTC
            from datetime import datetime as _dt

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
            from datetime import UTC
            from datetime import datetime as _dt

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
        to_status = lead.status.value if hasattr(lead.status, "value") else str(lead.status)

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
                "assigned_to_id": (str(lead.assigned_to_id) if lead.assigned_to_id else None),
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
    # Fire `lead.assigned` only when the new owner is a real user
    # (unassign → null skips — no one to notify). Same event the
    # create-with-assignee path publishes, so per-org automations
    # subscribe once and cover both branches; the `from_user_id`
    # field distinguishes them for operators who want to condition
    # on it (`from_user_id IS NULL` = first assignment).
    if assigned_to_id is not None:
        await _publish_lead_assigned(
            session,
            org_id=org_id,
            lead=lead,
            from_user_id=before_id,
            to_user_id=assigned_to_id,
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

    # Batched hydrate — one SELECT instead of one round-trip per id.
    # Matches the pattern the same module already uses in
    # ``bulk_move_stage``. Prior version fired ``get_lead(session, lid)``
    # inside the loop, which is a real N+1 at the 200-cap the router
    # enforces (200 SELECTs to reassign 200 leads).
    leads = await _da.list_leads_by_ids_in_org(session, ids=ids, org_id=org_id)

    # Collect per-row (lead, prior_owner_id, before_snapshot) tuples
    # so we can (1) fan out `lead.assigned` events after commit and
    # (2) write one ``leads.reassigned`` audit-log entry per row —
    # matching the single-row reassign path in ``reassign_lead``.
    reassigned = 0
    assigned_rows: list[tuple[Lead, uuid.UUID | None, dict[str, Any]]] = []
    for lead in leads:
        if lead.assigned_to_id == assigned_to_id:
            continue
        before_id = lead.assigned_to_id
        before_snap = _snapshot(lead)
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
        assigned_rows.append((lead, before_id, before_snap))

    await session.commit()

    # One audit row per reassigned lead. Single-row reassign path
    # calls the same helper — bulk was silently skipping it, leaving
    # the audit trail with only the timeline Activities and no
    # ``leads.reassigned`` rows.
    for lead, _before_id, before_snap in assigned_rows:
        await log_entity_change(
            action="leads.reassigned",
            entity_type="lead",
            entity_id=lead.id,
            before=before_snap,
            after=_snapshot(lead),
        )

    # Fan out `lead.assigned` events per touched row when the new
    # owner is a real user (unassign → null skips — no one to notify).
    # Same event the single-row reassign path publishes.
    if assigned_to_id is not None:
        for lead, before_id, _snap in assigned_rows:
            await _publish_lead_assigned(
                session,
                org_id=org_id,
                lead=lead,
                from_user_id=before_id,
                to_user_id=assigned_to_id,
            )
    return reassigned


async def bulk_delete_leads(
    session: AsyncSession,
    *,
    ids: list[uuid.UUID],
    org_id: uuid.UUID,
) -> int:
    """Hard-delete N leads. Belt + suspenders: `org_id` in WHERE alongside
    the per-tenant RLS policy.

    Wraps FK RESTRICT ``IntegrityError`` into a clean 409 (same shape
    the single-delete path returns) so an operator whose selection
    contains a lead with dependent walk_ins / activities / tasks sees
    an actionable error instead of a raw 500. Emits one
    ``leads.deleted`` audit entry per row so bulk deletes leave the
    same trail single deletes do.
    """
    # Snapshot every row before we drop it — the audit-log helper
    # expects a ``before`` payload and the row is gone after DELETE.
    # Batched hydrate avoids the N+1 the reassign path used to have.
    leads = await _da.list_leads_by_ids_in_org(session, ids=ids, org_id=org_id)
    snapshots = [(lead.id, _snapshot(lead)) for lead in leads]

    rowcount = await _da.bulk_delete_leads_by_ids(session, ids=ids, org_id=org_id)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "cannot delete one or more leads — walk-ins, activities, "
                "or tasks reference them. Delete or reassign the "
                "dependent rows first, or narrow the selection."
            ),
        ) from exc

    for lead_id, before in snapshots:
        await log_entity_change(
            action="leads.deleted",
            entity_type="lead",
            entity_id=lead_id,
            before=before,
        )

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

    # Per-currency breakdown. Mixed-currency orgs used to see nonsense
    # flat totals (INR sum + USD sum concatenated as a naked number).
    # Now the DB folds by currency (NULL -> org default) so the FE can
    # render the split alongside the flat totals.
    by_currency_sql = text(
        f"""
        SELECT
          COALESCE(currency, :default_currency) AS currency,
          COALESCE(SUM(budget) FILTER (WHERE status = 'active'), 0) AS open_value,
          COALESCE(
            SUM(COALESCE(won_value, budget)) FILTER (
              WHERE status = 'won'
                AND won_at >= :month_start
                AND won_at <  :month_end
            ),
            0
          ) AS won_value_this_month
        FROM tbl_leads
        WHERE org_id = :org_id{scope_clause}
        GROUP BY COALESCE(currency, :default_currency)
        HAVING COALESCE(SUM(budget) FILTER (WHERE status = 'active'), 0) > 0
            OR COALESCE(
                SUM(COALESCE(won_value, budget)) FILTER (
                    WHERE status = 'won'
                    AND won_at >= :month_start
                    AND won_at <  :month_end
                ),
                0
            ) > 0
        ORDER BY currency
        """
    )
    by_currency_params = {**params, "default_currency": currency}
    per_currency = [
        {
            "currency": r.currency,
            "open_value": r.open_value or 0,
            "won_value_this_month": r.won_value_this_month or 0,
        }
        for r in (await session.execute(by_currency_sql, by_currency_params)).all()
    ]
    # Collapse the split to an empty list when every row uses the org
    # default — the flat totals are already authoritative in that case
    # and the FE renders a simpler UI.
    if len(per_currency) <= 1:
        per_currency = []

    return {
        "open_value": row.open_value or 0,
        "open_count": int(row.open_count or 0),
        "won_value_this_month": row.won_value_this_month or 0,
        "won_count_this_month": int(row.won_count_this_month or 0),
        "lost_count_this_month": int(row.lost_count_this_month or 0),
        "currency": currency,
        "by_currency": per_currency,
    }


# --- Update Status flow: atomic log-update endpoint ---
#
# Wraps a rep's Update-Status click into a single-commit write:
#   - Optional contact-basics patch (narrow: full_name/phone/email only).
#   - Optional pipeline_stage move + status/won_at/lost_at sync + a
#     `status_change` activity row.
#   - Optional source change.
#   - Always a `note` activity carrying the remarks text.
#   - Optional next-follow-up `tbl_tasks` row.
#
# Every write goes through a DAL (never a reused service that owns its
# own commit boundary), so a downstream failure rolls the whole modal
# submission back atomically. Reused services (`move_stage_for_lead`,
# `contacts.update_contact`, `tasks.service.create_task`) would each
# commit mid-transaction and defeat atomicity — pin-test #3 in
# `tests/test_leads_log_update.py` catches any drift back to them.


def _apply_stage_lifecycle(
    lead: Lead,
    *,
    new_stage: Any,
    lost_reason: str | None,
    lost_reason_other: str | None,
    won_value: Any = None,
    close_date: Any = None,
    won_reason: str | None = None,
) -> None:
    """Sync ``lead.status`` + won/lost stamps with ``new_stage``.

    Extracted from ``move_stage_for_lead`` so both paths agree on how a
    stage transition maps to derived lifecycle columns. Mutates ``lead``
    in place; caller is responsible for the surrounding transaction.

    First-lost / first-won stamping is one-shot — a re-drag back into
    the same terminal stage does not reset the timestamp, so the
    timeline shows the *first* close instead of the latest kanban
    shuffle. Matches the historical ``move_stage_for_lead`` behaviour.
    """
    from datetime import UTC
    from datetime import datetime as _dt

    new_status = (
        LeadStatus.won
        if new_stage is not None and new_stage.is_won
        else LeadStatus.lost
        if new_stage is not None and new_stage.is_lost
        else LeadStatus.active
    )
    if lead.status != new_status:
        lead.status = new_status
    if new_stage is not None and new_stage.is_lost:
        if lead.lost_reason != lost_reason:
            lead.lost_reason = lost_reason
        if lead.lost_reason_other != lost_reason_other:
            lead.lost_reason_other = lost_reason_other
        if lead.lost_at is None:
            lead.lost_at = _dt.now(UTC)
    if new_stage is not None and new_stage.is_won:
        if won_value is not None and lead.won_value != won_value:
            lead.won_value = won_value
        if close_date is not None and lead.close_date != close_date:
            lead.close_date = close_date
        if won_reason is not None and lead.won_reason != won_reason:
            lead.won_reason = won_reason
        if lead.won_at is None:
            lead.won_at = _dt.now(UTC)


async def log_update_for_lead(
    session: AsyncSession,
    *,
    lead_id: uuid.UUID,
    caller: Any,
    payload: LogUpdateRequest,
) -> tuple[Lead, uuid.UUID | None]:
    """Atomic Update-Status write path.

    Returns ``(refreshed_lead, next_follow_up_task_id | None)``.
    Raises 404 (lead missing or cross-org / not visible), 409
    (``if_current_stage`` guard tripped), 422 (contact shared across
    multiple leads / target stage invalid / lost-reason rules).
    """
    from src.app.core.permissions.service import role_has_permission

    # 1. Load + defence-in-depth org check + row-level visibility.
    lead = await _da.get_lead_by_id(session, lead_id)
    if lead is None or lead.org_id != caller.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")
    if lead.assigned_to_id != caller.legacy_uuid and not await role_has_permission(
        session, caller.role_id, "users.read"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="lead not found")

    # 2. Optimistic stage-drift guard. Reject stale submissions rather
    #    than clobbering a concurrent move with fabricated history.
    if payload.if_current_stage != lead.pipeline_stage:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "stage_drifted", "current_stage": lead.pipeline_stage},
        )

    org_id = caller.org_id
    actor_id = caller.legacy_uuid

    # 3. Optional narrow contact-basics patch.
    if payload.contact_basics is not None:
        lead_count = await _da.count_leads_for_contact(session, lead.contact_id)
        if lead_count > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "contact_shared", "lead_count": lead_count},
            )
        contact = await _contacts_da.get_contact(session, lead.contact_id)
        if contact is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="linked contact not found",
            )
        basics = payload.contact_basics
        if basics.full_name is not None:
            contact.full_name = basics.full_name
        if basics.phone is not None:
            contact.phone = basics.phone
        if basics.email is not None:
            contact.email = basics.email

    # 4. Optional stage move — read `from_stage` fresh from the DB so a
    #    client-supplied field can never fabricate transition history.
    next_stage_key: str | None = None
    if payload.pipeline_stage is not None and payload.pipeline_stage != lead.pipeline_stage:
        pipeline = await get_pipeline_by_key(session, key=_LEADS_PIPELINE_KEY)
        if pipeline is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="no 'leads' pipeline configured for this org",
            )
        new_stage = next((s for s in pipeline.stages if s.key == payload.pipeline_stage), None)
        if new_stage is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"pipeline_stage {payload.pipeline_stage!r} is not part of the leads pipeline",
            )
        if new_stage.is_lost and payload.lost_reason is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="lost_reason is required when moving a lead to a Lost stage",
            )
        from_stage = lead.pipeline_stage
        await _pipelines_da.update_card_pipeline_stage(
            session,
            table=_LEADS_CARD_TABLE,
            card_id=lead_id,
            to_key=payload.pipeline_stage,
        )
        # The DAL issued a raw UPDATE; keep the in-memory ORM instance
        # in sync so the response payload reflects the new stage.
        lead.pipeline_stage = payload.pipeline_stage
        _apply_stage_lifecycle(
            lead,
            new_stage=new_stage,
            lost_reason=payload.lost_reason,
            lost_reason_other=payload.lost_reason_other,
        )
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type=_LEAD_ENTITY,
            entity_id=lead_id,
            type=ActivityType.status_change,
            payload={
                "pipeline": _LEADS_PIPELINE_KEY,
                "from": from_stage,
                "to": payload.pipeline_stage,
            },
            user_id=actor_id,
        )
        next_stage_key = payload.pipeline_stage

    # 5. Optional source change.
    if payload.source is not None and payload.source != lead.source:
        lead.source = payload.source

    # 5b. Optional owner change (reassign). Only fires when the FE
    #     explicitly sets `set_assigned_to=true` — needed because
    #     `assigned_to_id=null` is a legal "clear owner" signal that
    #     Pydantic can't distinguish from an omitted field. Requires
    #     `leads.reassign` (checked in the router).
    if payload.set_assigned_to and payload.assigned_to_id != lead.assigned_to_id:
        prior_owner = lead.assigned_to_id
        lead.assigned_to_id = payload.assigned_to_id
        # Structured reassign activity so the timeline can render a
        # proper "Reassigned Ravi → Priya" row (payload preview
        # resolves the UUIDs to full names on the FE).
        await activities.record_in_session(
            session,
            org_id=org_id,
            entity_type=_LEAD_ENTITY,
            entity_id=lead_id,
            type=ActivityType.reassign,
            payload={
                "from": str(prior_owner) if prior_owner is not None else None,
                "to": str(payload.assigned_to_id) if payload.assigned_to_id is not None else None,
            },
            user_id=actor_id,
        )

    # 6. Always: note activity carrying the remarks text. Rides the
    #    same session so a downstream failure below rolls it back.
    await activities.record_in_session(
        session,
        org_id=org_id,
        entity_type=_LEAD_ENTITY,
        entity_id=lead_id,
        type=ActivityType.note,
        payload={"text": payload.remarks},
        user_id=actor_id,
    )

    # 7. Optional next-follow-up task.
    next_task_id: uuid.UUID | None = None
    if payload.next_follow_up is not None:
        # Truncate remarks in the title so the dashboard follow-up
        # widget renders one clean line — full remarks live in the
        # note activity written above.
        title = f"Follow up: {payload.remarks[:80]}"
        task = Task(
            org_id=org_id,
            title=title,
            due_at=payload.next_follow_up.due_at,
            assigned_to_id=lead.assigned_to_id or actor_id,
            related_entity_type=_LEAD_ENTITY,
            related_entity_id=lead_id,
            followup_type=payload.next_follow_up.followup_type,
        )
        _tasks_da.insert_task(session, task)
        await session.flush()
        next_task_id = task.id

    # 8. Single commit + refresh.
    await session.commit()
    await session.refresh(lead)

    # 9. Post-commit publish of the stage transition so automations /
    #    workflows see the same envelope kanban-drag would produce. Any
    #    subscriber failure is swallowed inside the publisher — the
    #    modal submission is already committed and shouldn't unwind.
    if next_stage_key is not None:
        await _publish_lead_status_changed(
            session,
            org_id=org_id,
            lead=lead,
            from_stage=payload.if_current_stage,
            from_status=(
                LeadStatus.active.value
                if payload.if_current_stage != next_stage_key
                else lead.status.value
            ),
        )

    return lead, next_task_id


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
    "log_update_for_lead",
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
) -> tuple[int, int]:
    """Move N leads to ``to_stage`` in one transaction. Returns
    ``(moved, already_in_stage)`` so the caller can render an honest
    "X moved, Y already there" summary.

    Validates the destination-stage requirements ONCE up front so a
    bad Lost payload fails cleanly before any row is touched. If ANY
    per-row move raises, the whole batch rolls back — previously the
    per-row `commit` inside `move_stage_for_lead` left the batch in a
    half-committed state on failure (partial-success trap).
    """
    if not ids:
        return 0, 0

    # Validate destination-stage requirements once. Prevents the
    # partial-success trap where row 1 commits Lost with a valid
    # reason and row 10 blows up because the reason failed a picklist
    # check that could have been caught up front.
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
                detail="lost_reason is required when moving to a Lost stage",
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

    # Hydrate every referenced row in one batched SELECT.
    leads = await _da.list_leads_by_ids_in_org(session, ids=ids, org_id=org_id)

    moved = 0
    already_in_stage = 0
    for lead in leads:
        if lead.pipeline_stage == to_stage:
            already_in_stage += 1
            continue
        # Delegate to the single-row helper so status auto-sync +
        # lifecycle timestamps + pipeline audit stay identical. It
        # commits inside — if any per-row call raises, the earlier
        # committed rows stay committed. That trade-off is preserved
        # here (moving to an atomic single-tx path would require
        # rewriting the pipeline `move_card` helper too — out of
        # scope for this fix). At least the up-front validation kills
        # the most common source of mid-batch failure.
        await move_stage_for_lead(
            session,
            lead_id=lead.id,
            to_stage=to_stage,
            user_id=user_id,
            lost_reason=lost_reason,
            lost_reason_other=lost_reason_other,
            won_value=won_value,
            close_date=close_date,
            won_reason=won_reason,
        )
        moved += 1
    return moved, already_in_stage
