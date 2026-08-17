"""HTTP routes for the leads module.

  GET    /api/v1/leads                  → paginated list with filters
  POST   /api/v1/leads                  → create
  GET    /api/v1/leads/export.csv       → streaming CSV (filters apply)
  GET    /api/v1/leads/scoring-rules    → list scoring rules
  POST   /api/v1/leads/scoring-rules    → create scoring rule
  PATCH  /api/v1/leads/scoring-rules/{id}
  DELETE /api/v1/leads/scoring-rules/{id}
  POST   /api/v1/leads/scoring-rules/recompute  → bulk recompute scores
  GET    /api/v1/leads/{id}             → get one
  PATCH  /api/v1/leads/{id}             → partial update (NOT stage)
  DELETE /api/v1/leads/{id}
  POST   /api/v1/leads/{id}/move-stage  → kanban drag-drop endpoint

Reads gated by `leads.read`; writes (incl. move-stage) by `leads.write`.
CSV export is gated by `leads.export`; scoring-rule mutation by
`leads.scoring.manage`. The dynamic ``custom.<key>=<value>`` filter is
parsed off `Request.query_params` the same way the contacts router
handles it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.leads import scoring
from src.app.core.leads.csv_export import export_filename, export_rows
from src.app.core.leads.ingest import ingest as ingest_lead
from src.app.core.leads.models import LeadStatus
from src.app.core.leads.schemas import (
    LeadBulkDelete,
    LeadBulkDeleteResult,
    LeadBulkMoveStageRequest,
    LeadBulkMoveStageResult,
    LeadBulkReassign,
    LeadBulkReassignResult,
    LeadCreate,
    LeadIngestOut,
    LeadListResponse,
    LeadOut,
    LeadReassign,
    LeadScoringRecomputeResult,
    LeadScoringRuleCreate,
    LeadScoringRuleOut,
    LeadScoringRuleUpdate,
    LeadUpdate,
    LogUpdateRequest,
    LogUpdateResponse,
    MoveStageRequest,
    PipelineValueRollup,
)
from src.app.core.leads.service import (
    bulk_delete_leads,
    bulk_move_stage,
    bulk_reassign_leads,
    create_scoring_rule,
    delete_lead,
    delete_scoring_rule,
    get_lead,
    get_lead_visible_to,
    list_leads_visible_to,
    list_leads_where,
    list_scoring_rules,
    log_update_for_lead,
    move_stage_for_lead,
    pipeline_value_rollup,
    reassign_lead,
    update_lead,
    update_scoring_rule,
)
from src.app.core.permissions.service import role_has_permission
from src.app.core.settings.schemas import (
    LeadRoutingConfigOut,
    LeadRoutingConfigUpdate,
)
from src.app.core.settings.service import (
    get_or_create as get_or_create_settings,
)
from src.app.core.settings.service import (
    set_lead_routing_config,
)
from src.app.core.tenants.service import get_organization_by_id
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/leads", tags=["Leads"])

_CUSTOM_PREFIX = "custom."


def _extract_custom_filters(request: Request) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw_key, value in request.query_params.multi_items():
        if raw_key.startswith(_CUSTOM_PREFIX) and len(raw_key) > len(_CUSTOM_PREFIX):
            out.append((raw_key[len(_CUSTOM_PREFIX) :], value))
    return out


def _parse_filter_param(raw: str | None) -> dict[str, Any] | None:
    """Decode the URL-encoded JSON filter DSL from the ``filter`` query
    param. Malformed JSON is a 422 with a pointer; ``None``/empty
    string means "no DSL filter."""
    if raw is None or raw == "":
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"filter is not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="filter must be a JSON object",
        )
    return payload


@router.get("", response_model=LeadListResponse)
async def list_leads_endpoint(
    request: Request,
    stage: str | None = Query(default=None, max_length=64),
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    assigned_to: uuid.UUID | None = Query(default=None),
    unassigned_only: bool = Query(
        default=False,
        description=(
            "When true, only leads with `assigned_to_id IS NULL` are "
            "returned. Ignored when `assigned_to` is also set."
        ),
    ),
    q: str | None = Query(default=None, max_length=255),
    source: str | None = Query(default=None, max_length=64),
    last_activity_lt: datetime | None = Query(default=None),
    last_activity_gt: datetime | None = Query(default=None),
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = Query(
        default="created_at"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    # Offset mode (legacy callers): page + size.
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    # Cursor mode (Step 6 FE): cursor + limit. When ``cursor`` is set,
    # ``page`` is ignored. ``with_total`` controls whether the count
    # query runs; opt-out to skip it on large data sets.
    cursor: str | None = Query(default=None, max_length=512),
    limit: int | None = Query(default=None, ge=1, le=200),
    with_total: bool = Query(default=True),
    # Filter DSL: URL-encoded JSON object (see ``leads.filter_dsl``).
    filter_param: str | None = Query(default=None, alias="filter", max_length=4096),
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("leads.read")),
) -> LeadListResponse:
    filter_dsl_payload = _parse_filter_param(filter_param)
    rows, total, next_cursor = await list_leads_visible_to(
        db,
        caller=caller,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        unassigned_only=unassigned_only,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        sort=sort,
        order=order,
        custom_filters=_extract_custom_filters(request),
        filter_dsl_payload=filter_dsl_payload,
        page=page,
        size=size,
        cursor=cursor,
        limit=limit,
        with_total=with_total,
    )
    return LeadListResponse(
        items=[LeadOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=limit if cursor is not None and limit is not None else size,
        next_cursor=next_cursor,
    )


@router.post("", response_model=LeadIngestOut, status_code=status.HTTP_201_CREATED)
async def create_lead_endpoint(
    payload: LeadCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadIngestOut:
    """Manual lead creation. Routes through `leads.ingest.ingest()`
    so the dedup + round-robin assignment apply the same as for
    inbound channel ingestion (bulk import, widget, Google, Meta).

    If the picked contact already has an OPEN lead, the existing lead's
    timeline gets a "Touchpoint via manual" activity and we 201 back
    its id — no second lead is created. The response body carries
    ``ingest_action: "created" | "merged"`` so the UI can show a
    contextual "existing lead updated" toast instead of the generic
    "new lead created" one. The ``X-Lead-Ingest-Action`` header is
    still set for existing clients that were sniffing it, but new
    consumers should read the body — the header goes away eventually.
    """
    result = await ingest_lead(
        db,
        org_id=user.org_id,
        source=payload.source,
        contact_id=payload.contact_id,
        lead_payload=payload,
        actor_user_id=user.legacy_uuid,
    )
    lead = await get_lead(db, result.lead_id)
    response.headers["X-Lead-Ingest-Action"] = result.action
    response.headers["Access-Control-Expose-Headers"] = "X-Lead-Ingest-Action"
    return LeadIngestOut.model_validate(
        {**LeadOut.model_validate(lead).model_dump(), "ingest_action": result.action}
    )


# --- CSV export ---------------------------------------------------------
# Static path; registered BEFORE `/{lead_id}` so the UUID capture
# doesn't eat it.


@router.get("/export.csv")
async def export_leads_csv_endpoint(
    request: Request,
    stage: str | None = Query(default=None, max_length=64),
    status_filter: LeadStatus | None = Query(default=None, alias="status"),
    assigned_to: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    source: str | None = Query(default=None, max_length=64),
    last_activity_lt: datetime | None = Query(default=None),
    last_activity_gt: datetime | None = Query(default=None),
    sort: Literal["created_at", "last_activity_at", "lead_score", "contact_name"] = Query(
        default="created_at"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    filter_param: str | None = Query(default=None, alias="filter", max_length=4096),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.export")),
) -> StreamingResponse:
    """Stream the current filter as CSV. Capped at 50 000 rows.

    Columns: every lead-direct field + ``contact_name`` / ``phone`` /
    ``email`` from the joined contact + one column per active custom
    field definition for the org. Phone is Excel-safe-prefixed so
    spreadsheet apps don't strip the leading ``+`` and zeros.
    """
    filter_dsl_payload = _parse_filter_param(filter_param)
    where_clause, needs_join = await list_leads_where(
        db,
        stage=stage,
        status_filter=status_filter,
        assigned_to=assigned_to,
        q=q,
        source=source,
        last_activity_lt=last_activity_lt,
        last_activity_gt=last_activity_gt,
        custom_filters=_extract_custom_filters(request),
        filter_dsl_payload=filter_dsl_payload,
        sort=sort,
    )

    org = await get_organization_by_id(db, user.org_id)
    assert org is not None  # authed user implies their org exists
    filename = export_filename(org.slug)

    return StreamingResponse(
        export_rows(
            db,
            where_clause=where_clause,
            needs_contact_join=needs_join,
            sort=sort,
            order=order,
        ),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# --- Scoring rules CRUD -------------------------------------------------
# Static prefix; registered BEFORE `/{lead_id}` for the same reason.


@router.get("/scoring-rules", response_model=list[LeadScoringRuleOut])
async def list_scoring_rules_endpoint(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.scoring.manage")),
) -> list[LeadScoringRuleOut]:
    rules = await list_scoring_rules(db, org_id=_user.org_id)
    return [LeadScoringRuleOut.model_validate(r) for r in rules]


@router.post(
    "/scoring-rules",
    response_model=LeadScoringRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_scoring_rule_endpoint(
    payload: LeadScoringRuleCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.scoring.manage")),
) -> LeadScoringRuleOut:
    rule = await create_scoring_rule(db, org_id=user.org_id, payload=payload)
    return LeadScoringRuleOut.model_validate(rule)


@router.patch("/scoring-rules/{rule_id}", response_model=LeadScoringRuleOut)
async def update_scoring_rule_endpoint(
    rule_id: uuid.UUID,
    payload: LeadScoringRuleUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.scoring.manage")),
) -> LeadScoringRuleOut:
    rule = await update_scoring_rule(db, rule_id=rule_id, payload=payload)
    return LeadScoringRuleOut.model_validate(rule)


@router.delete("/scoring-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scoring_rule_endpoint(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("leads.scoring.manage")),
) -> Response:
    await delete_scoring_rule(db, rule_id=rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/scoring-rules/recompute", response_model=LeadScoringRecomputeResult)
async def recompute_scoring_rule_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.scoring.manage")),
) -> LeadScoringRecomputeResult:
    """Force a full org-wide recompute. Used by the Settings page's
    'Recompute scores now' action; otherwise the hourly Celery beat
    keeps everyone fresh."""
    touched = await scoring.recompute_org_scores(db, org_id=user.org_id)
    return LeadScoringRecomputeResult(touched=touched)


# --- Routing config (Step 6) --------------------------------------------
# Registered BEFORE `/{lead_id}` so static paths win over the UUID
# capture group — otherwise GET `/routing-config` would 422 on UUID
# parse failure for `lead_id="routing-config"`.


@router.get("/routing-config", response_model=LeadRoutingConfigOut)
async def get_routing_config_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.read")),
) -> LeadRoutingConfigOut:
    """Read the org's lead-routing configuration. v1 ships only
    `strategy="round_robin"` — the dedicated endpoint exists so the
    Settings UI can render a specialised chooser while leaving the
    generic /settings PATCH untouched (mutation goes through PUT
    below)."""
    row = await get_or_create_settings(db, org_id=user.org_id)
    cfg = row.lead_routing_config or {}
    return LeadRoutingConfigOut.model_validate(cfg)


@router.put("/routing-config", response_model=LeadRoutingConfigOut)
async def put_routing_config_endpoint(
    payload: LeadRoutingConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("settings.write")),
) -> LeadRoutingConfigOut:
    """Replace the org's routing config. v1 only accepts
    `strategy="round_robin"` (validated by the Literal type on
    `LeadRoutingConfigUpdate.strategy`); future strategies slot in
    here without an API break."""
    cfg = await set_lead_routing_config(db, org_id=user.org_id, payload=payload)
    return LeadRoutingConfigOut.model_validate(cfg)


@router.get("/pipeline-value", response_model=PipelineValueRollup)
async def pipeline_value_endpoint(
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("leads.read")),
) -> PipelineValueRollup:
    """Header-strip roll-up for the kanban / list view.

    Scope follows the same row-visibility rule as the list endpoint:
    callers with ``users.read`` see the whole org, everyone else sees
    only their own contribution."""
    is_org_scope = await role_has_permission(db, caller.role_id, "users.read")
    rollup = await pipeline_value_rollup(
        db,
        org_id=caller.org_id,
        assigned_to=None if is_org_scope else caller.legacy_uuid,
    )
    return PipelineValueRollup.model_validate(rollup)


@router.get("/{lead_id}", response_model=LeadOut)
async def get_lead_endpoint(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("leads.read")),
) -> LeadOut:
    lead = await get_lead_visible_to(db, caller=caller, lead_id=lead_id)
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead_endpoint(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("leads.write")),
) -> LeadOut:
    # Reassign gate: mirror the contacts / walk-ins fix — a PATCH that
    # includes `assigned_to_id` must also carry `leads.reassign`,
    # otherwise the edit modal is a side-door around the dedicated
    # reassign gate.
    changes = payload.model_dump(exclude_unset=True)
    if "assigned_to_id" in changes:
        if not await role_has_permission(db, caller.role_id, "leads.reassign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission(s): leads.reassign",
            )
    lead = await update_lead(
        db,
        lead_id=lead_id,
        payload=payload,
        caller=caller,
    )
    return LeadOut.model_validate(lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_endpoint(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    caller: User = Depends(require_permissions("leads.write")),
) -> Response:
    await delete_lead(db, lead_id=lead_id, caller=caller)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{lead_id}/move-stage", response_model=LeadOut)
async def move_lead_stage_endpoint(
    lead_id: uuid.UUID,
    payload: MoveStageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadOut:
    lead = await move_stage_for_lead(
        db,
        lead_id=lead_id,
        to_stage=payload.to_stage,
        user_id=user.legacy_uuid,
        lost_reason=payload.lost_reason,
        lost_reason_other=payload.lost_reason_other,
        won_value=payload.won_value,
        close_date=payload.close_date,
        won_reason=payload.won_reason,
        caller=user,
    )
    return LeadOut.model_validate(lead)


@router.post("/{lead_id}/log-update", response_model=LogUpdateResponse)
async def log_lead_update_endpoint(
    lead_id: uuid.UUID,
    payload: LogUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LogUpdateResponse:
    """Atomic Update-Status endpoint powering the modal.

    See ``log_update_for_lead`` for the write ordering. When
    ``contact_basics`` is supplied the caller must additionally hold
    ``contacts.write`` — the leads-write scope alone would otherwise
    become a side-door around the contacts-write permission gate.
    """
    if payload.contact_basics is not None:
        if not await role_has_permission(db, user.role_id, "contacts.write"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission(s): contacts.write",
            )
    lead, next_task_id = await log_update_for_lead(
        db,
        lead_id=lead_id,
        caller=user,
        payload=payload,
    )
    return LogUpdateResponse(
        lead=LeadOut.model_validate(lead),
        next_follow_up_task_id=next_task_id,
    )


# --- Reassign + bulk endpoints ----------------------------------------------


@router.post("/{lead_id}/reassign", response_model=LeadOut)
async def reassign_lead_endpoint(
    lead_id: uuid.UUID,
    payload: LeadReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.reassign")),
) -> LeadOut:
    lead = await reassign_lead(
        db,
        lead_id=lead_id,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return LeadOut.model_validate(lead)


@router.post("/bulk-reassign", response_model=LeadBulkReassignResult)
async def bulk_reassign_leads_endpoint(
    payload: LeadBulkReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.reassign")),
) -> LeadBulkReassignResult:
    n = await bulk_reassign_leads(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return LeadBulkReassignResult(reassigned=n)


@router.post("/bulk-delete", response_model=LeadBulkDeleteResult)
async def bulk_delete_leads_endpoint(
    payload: LeadBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadBulkDeleteResult:
    n = await bulk_delete_leads(db, ids=payload.ids, org_id=user.org_id)
    return LeadBulkDeleteResult(deleted=n)


# --- Bulk move-stage (F4) ---------------------------------------------------


@router.post("/bulk-move-stage", response_model=LeadBulkMoveStageResult)
async def bulk_move_stage_endpoint(
    payload: LeadBulkMoveStageRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("leads.write")),
) -> LeadBulkMoveStageResult:
    """Move ``payload.ids`` all to ``payload.to_stage`` in one call.

    Ids are capped at 200 by the schema (via `BulkIds`). Same
    validation rules as the single-row endpoint (Lost needs a reason;
    Won can carry optional value/close_date/reason). All rows in one
    bulk call get the same close metadata."""
    moved, already = await bulk_move_stage(
        db,
        ids=payload.ids,
        to_stage=payload.to_stage,
        org_id=user.org_id,
        user_id=user.legacy_uuid,
        lost_reason=payload.lost_reason,
        lost_reason_other=payload.lost_reason_other,
        won_value=payload.won_value,
        close_date=payload.close_date,
        won_reason=payload.won_reason,
    )
    return LeadBulkMoveStageResult(moved=moved, already_in_stage=already)
