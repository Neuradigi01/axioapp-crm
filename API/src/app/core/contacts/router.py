"""HTTP routes for `contacts`.

Routes mounted under ``/api/v1/contacts``. Reads require
``contacts.read``; mutations require ``contacts.write``. Tenant scoping
is automatic via the ORM filter on `TenantScoped`.

  GET    /contacts              → paginated list, q/source/tag/custom.* filters
  POST   /contacts              → create
  GET    /contacts/{id}         → get one
  PATCH  /contacts/{id}         → partial update
  DELETE /contacts/{id}         → delete

The dynamic ``custom.<key>=<value>`` filter is parsed off
``Request.query_params`` because FastAPI's typed Query params don't
support arbitrary prefixed names.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.permissions.service import role_has_permission
from src.app.core.contacts.consent_service import (
    ConsentError,
    count_consent_events,
    list_consent_events,
    record_transition,
)
from src.app.core.contacts.data_export import build_contact_data_export
from src.app.core.contacts.schemas import (
    ConsentEventOut,
    ContactAnonymiseRequest,
    ContactBulkAddTag,
    ContactBulkAddTagResult,
    ContactBulkDelete,
    ContactBulkDeleteResult,
    ContactBulkReassign,
    ContactBulkReassignResult,
    ContactCreate,
    ContactDuplicateCheckResponse,
    ContactDuplicateMatch,
    ContactHydrateRequest,
    ContactListItem,
    ContactListResponse,
    ContactMergeRequest,
    ContactMergeResponse,
    ContactOut,
    ContactReassign,
    ContactUpdate,
    OptInHistoryOut,
    OptInRecordRequest,
    OptOutRecordRequest,
)
from src.app.core.contacts.service import (
    anonymise_contact,
    bulk_add_tag_contacts,
    bulk_delete_contacts,
    bulk_reassign_contacts,
    check_duplicate,
    create_contact,
    delete_contact,
    export_contacts_csv_rows,
    get_contact,
    hydrate_contacts_by_ids,
    list_contact_custom_field_defs,
    list_contacts,
    merge_contacts,
    reassign_contact,
    update_contact,
)
from src.app.core.tenants import service as tenants_service
from src.app.core.users.models import User
from src.app.shared.db import get_db

router = APIRouter(prefix="/contacts", tags=["Contacts"])

_CUSTOM_PREFIX = "custom."


def _extract_custom_filters(request: Request) -> list[tuple[str, str]]:
    """Pull every `custom.<key>=<value>` pair out of the query string."""
    out: list[tuple[str, str]] = []
    for raw_key, value in request.query_params.multi_items():
        if raw_key.startswith(_CUSTOM_PREFIX) and len(raw_key) > len(_CUSTOM_PREFIX):
            out.append((raw_key[len(_CUSTOM_PREFIX) :], value))
    return out


@router.get("", response_model=ContactListResponse)
async def list_contacts_endpoint(
    request: Request,
    q: str | None = Query(default=None, max_length=255),
    source: list[str] | None = Query(
        default=None,
        description=(
            "Filter by source. Repeat the param (`?source=X&source=Y`) "
            "to match any of several sources — the column-header filter "
            "popover sends this shape."
        ),
    ),
    tag: list[str] | None = Query(
        default=None,
        description="Filter by tag. Repeatable — OR-set semantics.",
    ),
    assigned_to_id: list[uuid.UUID] | None = Query(
        default=None,
        description="Filter by owner UUID. Repeatable — OR-set semantics.",
    ),
    exclude_anonymised: bool = Query(
        default=False,
        description=(
            "When true, anonymised (DPDP right-to-be-forgotten) contacts "
            "are excluded from the result. Used by pickers that must not "
            "offer wiped records as merge / link targets."
        ),
    ),
    sort: Literal["full_name", "created_at", "last_activity_at"] = Query(default="created_at"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> ContactListResponse:
    rows, total = await list_contacts(
        db,
        q=q,
        sources=source,
        tags=tag,
        assigned_to_ids=assigned_to_id,
        custom_filters=_extract_custom_filters(request),
        sort=sort,
        order=order,
        page=page,
        size=size,
        exclude_anonymised=exclude_anonymised,
    )
    return ContactListResponse(
        items=[ContactListItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def create_contact_endpoint(
    payload: ContactCreate,
    stub: bool = Query(
        default=False,
        description=(
            "Skip required-custom-field validation. Set from indirect "
            "create paths (e.g. the lead-form auto-create) where the "
            "operator can't reasonably know the contact's custom-field "
            "schema. Behaves the same as the widget / webhook ingest paths."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactOut:
    contact = await create_contact(
        db,
        org_id=user.org_id,
        payload=payload,
        require_all_required=not stub,
    )
    return ContactOut.model_validate(contact)


# Static GETs MUST precede `/{contact_id}` — FastAPI matches in
# registration order, so e.g. `/export.csv` would otherwise be parsed
# as a UUID and fail validation.


@router.get("/check-duplicate", response_model=ContactDuplicateCheckResponse)
async def check_duplicate_endpoint(
    phone: str | None = Query(default=None, max_length=32),
    email: str | None = Query(default=None, max_length=255),
    exclude_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.read")),
) -> ContactDuplicateCheckResponse:
    matches = await check_duplicate(
        db,
        org_id=user.org_id,
        phone=phone,
        email=email,
        exclude_id=exclude_id,
    )
    return ContactDuplicateCheckResponse(
        matches=[ContactDuplicateMatch.model_validate(m) for m in matches]
    )


@router.get("/export.csv")
async def export_csv_endpoint(
    request: Request,
    q: str | None = Query(default=None, max_length=255),
    source: list[str] | None = Query(default=None),
    tag: list[str] | None = Query(default=None),
    assigned_to_id: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.read")),
) -> StreamingResponse:
    """Stream the current filter as CSV. Capped at 50k rows server-side.

    Standard columns: id, full_name, phone, email, source, tags,
    assigned_to_id, last_activity_at, created_at, updated_at. Then
    one column per visible custom field, headed
    ``custom.<field_key>`` — the stable key rather than the label so
    downstream ETL doesn't break when an org renames a field.
    """
    rows = await export_contacts_csv_rows(
        db,
        q=q,
        sources=source,
        tags=tag,
        assigned_to_ids=assigned_to_id,
        custom_filters=_extract_custom_filters(request),
    )
    # Fetch every visible contact custom field for the org. Same order
    # the render endpoint uses so the CSV columns match the form layout
    # top-to-bottom.
    custom_defs = await list_contact_custom_field_defs(db)

    # Resolve org slug for the filename. Two reasons: (1) the user is
    # often signed into multiple orgs and the file is more useful when
    # named per-org; (2) keeps separate per-tenant exports from
    # colliding on disk.
    org = await tenants_service.get_organization_by_id(db, user.org_id)
    assert org is not None  # authed user implies their org exists

    # IST-anchored filename date. Mumbai / Bangalore operators pulling
    # an export at 04:00 IST would previously get yesterday's UTC date
    # in the filename — surprising and hard to search for later.
    IST = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(UTC).astimezone(IST).date().isoformat()
    filename = f"contacts-{org.slug}-{today}.csv"

    async def _stream() -> AsyncIterator[bytes]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        header = [
            "id",
            "full_name",
            "phone",
            "email",
            "source",
            "tags",
            "assigned_to_id",
            "last_activity_at",
            "created_at",
            "updated_at",
        ]
        header.extend(f"custom.{d.field_key}" for d in custom_defs)
        writer.writerow(header)
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()

        for c in rows:
            standard = [
                str(c.id),
                c.full_name,
                c.phone or "",
                c.email or "",
                c.source or "",
                "|".join(c.tags or []),
                str(c.assigned_to_id) if c.assigned_to_id else "",
                c.last_activity_at.isoformat() if c.last_activity_at else "",
                c.created_at.isoformat(),
                c.updated_at.isoformat(),
            ]
            custom_data = c.custom_data or {}
            standard.extend(
                _format_custom_value(custom_data.get(d.field_key)) for d in custom_defs
            )
            writer.writerow(standard)
            yield buf.getvalue().encode("utf-8")
            buf.seek(0)
            buf.truncate()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _format_custom_value(value: object) -> str:
    """Stringify a ``custom_data`` cell for CSV. Mirrors the frontend's
    ``formatValue``: lists join with ``, ``, booleans render as
    Yes/No, ``None`` becomes empty. Anything else falls back to
    ``str(...)`` — ISO dates come out as their JSON string, numbers as
    plain digits."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact_endpoint(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.read")),
) -> ContactOut:
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut)
async def update_contact_endpoint(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactOut:
    # Reassigning via the edit modal must not sidestep the dedicated
    # `contacts.reassign` gate. When the payload includes
    # `assigned_to_id`, additionally require `contacts.reassign`.
    # `exclude_unset=True` distinguishes "not sent" from "sent as null"
    # (the null case is an explicit unassign — still a reassign action).
    changes = payload.model_dump(exclude_unset=True)
    if "assigned_to_id" in changes:
        if not await role_has_permission(db, user.role_id, "contacts.reassign"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing permission(s): contacts.reassign",
            )
    contact = await update_contact(
        db,
        contact_id=contact_id,
        payload=payload,
        org_id=user.org_id,
    )
    return ContactOut.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact_endpoint(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permissions("contacts.write")),
) -> Response:
    await delete_contact(db, contact_id=contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Reassign + bulk-action endpoints ---------------------------------------


@router.post("/{contact_id}/reassign", response_model=ContactOut)
async def reassign_contact_endpoint(
    contact_id: uuid.UUID,
    payload: ContactReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.reassign")),
) -> ContactOut:
    contact = await reassign_contact(
        db,
        contact_id=contact_id,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return ContactOut.model_validate(contact)


@router.post("/{contact_id}/anonymise", response_model=ContactOut)
async def anonymise_contact_endpoint(
    contact_id: uuid.UUID,
    payload: ContactAnonymiseRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactOut:
    """DPDP right-to-be-forgotten. Wipes PII on the contact row +
    force-flips both consent channels to opted_out + stamps
    ``anonymised_at``. Historical FKs (activities, leads,
    appointments, invoices) are preserved so the audit trail stays
    intact. ``reason`` is persisted to the audit log for auditor
    trace; not stored on the anonymised row."""
    contact = await anonymise_contact(
        db,
        contact_id=contact_id,
        org_id=user.org_id,
        reason=payload.reason,
        actor_user_id=user.legacy_uuid,
    )
    return ContactOut.model_validate(contact)


@router.post("/{primary_id}/merge", response_model=ContactMergeResponse)
async def merge_contacts_endpoint(
    primary_id: uuid.UUID,
    payload: ContactMergeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactMergeResponse:
    """Fold ``payload.secondary_id`` into ``primary_id``, delete the
    secondary. Every cross-module row that referenced the secondary is
    repointed at the primary so history is preserved. See
    ``service.merge_contacts`` for the tag / custom_data merge rules
    and the full list of tables touched."""
    primary, rows_reassigned = await merge_contacts(
        db,
        primary_id=primary_id,
        secondary_id=payload.secondary_id,
        org_id=user.org_id,
    )
    return ContactMergeResponse(
        primary=ContactOut.model_validate(primary),
        secondary_id=payload.secondary_id,
        rows_reassigned=rows_reassigned,
    )


@router.post("/bulk-reassign", response_model=ContactBulkReassignResult)
async def bulk_reassign_endpoint(
    payload: ContactBulkReassign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.reassign")),
) -> ContactBulkReassignResult:
    n = await bulk_reassign_contacts(
        db,
        ids=payload.ids,
        org_id=user.org_id,
        assigned_to_id=payload.assigned_to_id,
        note=payload.note,
        actor_user_id=user.legacy_uuid,
    )
    return ContactBulkReassignResult(reassigned=n)


@router.post("/bulk-delete", response_model=ContactBulkDeleteResult)
async def bulk_delete_endpoint(
    payload: ContactBulkDelete,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactBulkDeleteResult:
    n = await bulk_delete_contacts(db, ids=payload.ids, org_id=user.org_id)
    return ContactBulkDeleteResult(deleted=n)


@router.post("/hydrate", response_model=list[ContactListItem])
async def hydrate_contacts_endpoint(
    payload: ContactHydrateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.read")),
) -> list[ContactListItem]:
    """Bulk-fetch `ContactListItem` shape for many ids in a single
    call. Collapses N per-row `GET /contacts/{id}` fan-outs from
    list pages (walk-ins, appointments, etc.) into one round-trip."""
    rows = await hydrate_contacts_by_ids(db, ids=payload.ids, org_id=user.org_id)
    return [ContactListItem.model_validate(r) for r in rows]


@router.post("/bulk-add-tag", response_model=ContactBulkAddTagResult)
async def bulk_add_tag_endpoint(
    payload: ContactBulkAddTag,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.write")),
) -> ContactBulkAddTagResult:
    n = await bulk_add_tag_contacts(db, ids=payload.ids, tag=payload.tag, org_id=user.org_id)
    return ContactBulkAddTagResult(updated=n)


# --- Opt-in (whatsapp-platform-upgrade Step 22) ----------------------------


def _client_ip(request: Request) -> str | None:
    """Best-effort client IP for the consent audit. Honours
    ``X-Forwarded-For`` when the API is behind a proxy; falls back
    to the socket address. Returns None when neither is available
    (e.g. tests using the ASGI direct adapter)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:64]
    client = request.client
    return client.host[:64] if client else None


@router.get(
    "/{contact_id}/data-export",
    summary="DPDP right-to-access — full data ZIP for one contact.",
)
async def export_contact_data_endpoint(
    contact_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.read")),
) -> Response:
    """Streams a ZIP archive with the contact's profile + consent
    log + leads + conversation transcripts. Anyone with
    `contacts.read` can trigger an export — DPDP §11(a) requires
    the data fiduciary to make this available; the server audits
    the download with the requester's user id.

    Internal operator notes (Step 13) are excluded from
    transcripts. Cross-tenant data is impossible — RLS scopes
    every query."""
    try:
        bundle = await build_contact_data_export(
            db,
            contact_id=contact_id,
            requested_by_user_id=user.legacy_uuid,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    from src.app.core import audit

    await audit.log(
        "contacts.data_exported",
        entity_type="contact",
        entity_id=contact_id,
        user_id=user.legacy_uuid,
        after=bundle.summary,
    )
    return Response(
        content=bundle.archive_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="{bundle.filename}"'),
        },
    )


@router.get(
    "/{contact_id}/opt-in",
    response_model=OptInHistoryOut,
    summary="Current opt-in state + immutable consent-log history",
)
async def get_opt_in_endpoint(
    contact_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("contacts.read")),
) -> OptInHistoryOut:
    """Read-only view of the opt-in surface for one contact. Read
    gate is the standard `contacts.read` — every staffer with
    access to the contact can see the consent state. Manual
    overrides are gated separately on `whatsapp.opt_in.manage`.

    `limit` / `offset` page through the consent events (200 max per
    call). `total_events` in the response tells the FE how many more
    exist so it can render an accurate "N more" pager.
    """
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    events = await list_consent_events(
        db, contact_id=contact_id, limit=limit, offset=offset
    )
    total = await count_consent_events(db, contact_id=contact_id)
    return OptInHistoryOut(
        contact_id=contact.id,
        status=contact.whatsapp_opt_in_status,
        source=contact.whatsapp_opt_in_source,
        recorded_at=contact.whatsapp_opt_in_recorded_at,
        recorded_by_user_id=contact.whatsapp_opt_in_recorded_by_user_id,
        opt_out_recorded_at=contact.whatsapp_opt_out_recorded_at,
        opt_out_reason=contact.whatsapp_opt_out_reason,
        events=[ConsentEventOut.model_validate(e) for e in events],
        total_events=total,
    )


@router.post(
    "/{contact_id}/opt-in",
    response_model=ConsentEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Manually record an opt-in (operator override).",
)
async def post_opt_in_endpoint(
    contact_id: uuid.UUID,
    payload: OptInRecordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.opt_in.manage")),
) -> ConsentEventOut:
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    try:
        result = await record_transition(
            db,
            contact=contact,
            new_status="opted_in",
            source=payload.source,
            actor_user_id=user.legacy_uuid,
            reason=payload.reason,
            request_evidence=payload.request_evidence,
            ip_address=_client_ip(request),
        )
    except ConsentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if not result.persisted:
        # Idempotent no-op — re-fetch the most recent event so the
        # caller still gets a meaningful row back instead of a 201
        # with stale data.
        recent = await list_consent_events(db, contact_id=contact_id, limit=1)
        if recent:
            return ConsentEventOut.model_validate(recent[0])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="contact is already opted in",
        )
    recent = await list_consent_events(db, contact_id=contact_id, limit=1)
    return ConsentEventOut.model_validate(recent[0])


@router.post(
    "/{contact_id}/opt-out",
    response_model=ConsentEventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Manually record an opt-out (operator override).",
)
async def post_opt_out_endpoint(
    contact_id: uuid.UUID,
    payload: OptOutRecordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("whatsapp.opt_in.manage")),
) -> ConsentEventOut:
    contact = await get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="contact not found")
    try:
        result = await record_transition(
            db,
            contact=contact,
            new_status="opted_out",
            source="manual_entry",
            actor_user_id=user.legacy_uuid,
            reason=payload.reason,
            request_evidence=payload.request_evidence,
            ip_address=_client_ip(request),
        )
    except ConsentError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    if not result.persisted:
        recent = await list_consent_events(db, contact_id=contact_id, limit=1)
        if recent:
            return ConsentEventOut.model_validate(recent[0])
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="contact is already opted out",
        )
    recent = await list_consent_events(db, contact_id=contact_id, limit=1)
    return ConsentEventOut.model_validate(recent[0])
