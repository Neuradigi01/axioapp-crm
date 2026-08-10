"""Internal review-workflow state machine for templates.

Five transitions wire the central state machine:

    draft ──submit──▶ in_review ──approve──▶ approved ──publish──▶ published ──archive──▶ archived
                       │                                                                       ▲
                       ├──reject──▶ draft                                                      │
                       └──request_changes──▶ draft                                              │
    draft / any state ──────────────────────────archive─────────────────────────────────────────┘
    draft ──publish──▶ published   (only when org setting `template_review_mandatory = false`)

Each transition:

  1. Loads the template (RLS-scoped) — raises :class:`TemplateNotFound`.
  2. Validates the current state allows the requested action — raises
     :class:`InvalidWorkflowTransition` otherwise.
  3. Honours two org settings, both on ``tbl_org_settings``:
      * ``template_review_mandatory`` — when ``True`` a draft cannot
        publish directly; it must traverse ``in_review → approved``.
      * ``template_review_self_approve_allowed`` — when ``False`` the
        author of the template (snapshot via
        ``created_by_user_id``) cannot ``approve`` their own draft.
  4. Mutates ``internal_status`` on the parent row.
  5. Appends a row to ``tbl_message_template_reviews`` with the
     ``action`` enum value, the reviewer/actor, the note (when
     supplied), and the version at the time of the action.
  6. Emits a best-effort audit event ``templates.<action>`` via the
     shared :mod:`core.audit` writer.

The state machine is intentionally **pure of HTTP concerns**: it
raises typed Python exceptions that the router maps to HTTP codes.
Future automation / workflow callers will use these same functions
without touching FastAPI.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core import audit
from src.app.core.notifications import service as notifications_service
from src.app.core.permissions import data_access as _perms_da
from src.app.core.settings.models import OrgSettings
from src.app.core.templates.exceptions import (
    InvalidWorkflowTransition,
    PublishBlockedByExternal,
    SelfApproveBlocked,
    TemplateError,
)
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateReview,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.core.templates.service import get_template

logger = logging.getLogger(__name__)


# --- audit snapshot ----------------------------------------------------


def _snapshot(template: MessageTemplate) -> dict[str, Any]:
    return {
        "id": str(template.id),
        "name": template.name,
        "channel": template.channel.value,
        "internal_status": template.internal_status.value,
        "external_status": template.external_status.value,
        "current_version": template.current_version,
    }


# --- org-setting reader ------------------------------------------------


async def _get_org_review_settings(
    session: AsyncSession, *, org_id: uuid.UUID
) -> tuple[bool, bool]:
    """Return ``(mandatory, self_approve_allowed)`` from
    ``tbl_org_settings`` for the org. Missing row → both defaults
    (``False, False``)."""
    row = (
        await session.execute(
            select(
                OrgSettings.template_review_mandatory,
                OrgSettings.template_review_self_approve_allowed,
            ).where(OrgSettings.org_id == org_id)
        )
    ).one_or_none()
    if row is None:
        return False, False
    return bool(row[0]), bool(row[1])


# --- common transition write helper ------------------------------------


async def _apply_transition(
    session: AsyncSession,
    *,
    template: MessageTemplate,
    new_status: TemplateInternalStatus,
    action: TemplateReviewAction,
    actor_user_id: uuid.UUID | None,
    note: str | None,
) -> MessageTemplate:
    """Mutate ``internal_status``, write a review row, commit, emit
    audit. Single source of truth for the audit + history shape so
    every transition logs the same way."""
    before = _snapshot(template)
    template.internal_status = new_status
    template.updated_by_user_id = actor_user_id
    template.updated_at = func.now()

    review = MessageTemplateReview(
        org_id=template.org_id,
        template_id=template.id,
        version=template.current_version,
        reviewer_user_id=actor_user_id,
        action=action,
        note=note,
    )
    session.add(review)
    await session.commit()
    await session.refresh(template)

    await audit.log(
        f"templates.{action.value}",
        entity_type="message_template",
        entity_id=template.id,
        before=before,
        after=_snapshot(template),
    )
    logger.info(
        "templates.workflow org=%s template=%s action=%s -> %s",
        template.org_id,
        template.id,
        action.value,
        new_status.value,
    )
    return template


# --- transitions -------------------------------------------------------


async def submit_for_review(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    note: str | None = None,
) -> MessageTemplate:
    """``draft → in_review`` + fan-out notifications to reviewers.

    Every active user in the org who holds ``templates.review`` gets
    an in-app notification pointing at the template editor so they
    can approve or reject without hunting through the list.
    Notification failures are swallowed by ``notify()`` — the
    workflow transition is authoritative and must not roll back on
    a WS / email hiccup."""
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status != TemplateInternalStatus.draft:
        raise InvalidWorkflowTransition(current=template.internal_status.value, action="submit")
    updated = await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.in_review,
        action=TemplateReviewAction.submit,
        actor_user_id=user_id,
        note=note,
    )
    await _notify_reviewers_on_submit(session, template=updated, submitter_user_id=user_id)
    return updated


async def _notify_reviewers_on_submit(
    session: AsyncSession,
    *,
    template: MessageTemplate,
    submitter_user_id: uuid.UUID | None,
) -> None:
    """Best-effort fan-out. Every user with ``templates.review`` in the
    template's org gets one in-app notification. The submitter is
    skipped — no point pinging yourself. Errors are logged + swallowed
    so a broken notification service can never block a submission."""
    try:
        reviewer_ids = await _perms_da.list_user_ids_with_permission(
            session, org_id=template.org_id, permission_key="templates.review"
        )
    except Exception:
        logger.exception("templates.submit_for_review: reviewer lookup failed")
        return

    submitter_name = "A teammate"
    if submitter_user_id is not None:
        try:
            from src.app.core.users import data_access as _users_da

            submitter = await _users_da.get_user_by_uuid(session, submitter_user_id)
            if submitter is not None:
                submitter_name = submitter.full_name or submitter.email or "A teammate"
        except Exception:
            logger.exception("templates.submit_for_review: submitter lookup failed")

    title = f"{submitter_name} sent a template for your approval"
    body = f"Template '{template.name}' ({template.channel.value}) needs review."
    payload = {
        "template_id": str(template.id),
        "template_name": template.name,
        "channel": template.channel.value,
        "submitted_by_user_id": str(submitter_user_id) if submitter_user_id else None,
        "submitted_by_name": submitter_name,
        "deeplink": f"/user/templates/{template.id}",
    }
    for reviewer_id in reviewer_ids:
        if submitter_user_id is not None and reviewer_id == submitter_user_id:
            continue
        try:
            await notifications_service.notify(
                org_id=template.org_id,
                user_id=reviewer_id,
                type="template.submitted_for_review",
                title=title,
                body=body,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "templates.submit_for_review: notify failed for %s", reviewer_id
            )


async def approve(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    reviewer_user_id: uuid.UUID | None,
    note: str | None = None,
    caller_can_publish: bool = False,
) -> MessageTemplate:
    """``in_review → published`` (auto-publish on approve).

    Previously this transitioned to ``approved`` as an intermediate
    "ready to publish" state, then a second click walked
    ``approved → published``. That two-step dance was pure friction
    for the org — reviewers with review rights invariably held
    publish rights too, so they always clicked Publish immediately
    after Approve. The manager collapsed the flow: approving IS
    publishing. The ``approved`` state stays legal in the DB for any
    historical rows that landed there, but the state machine no
    longer produces new ones.

    Reviewer ≠ author still enforced unless the org setting
    ``template_review_self_approve_allowed`` is ``True`` OR the
    caller holds ``templates.publish`` (Owner / Admin tier).
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status != TemplateInternalStatus.in_review:
        raise InvalidWorkflowTransition(current=template.internal_status.value, action="approve")

    _, self_approve_allowed = await _get_org_review_settings(session, org_id=org_id)
    if (
        not self_approve_allowed
        and not caller_can_publish
        and reviewer_user_id is not None
        and template.created_by_user_id == reviewer_user_id
    ):
        raise SelfApproveBlocked()

    # External-status pre-check mirrors ``publish()`` — a WhatsApp
    # template with a pending / rejected Meta status shouldn't skip to
    # ``published`` internally either.
    if template.external_status not in (
        TemplateExternalStatus.n_a,
        TemplateExternalStatus.approved,
    ):
        raise PublishBlockedByExternal(external_status=template.external_status.value)

    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.published,
        action=TemplateReviewAction.approve,
        actor_user_id=reviewer_user_id,
        note=note,
    )


async def reject(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    reviewer_user_id: uuid.UUID | None,
    note: str,
) -> MessageTemplate:
    """``in_review → draft`` with a mandatory note explaining why."""
    if not note or not note.strip():
        raise TemplateError("a non-empty note is required to reject")
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status != TemplateInternalStatus.in_review:
        raise InvalidWorkflowTransition(current=template.internal_status.value, action="reject")
    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.draft,
        action=TemplateReviewAction.reject,
        actor_user_id=reviewer_user_id,
        note=note,
    )


async def request_changes(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    reviewer_user_id: uuid.UUID | None,
    note: str,
) -> MessageTemplate:
    """``in_review → draft`` — same final state as ``reject`` but the
    review-row carries ``request_changes`` so the UI can render
    "please revise" instead of "rejected". Mandatory note."""
    if not note or not note.strip():
        raise TemplateError("a non-empty note is required to request changes")
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status != TemplateInternalStatus.in_review:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value, action="request_changes"
        )
    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.draft,
        action=TemplateReviewAction.request_changes,
        actor_user_id=reviewer_user_id,
        note=note,
    )


async def publish(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    note: str | None = None,
    caller_can_publish: bool = False,
) -> MessageTemplate:
    """Move to ``published``. Two start states possible:

      * ``approved → published`` — the normal path.
      * ``draft → published`` — allowed when EITHER the org has opted
        out of mandatory review (``template_review_mandatory=False``)
        OR the caller is a senior role (holds ``templates.publish``,
        i.e. Owner / Admin per the seeded role templates). Junior
        roles that were granted publish by exception still traverse
        the review chain unless the org flag is also flipped.

    Plus the external-status pre-check: ``external_status`` must be
    ``n_a`` (the channel doesn't require external review at all) or
    ``approved`` (Meta / DLT already blessed it). Pending / rejected /
    paused all block publish.
    """
    template = await get_template(session, org_id=org_id, template_id=template_id)

    if template.external_status not in (
        TemplateExternalStatus.n_a,
        TemplateExternalStatus.approved,
    ):
        raise PublishBlockedByExternal(external_status=template.external_status.value)

    mandatory, _ = await _get_org_review_settings(session, org_id=org_id)
    # Owner / Admin bypass — senior roles never need to wait for a
    # second pair of eyes on their own draft. The router passes True
    # when the caller holds ``templates.publish``, which the seeded
    # Owner + Admin templates carry.
    mandatory_effective = mandatory and not caller_can_publish

    if template.internal_status == TemplateInternalStatus.approved:
        pass  # always allowed
    elif template.internal_status == TemplateInternalStatus.draft and not mandatory_effective:
        pass  # shortcut allowed when review is optional or caller is Owner / Admin
    else:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value,
            action="publish",
            hint=(
                "publish requires approved status; enable "
                "template_review_mandatory=false to allow direct "
                "publish from draft"
                if mandatory_effective
                else "publish requires approved or draft"
            ),
        )

    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.published,
        action=TemplateReviewAction.publish,
        actor_user_id=user_id,
        note=note,
    )


async def archive(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    user_id: uuid.UUID | None,
    note: str | None = None,
) -> MessageTemplate:
    """Any state → ``archived``. Idempotent on already-archived rows
    (returns the row without writing a second review entry)."""
    template = await get_template(session, org_id=org_id, template_id=template_id)
    if template.internal_status == TemplateInternalStatus.archived:
        return template
    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.archived,
        action=TemplateReviewAction.archive,
        actor_user_id=user_id,
        note=note,
    )


__all__ = [
    "approve",
    "archive",
    "publish",
    "reject",
    "request_changes",
    "submit_for_review",
]
