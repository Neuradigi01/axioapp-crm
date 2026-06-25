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
    """``draft → in_review``."""
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )
    if template.internal_status != TemplateInternalStatus.draft:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value, action="submit"
        )
    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.in_review,
        action=TemplateReviewAction.submit,
        actor_user_id=user_id,
        note=note,
    )


async def approve(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    reviewer_user_id: uuid.UUID | None,
    note: str | None = None,
) -> MessageTemplate:
    """``in_review → approved``. Reviewer ≠ author unless the org
    setting ``template_review_self_approve_allowed`` is ``True``."""
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )
    if template.internal_status != TemplateInternalStatus.in_review:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value, action="approve"
        )

    _, self_approve_allowed = await _get_org_review_settings(
        session, org_id=org_id
    )
    if (
        not self_approve_allowed
        and reviewer_user_id is not None
        and template.created_by_user_id == reviewer_user_id
    ):
        raise SelfApproveBlocked()

    return await _apply_transition(
        session,
        template=template,
        new_status=TemplateInternalStatus.approved,
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
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )
    if template.internal_status != TemplateInternalStatus.in_review:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value, action="reject"
        )
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
        raise TemplateError(
            "a non-empty note is required to request changes"
        )
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )
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
) -> MessageTemplate:
    """Move to ``published``. Two start states possible:

      * ``approved → published`` — the normal path.
      * ``draft → published`` — only when org setting
        ``template_review_mandatory`` is ``False`` (the operator
        explicitly opted out of mandatory review).

    Plus the external-status pre-check: ``external_status`` must be
    ``n_a`` (the channel doesn't require external review at all) or
    ``approved`` (Meta / DLT already blessed it). Pending / rejected /
    paused all block publish.
    """
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )

    if template.external_status not in (
        TemplateExternalStatus.n_a,
        TemplateExternalStatus.approved,
    ):
        raise PublishBlockedByExternal(
            external_status=template.external_status.value
        )

    mandatory, _ = await _get_org_review_settings(session, org_id=org_id)

    if template.internal_status == TemplateInternalStatus.approved:
        pass  # always allowed
    elif (
        template.internal_status == TemplateInternalStatus.draft
        and not mandatory
    ):
        pass  # shortcut allowed when review is optional
    else:
        raise InvalidWorkflowTransition(
            current=template.internal_status.value,
            action="publish",
            hint=(
                "publish requires approved status; enable "
                "template_review_mandatory=false to allow direct "
                "publish from draft"
                if mandatory
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
    template = await get_template(
        session, org_id=org_id, template_id=template_id
    )
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
