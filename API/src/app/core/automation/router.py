"""HTTP routes for the automation engine.

Nine endpoints mounted under ``/api/v1/automations``:

  GET    /api/v1/automations/triggers                 — paginated list
  POST   /api/v1/automations/triggers                 — create
  GET    /api/v1/automations/triggers/{id}            — read
  PATCH  /api/v1/automations/triggers/{id}            — edit
  POST   /api/v1/automations/triggers/{id}/enable     — toggle on
  POST   /api/v1/automations/triggers/{id}/disable    — toggle off
  DELETE /api/v1/automations/triggers/{id}            — hard delete
  GET    /api/v1/automations/triggers/{id}/runs       — run history
  GET    /api/v1/automations/event-types              — discovery

Reads are gated on :data:`PERM_READ`; mutations on :data:`PERM_WRITE`.
Run-history is gated tighter on :data:`PERM_RUNS_READ` (payloads can
carry sensitive contact data). All error mapping flows through
``_automation_http_map`` so the operator sees consistent ``detail``
shapes: 404 / 409 / 422 cover :class:`TriggerNotFound`,
:class:`DuplicateTriggerName`, :class:`InvalidCondition` +
:class:`MissingTemplateForChannel`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.automation import data_access, event_catalog
from src.app.core.automation import service as automation_service
from src.app.core.automation.exceptions import (
    AutomationError,
    DuplicateTriggerName,
    FieldNotEnum,
    FieldNotFound,
    InvalidCondition,
    MissingTemplateForChannel,
    ResolverNotRegistered,
    TriggerNotFound,
)
from src.app.core.automation.field_specs import FieldType
from src.app.core.automation.models import AutomationRunStatus
from src.app.core.automation.permissions import (
    PERM_READ,
    PERM_RUNS_READ,
    PERM_WRITE,
)
from src.app.core.automation.schemas import (
    EnumOptionOut,
    FieldValuesRequest,
    PreviewMatchesRequest,
    PreviewMatchesResponse,
    RunRead,
    TriggerCreate,
    TriggerRead,
    TriggerUpdate,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.tenants.data_access import get_organization_by_id
from src.app.core.users.models import User
from src.app.shared.db import get_db


async def _org_template_id(db: AsyncSession, org_id: uuid.UUID) -> str | None:
    """Look up the caller org's installed-pack slug (``template_id``)
    once per request. Cached for the request via FastAPI's
    dependency-injection scope. Returns ``None`` for orgs without an
    installed pack — such orgs see only core events.
    """
    org = await get_organization_by_id(db, org_id)
    return org.template_id if org is not None else None


router = APIRouter(prefix="/automations", tags=["Automations"])


# --- response wrappers ----------------------------------------------


class TriggerListResponse(BaseModel):
    items: list[TriggerRead]
    total: int
    limit: int
    offset: int


class RunListResponse(BaseModel):
    items: list[RunRead]
    total: int
    limit: int
    offset: int


class FieldSpecOut(BaseModel):
    """Customer-friendly builder metadata for one filterable field
    on an event (``tasks/automation-conditions/`` Step 1).

    Values for ``enum`` fields are NOT included here — the frontend
    fetches them per-request via step-2's live resolver so a
    customer's dropdown always shows their org's actual pipeline
    stages / lead sources / users, not a hardcoded list.
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    label: str
    type: FieldType
    group: str
    enum_resolver: str | None = None
    help_text: str | None = None


class EventCatalogEntry(BaseModel):
    """Wire shape for the discovery endpoint — one row per event."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    label: str
    description: str
    sample_payload: dict
    condition_fields: list[FieldSpecOut] = []


# --- exception mapping ----------------------------------------------


def _automation_http_map(exc: AutomationError) -> HTTPException:
    if isinstance(exc, (TriggerNotFound, FieldNotFound)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, DuplicateTriggerName):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, (InvalidCondition, MissingTemplateForChannel, FieldNotEnum)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ResolverNotRegistered):
        # Code bug — pin-test should have caught it before deploy. 500
        # so ops notice; ``detail.code`` preserved for structured error.
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": str(exc)},
    )


# --- trigger CRUD ---------------------------------------------------


@router.get("/triggers", response_model=TriggerListResponse)
async def list_triggers_endpoint(
    event_type: str | None = Query(default=None, max_length=200),
    enabled: bool | None = Query(default=None),
    channel: ConversationChannel | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TriggerListResponse:
    rows, total = await automation_service.list_triggers(
        db,
        org_id=user.org_id,
        event_type=event_type,
        enabled=enabled,
        channel=channel,
        q=q,
        limit=limit,
        offset=offset,
    )
    return TriggerListResponse(
        items=[TriggerRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/triggers",
    response_model=TriggerRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_trigger_endpoint(
    payload: TriggerCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.create_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.get("/triggers/{trigger_id}", response_model=TriggerRead)
async def get_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TriggerRead:
    try:
        trigger = await automation_service.get_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.patch("/triggers/{trigger_id}", response_model=TriggerRead)
async def update_trigger_endpoint(
    trigger_id: uuid.UUID,
    payload: TriggerUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.update_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
            payload=payload,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.post("/triggers/{trigger_id}/enable", response_model=TriggerRead)
async def enable_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.enable_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.post("/triggers/{trigger_id}/disable", response_model=TriggerRead)
async def disable_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TriggerRead:
    try:
        trigger = await automation_service.disable_trigger(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            trigger_id=trigger_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return TriggerRead.model_validate(trigger)


@router.delete(
    "/triggers/{trigger_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_trigger_endpoint(
    trigger_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    try:
        await automation_service.delete_trigger(db, org_id=user.org_id, trigger_id=trigger_id)
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- run history ----------------------------------------------------


@router.get("/triggers/{trigger_id}/runs", response_model=RunListResponse)
async def list_runs_endpoint(
    trigger_id: uuid.UUID,
    run_status: AutomationRunStatus | None = Query(default=None, alias="status"),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_RUNS_READ)),
) -> RunListResponse:
    """Per-trigger run history. ``status`` query param uses
    :class:`AutomationRunStatus`; ``since`` is an ISO-8601 timestamp
    (e.g. ``2026-06-26T00:00:00Z``). The endpoint refuses unknown
    trigger ids with 404 — RLS-scoped lookup."""
    try:
        # Confirm the trigger exists in this org (RLS + 404 mapping).
        await automation_service.get_trigger(db, org_id=user.org_id, trigger_id=trigger_id)
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    rows, total = await data_access.list_runs(
        db,
        org_id=user.org_id,
        trigger_id=trigger_id,
        status=run_status,
        since=since,
        limit=limit,
        offset=offset,
    )
    return RunListResponse(
        items=[RunRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# --- event discovery ------------------------------------------------


@router.get("/event-types", response_model=list[EventCatalogEntry])
async def list_event_types_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> list[EventCatalogEntry]:
    """Discovery catalog — feeds the trigger editor's event picker,
    the variable-hint side panel, and the customer-friendly
    condition builder's field dropdown.

    Per event, ``condition_fields`` is the base catalog's spec list
    (code-owned per step-1) plus the caller org's custom fields for
    every entity the event mounts a ``custom_data`` on (step-6).
    Response is filtered to the caller org's installed pack
    (step-7) — core events + only-this-org's-pack events.
    Runs a single batched SQL round-trip to pull all
    ``tbl_custom_field_definitions`` rows across every mounted
    entity type in one shot, plus a tiny org lookup for the
    template_id gate.
    """
    template_id = await _org_template_id(db, user.org_id)
    entries = await automation_service.list_event_types_with_custom_fields(
        db, org_id=user.org_id, template_id=template_id
    )
    return [
        EventCatalogEntry(
            event_type=entry["event_type"],
            label=entry["label"],
            description=entry["description"],
            sample_payload=entry["sample_payload"],
            condition_fields=[
                FieldSpecOut(
                    path=spec.path,
                    label=spec.label,
                    type=spec.type,
                    group=spec.group,
                    enum_resolver=spec.enum_resolver,
                    help_text=spec.help_text,
                )
                for spec in entry["condition_fields"]
            ],
        )
        for entry in entries
    ]


@router.post(
    "/event-types/{event_type}/field-values",
    response_model=list[EnumOptionOut],
)
async def list_field_values_endpoint(
    event_type: str,
    payload: FieldValuesRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> list[EnumOptionOut]:
    """Return the caller org's live options for one enum-typed field
    on one event (``tasks/automation-conditions/`` Step 2).

    Fires from the condition builder whenever the customer picks a
    new enum field in the "Only if" dropdown — the frontend uses
    the response to populate the Value dropdown with the org's
    actual pipeline stages / lead sources / users / etc.

    Empty list is a valid response (org hasn't configured any
    values yet — frontend renders the "no options" hint). 404 when
    the event or field isn't in the catalog; 422 when the field
    isn't of enum type.
    """
    # Fast 404 when the event isn't in the catalog OR isn't visible
    # to the caller's installed pack (step-7). Same status code on
    # purpose — the endpoint leaks nothing about pack existence to
    # non-installers.
    template_id = await _org_template_id(db, user.org_id)
    entry = event_catalog.get_entry(event_type)
    if entry is None or not event_catalog.is_visible_to(entry, template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "automation.event_not_found",
                "message": f"event type {event_type!r} is not in the catalog",
            },
        )
    try:
        options = await automation_service.list_field_values(
            db,
            org_id=user.org_id,
            event_type=event_type,
            field=payload.field,
            template_id=template_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    # Small private cache so repeat picks of the same field across
    # editor tabs don't re-hit the resolver — pool values change
    # rarely (adding a pipeline stage is a Settings action). The
    # frontend also caches in-session (step-3).
    response.headers["Cache-Control"] = "private, max-age=60"
    return [EnumOptionOut(value=o.value, label=o.label) for o in options]


@router.post(
    "/event-types/{event_type}/preview-matches",
    response_model=PreviewMatchesResponse,
)
async def preview_matches_endpoint(
    event_type: str,
    payload: PreviewMatchesRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> PreviewMatchesResponse:
    """Preview how many historical events in the last ``window_days``
    would match the customer's draft condition — informational only,
    no dispatch, no side effects (``tasks/automation-conditions/``
    Step 5).

    Fires from the condition builder on a 500 ms debounce as the
    operator authors. Response drives the "This condition would have
    matched N events in the last 7 days" line under the sentence
    preview. Zero matches / no historical data / truncated scans
    each get a distinct render on the frontend so the customer knows
    whether their filter is too tight vs. the org just hasn't logged
    any events yet.
    """
    template_id = await _org_template_id(db, user.org_id)
    entry = event_catalog.get_entry(event_type)
    if entry is None or not event_catalog.is_visible_to(entry, template_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "automation.event_not_found",
                "message": f"event type {event_type!r} is not in the catalog",
            },
        )
    try:
        result = await automation_service.preview_matches(
            db,
            org_id=user.org_id,
            event_type=event_type,
            conditions_ast=payload.conditions,
            window_days=payload.window_days,
            template_id=template_id,
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    # Short cache — the operator is actively authoring, so a stale
    # count from 60s ago would be misleading. 15s is enough to
    # deduplicate the debounce burst on a fast typer without
    # hiding fresh runs from a manual test dispatch.
    response.headers["Cache-Control"] = "private, max-age=15"
    return PreviewMatchesResponse(**result)


# --- per-contact run list + retry + run-now (Step 9) ---------------


@router.get("/runs", response_model=RunListResponse)
async def list_runs_by_filters_endpoint(
    contact_id: uuid.UUID | None = Query(default=None),
    trigger_id: uuid.UUID | None = Query(default=None),
    run_status: AutomationRunStatus | None = Query(default=None, alias="status"),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_RUNS_READ)),
) -> RunListResponse:
    """Step 9 — general run-history filter. Drives the per-contact
    "Automations" tab on the contact detail page (callers pass
    ``contact_id``) + future cross-trigger admin views. Gated on
    the same `automations.runs.read` permission as the per-trigger
    run list."""
    rows, total = await data_access.list_runs(
        db,
        org_id=user.org_id,
        trigger_id=trigger_id,
        contact_id=contact_id,
        status=run_status,
        since=since,
        limit=limit,
        offset=offset,
    )
    return RunListResponse(
        items=[RunRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/runs/{run_id}/retry", response_model=RunRead)
async def retry_run_endpoint(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> RunRead:
    """Step 9 — re-queue a failed run via the same Celery task path.
    Refuses anything other than `status='failed'`:

    * ``queued`` / ``dispatched`` → 409 (already in flight).
    * ``sent`` → 409 (no-op; use Run-now for a fresh send).
    * ``skipped`` → 409 (the dispatcher decided this one shouldn't
      fire — operator should fix the root cause + use Run-now).
    """
    from datetime import datetime as _dt

    from src.app.core.automation import tasks as automation_tasks
    from src.app.core.automation.models import AutomationRunStatus

    run = await data_access.get_run(db, org_id=user.org_id, run_id=run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found",
        )
    if run.status != AutomationRunStatus.failed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "automation.run_not_retryable",
                "message": (f"only failed runs can be retried (this one is '{run.status.value}')"),
            },
        )

    # Reset for the next dispatch — clear the failure markers + flip
    # back to queued so the deliver_run task picks it up on Celery.
    run.status = AutomationRunStatus.queued
    run.error = None
    run.dispatched_at = None
    run.completed_at = None
    run.channel_message_id = None
    run.scheduled_at = _dt.now(UTC)
    await db.commit()
    await db.refresh(run)

    automation_tasks.deliver_run.apply_async(args=(str(run.id),), countdown=0)

    return RunRead.model_validate(run)


class RunNowPayload(BaseModel):
    """Body for ``POST /triggers/{id}/run-now``."""

    model_config = ConfigDict(extra="forbid")

    payload: dict


@router.post("/triggers/{trigger_id}/run-now", response_model=RunRead)
async def run_now_endpoint(
    trigger_id: uuid.UUID,
    payload: RunNowPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> RunRead:
    """Step 9 — manual fire for a saved trigger.

    Routes through the standard dispatcher (so conditions DO still
    evaluate + the recipient resolver runs); writes a fresh run row
    with a synthetic ``event_id=manual:{trigger_id}:{uuid}`` so it
    doesn't collide with real events on the
    ``(trigger_id, event_id)`` uniqueness check.

    Returns 409 if the payload doesn't satisfy the trigger's
    conditions — the operator should either adjust the payload OR
    use the trigger editor's Save & Test (dry-run) modal first to
    iterate without writing run rows.
    """
    from src.app.core.automation import dispatcher

    try:
        trigger = await automation_service.get_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    manual_event_id = f"manual:{trigger_id}:{uuid.uuid4()}"

    runs = await dispatcher.dispatch_event(
        db,
        org_id=user.org_id,
        event_type=trigger.event_type,
        payload=payload.payload,
        event_id=manual_event_id,
    )
    target = next((r for r in runs if r.trigger_id == trigger.id), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "automation.run_now_no_match",
                "message": (
                    "trigger conditions did not match the supplied "
                    "payload — adjust the payload or the trigger's "
                    "conditions"
                ),
            },
        )
    return RunRead.model_validate(target)


# --- dry-run (Step 8) ----------------------------------------------


class DryRunPayload(BaseModel):
    """Body for ``POST /triggers/{id}/dry-run``."""

    model_config = ConfigDict(extra="forbid")

    payload: dict


class DryRunResult(BaseModel):
    """Wire shape the editor's Save & Test modal renders."""

    model_config = ConfigDict(extra="forbid")

    would_match: bool
    skip_reason: str | None = None
    would_send_to: str | None = None
    rendered_subject: str | None = None
    rendered_body: str | None = None


@router.post("/triggers/{trigger_id}/dry-run", response_model=DryRunResult)
async def dry_run_endpoint(
    trigger_id: uuid.UUID,
    payload: DryRunPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> DryRunResult:
    """Step 8 — run the dispatcher path against the supplied payload
    WITHOUT inserting a run row or sending a real message. Returns
    the match decision + the would-be recipient + the rendered
    subject/body so the editor's Save & Test modal can show the
    operator exactly what would happen.

    Same compliance gates as the live path are NOT applied here —
    operators see the un-gated render so they can verify the
    template variables resolve correctly; Step 13's compliance
    enforcement only matters at real-send time."""
    from src.app.core.automation import conditions, recipients
    from src.app.core.templates import data_access as templates_da
    from src.app.core.templates.variables import resolve as render_variables

    try:
        trigger = await automation_service.get_trigger(
            db, org_id=user.org_id, trigger_id=trigger_id
        )
    except AutomationError as exc:
        raise _automation_http_map(exc) from exc

    # 1. Condition evaluation — same evaluator the matcher uses.
    matches = conditions.evaluate(trigger.conditions, payload.payload)
    if not matches:
        return DryRunResult(
            would_match=False,
            skip_reason="condition_failed",
        )

    # 2. Recipient resolution.
    try:
        recipient = await recipients.resolve(
            trigger.recipient_resolver,
            db,
            payload=payload.payload,
            config=trigger.recipient_resolver_config or {},
        )
    except recipients.UnknownResolver:
        return DryRunResult(
            would_match=True,
            skip_reason="unknown_resolver",
        )
    if not recipient:
        return DryRunResult(
            would_match=True,
            skip_reason="no_recipient",
        )

    # 3. Template render.
    template = await templates_da.get_template(
        db, org_id=user.org_id, template_id=trigger.template_id
    )
    if template is None:
        return DryRunResult(
            would_match=True,
            would_send_to=recipient,
            skip_reason="template_missing",
        )

    rendered_body = render_variables(template.body_text, payload.payload)
    rendered_subject = (
        render_variables(template.subject, payload.payload) if template.subject else None
    )

    return DryRunResult(
        would_match=True,
        would_send_to=recipient,
        rendered_subject=rendered_subject,
        rendered_body=rendered_body,
    )


__all__ = ["router"]
