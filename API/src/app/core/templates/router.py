"""HTTP routes for the central template library.

Nine endpoints, all mounted under ``/api/v1/templates``:

  GET    /api/v1/templates                          — paginated list
  POST   /api/v1/templates                          — create draft
  GET    /api/v1/templates/{id}                     — read
  PATCH  /api/v1/templates/{id}                     — edit draft (new version)
  DELETE /api/v1/templates/{id}                     — soft-archive
  GET    /api/v1/templates/{id}/versions            — version list
  GET    /api/v1/templates/{id}/versions/{version}  — read a past version
  POST   /api/v1/templates/{id}/preview             — render with sample context
  GET    /api/v1/templates/variables/{channel}      — variable picker registry

Reads are gated on :data:`PERM_READ`; mutations (create / patch /
archive) on :data:`PERM_WRITE`. Review / publish / external-submit
endpoints come online in Steps 4 + 9; they belong to the same module
but aren't wired here so the router stays under the Rule-8 size limit.

The variable-picker endpoint is the editor's source of truth (Step
7's UI loads it once per editor open). The list is static per
channel, so the response is small + cacheable.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.auth.dependencies import require_permissions
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import external_submission as templates_external
from src.app.core.templates import service as templates_service
from src.app.core.templates import test_send as templates_test_send
from src.app.core.templates import workflow as templates_workflow
from src.app.core.templates.exceptions import (
    DuplicateTemplateName,
    InvalidRecipient,
    InvalidWorkflowTransition,
    PublishBlockedByExternal,
    SelfApproveBlocked,
    TemplateError,
    TemplateLocked,
    TemplateNotFound,
    TestSendNotSupported,
)
from src.app.core.templates.external_submission import (
    ExternalSubmissionNotSupported,
    MissingExtensionRow,
)
from src.app.core.templates.models import (
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.permissions import (
    PERM_PUBLISH,
    PERM_READ,
    PERM_REVIEW,
    PERM_SUBMIT_EXTERNAL,
    PERM_WRITE,
)
from src.app.core.templates.schemas import (
    TemplateCreate,
    TemplateRead,
    TemplateReviewRead,
    TemplateTestSendRead,
    TemplateUpdate,
    TemplateVersionRead,
    TestSendPayload,
    WorkflowActionPayload,
)
from src.app.core.templates.variables import (
    VariableDef,
    resolve,
    variables_for_channel,
)
from src.app.core.users.models import User
from src.app.shared.db import get_db


router = APIRouter(prefix="/templates", tags=["Templates"])


# --- response wrappers -------------------------------------------------


class TemplateListResponse(BaseModel):
    """Paginated list response."""

    items: list[TemplateRead]
    total: int
    limit: int
    offset: int


class PreviewRequest(BaseModel):
    """Body for ``POST /templates/{id}/preview``.

    ``context`` is a nested dict matching the variable namespace shape
    (``{"contact": {"first_name": "Asha"}, "org": {"name": "Acme"}}``).
    Missing paths render as empty string per :func:`resolve` semantics
    — preview never raises on missing data, so the operator sees what
    the customer would see when the template runs against a partial
    payload.
    """

    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    """Rendered preview returned by ``POST /templates/{id}/preview``."""

    subject: Optional[str] = None
    body: str


class VariableDefOut(BaseModel):
    """Wire shape for one row in the variable picker."""

    key: str
    label: str
    type: str
    required: bool
    default: Optional[str] = None


# --- helpers -----------------------------------------------------------


def _to_variable_out(defn: VariableDef) -> VariableDefOut:
    return VariableDefOut(
        key=defn.key,
        label=defn.label,
        type=defn.type.value,
        required=defn.required,
        default=defn.default,
    )


# --- endpoints ---------------------------------------------------------


@router.get("", response_model=TemplateListResponse)
async def list_endpoint(
    channel: Optional[ConversationChannel] = Query(default=None),
    internal_status: Optional[TemplateInternalStatus] = Query(default=None),
    external_status: Optional[TemplateExternalStatus] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateListResponse:
    rows, total = await templates_service.list_templates(
        db,
        org_id=user.org_id,
        channel=channel,
        internal_status=internal_status,
        external_status=external_status,
        q=q,
        limit=limit,
        offset=offset,
    )
    return TemplateListResponse(
        items=[TemplateRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=TemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_endpoint(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    try:
        template = await templates_service.create_template(
            db,
            org_id=user.org_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except DuplicateTemplateName as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TemplateRead.model_validate(template)


@router.get("/variables/{channel}", response_model=list[VariableDefOut])
async def variables_endpoint(
    channel: ConversationChannel,
    _user: User = Depends(require_permissions(PERM_READ)),
) -> list[VariableDefOut]:
    """Variable picker registry for the chosen channel. Static — the
    editor (Step 7) calls this once per open. No DB hit."""
    return [_to_variable_out(v) for v in variables_for_channel(channel)]


@router.get("/{template_id}", response_model=TemplateRead)
async def get_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateRead:
    try:
        template = await templates_service.get_template(
            db, org_id=user.org_id, template_id=template_id
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return TemplateRead.model_validate(template)


@router.patch("/{template_id}", response_model=TemplateRead)
async def update_endpoint(
    template_id: uuid.UUID,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    try:
        template = await templates_service.update_template(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            payload=payload,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    except TemplateLocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        # Channel-coherence errors (subject on a non-email template).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return TemplateRead.model_validate(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> Response:
    try:
        await templates_service.archive_template(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{template_id}/versions",
    response_model=list[TemplateVersionRead],
)
async def list_versions_endpoint(
    template_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> list[TemplateVersionRead]:
    try:
        rows = await templates_service.list_versions(
            db,
            org_id=user.org_id,
            template_id=template_id,
            limit=limit,
            offset=offset,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return [TemplateVersionRead.model_validate(r) for r in rows]


@router.get(
    "/{template_id}/versions/{version}",
    response_model=TemplateVersionRead,
)
async def get_version_endpoint(
    template_id: uuid.UUID,
    version: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> TemplateVersionRead:
    try:
        row = await templates_service.get_version(
            db,
            org_id=user.org_id,
            template_id=template_id,
            version=version,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template version not found",
        ) from exc
    return TemplateVersionRead.model_validate(row)


# --- workflow transitions ---------------------------------------------


def _workflow_http_map(exc: TemplateError) -> HTTPException:
    """Translate workflow exceptions into FastAPI HTTPException."""
    if isinstance(exc, TemplateNotFound):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        )
    if isinstance(
        exc,
        (InvalidWorkflowTransition, SelfApproveBlocked, PublishBlockedByExternal),
    ):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    # Generic note-required / other TemplateError → 422.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.post("/{template_id}/submit", response_model=TemplateRead)
async def submit_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload = WorkflowActionPayload(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    try:
        template = await templates_workflow.submit_for_review(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


@router.post("/{template_id}/approve", response_model=TemplateRead)
async def approve_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload = WorkflowActionPayload(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_REVIEW)),
) -> TemplateRead:
    try:
        template = await templates_workflow.approve(
            db,
            org_id=user.org_id,
            template_id=template_id,
            reviewer_user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


@router.post("/{template_id}/reject", response_model=TemplateRead)
async def reject_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_REVIEW)),
) -> TemplateRead:
    if not payload.note or not payload.note.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="note is required when rejecting a template",
        )
    try:
        template = await templates_workflow.reject(
            db,
            org_id=user.org_id,
            template_id=template_id,
            reviewer_user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


@router.post(
    "/{template_id}/request-changes", response_model=TemplateRead
)
async def request_changes_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_REVIEW)),
) -> TemplateRead:
    if not payload.note or not payload.note.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="note is required when requesting changes",
        )
    try:
        template = await templates_workflow.request_changes(
            db,
            org_id=user.org_id,
            template_id=template_id,
            reviewer_user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


@router.post("/{template_id}/publish", response_model=TemplateRead)
async def publish_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload = WorkflowActionPayload(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_PUBLISH)),
) -> TemplateRead:
    try:
        template = await templates_workflow.publish(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


@router.post("/{template_id}/archive", response_model=TemplateRead)
async def archive_workflow_endpoint(
    template_id: uuid.UUID,
    payload: WorkflowActionPayload = WorkflowActionPayload(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateRead:
    """Archive via the workflow (writes a review row + audits).

    The Step-3 ``DELETE /templates/{id}`` route still works for
    backwards-compat; this endpoint is the workflow-aligned twin that
    the UI calls when the operator clicks "Archive" from the review
    modal so the review trail captures the action with an optional
    note."""
    try:
        template = await templates_workflow.archive(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            note=payload.note,
        )
    except TemplateError as exc:
        raise _workflow_http_map(exc) from exc
    return TemplateRead.model_validate(template)


# --- external submission (Step 9) ------------------------------------


class ExternalStatusResponse(BaseModel):
    """Wire shape for ``GET /templates/{id}/external-status``."""

    model_config = ConfigDict(extra="forbid")

    status: str
    rejection_reason: Optional[str] = None
    last_synced_at: Optional[str] = None


def _meta_app_credentials() -> tuple[str, str]:
    """Pull the Meta App credentials needed by the WA submission path.

    Both are loaded from the SOPS-managed secrets at process start;
    a missing pair is a 503 (operator can't fix from the UI)."""
    from config import META_APP_ID, WHATSAPP_APP_SECRET

    if not META_APP_ID or not WHATSAPP_APP_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Server is missing Meta App credentials — "
                "set META_APP_ID and WHATSAPP_APP_SECRET."
            ),
        )
    return META_APP_ID, WHATSAPP_APP_SECRET


@router.post("/{template_id}/submit-external", response_model=TemplateRead)
async def submit_external_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_SUBMIT_EXTERNAL)),
) -> TemplateRead:
    """Submit the template to its channel's external review pipeline
    (today: WhatsApp / Meta). Returns the central row with
    ``external_status='pending'`` on success."""
    app_id, app_secret = _meta_app_credentials()
    try:
        template = await templates_external.submit_external(
            db,
            org_id=user.org_id,
            template_id=template_id,
            user_id=user.legacy_uuid,
            app_id=app_id,
            app_secret=app_secret,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    except ExternalSubmissionNotSupported as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except MissingExtensionRow as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return TemplateRead.model_validate(template)


@router.get(
    "/{template_id}/external-status",
    response_model=ExternalStatusResponse,
)
async def external_status_endpoint(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> ExternalStatusResponse:
    """Return the live external-status payload (status + rejection
    reason + last-synced-at) for the editor's status badge."""
    try:
        payload = await templates_external.get_external_status(
            db, org_id=user.org_id, template_id=template_id
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    return ExternalStatusResponse(**payload)


# --- test send --------------------------------------------------------


@router.post(
    "/{template_id}/test-send",
    response_model=TemplateTestSendRead,
)
async def test_send_endpoint(
    template_id: uuid.UUID,
    payload: TestSendPayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_WRITE)),
) -> TemplateTestSendRead:
    """Send a one-off rendered copy of the template to a chosen
    recipient. Used by the editor's "Test send" button (Step 8 UI).

    Works on drafts — no need to publish first; the operator can test
    a fresh template before submitting it for review."""
    try:
        audit_row = await templates_test_send.dispatch_test_send(
            db,
            org_id=user.org_id,
            template_id=template_id,
            recipient=payload.recipient,
            user_id=user.legacy_uuid,
            sample_context=payload.sample_context,
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    except InvalidRecipient as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except TestSendNotSupported as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    return TemplateTestSendRead.model_validate(audit_row)


@router.post("/{template_id}/preview", response_model=PreviewResponse)
async def preview_endpoint(
    template_id: uuid.UUID,
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions(PERM_READ)),
) -> PreviewResponse:
    """Render the template's body (and subject, for email) against a
    sample context. Uses the lenient resolver — missing paths render
    as empty string, so previewing with an empty body returns the
    template's static content + blanks for variables.
    """
    try:
        template = await templates_service.get_template(
            db, org_id=user.org_id, template_id=template_id
        )
    except TemplateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="template not found",
        ) from exc
    body = resolve(template.body_text, payload.context)
    subject = (
        resolve(template.subject, payload.context)
        if template.subject
        else None
    )
    return PreviewResponse(subject=subject, body=body)


__all__ = ["router"]
