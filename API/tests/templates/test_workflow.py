"""Workflow state-machine tests for ``core.templates.workflow``.

Exercises the five transitions, the self-approve guard, the
mandatory-review org toggle, and the publish-blocked-by-external
pre-check. Verifies that every transition appends one
``tbl_message_template_reviews`` row.

Uses the function-scoped ``test_db`` fixture from ``conftest.py``.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.settings.models import OrgSettings
from src.app.core.templates import service as templates_service
from src.app.core.templates import workflow as templates_workflow
from src.app.core.templates.exceptions import (
    InvalidWorkflowTransition,
    PublishBlockedByExternal,
    SelfApproveBlocked,
    TemplateError,
)
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateReview,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def org_and_settings(test_db):
    """Seed one org + its OrgSettings row. Returns (org_id, settings_id)
    so individual tests can flip the toggles by direct row mutation."""
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    settings = OrgSettings(org_id=org_id)
    test_db.add(settings)
    await test_db.commit()
    await test_db.refresh(settings)
    return org_id, settings


def _email_payload(name: str = "T") -> TemplateCreate:
    return TemplateCreate(
        name=name,
        channel=ConversationChannel.email,
        category=TemplateCategory.marketing,
        body_text="Hi {{ contact.first_name }}",
        subject="Welcome",
    )


async def _make_draft(test_db, *, org_id, author_uuid=None):
    token = set_context(
        RequestContext(org_id=org_id, user_id=author_uuid or uuid.uuid4())
    )
    try:
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=author_uuid,
            payload=_email_payload(),
        )
    finally:
        reset_context(token)


# --- legal transitions --------------------------------------------------


async def test_draft_to_in_review(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        out = await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        assert out.internal_status == TemplateInternalStatus.in_review
    finally:
        reset_context(token)


async def test_full_happy_path(test_db, org_and_settings):
    """draft → in_review → approved → published, with reviewer ≠ author."""
    org_id, _ = org_and_settings
    author = uuid.uuid4()
    reviewer = uuid.uuid4()
    template = await _make_draft(test_db, org_id=org_id, author_uuid=author)

    token = set_context(RequestContext(org_id=org_id))
    try:
        t1 = await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=author,
        )
        assert t1.internal_status == TemplateInternalStatus.in_review

        t2 = await templates_workflow.approve(
            test_db,
            org_id=org_id,
            template_id=template.id,
            reviewer_user_id=reviewer,
            note="LGTM",
        )
        assert t2.internal_status == TemplateInternalStatus.approved

        t3 = await templates_workflow.publish(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=reviewer,
        )
        assert t3.internal_status == TemplateInternalStatus.published

        # 3 review rows recorded.
        reviews = (
            await test_db.execute(
                select(MessageTemplateReview)
                .where(MessageTemplateReview.template_id == template.id)
                .order_by(MessageTemplateReview.created_at.asc())
            )
        ).scalars().all()
        assert [r.action for r in reviews] == [
            TemplateReviewAction.submit,
            TemplateReviewAction.approve,
            TemplateReviewAction.publish,
        ]
        assert reviews[1].note == "LGTM"
    finally:
        reset_context(token)


async def test_reject_returns_to_draft(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        out = await templates_workflow.reject(
            test_db,
            org_id=org_id,
            template_id=template.id,
            reviewer_user_id=uuid.uuid4(),
            note="needs more variables",
        )
        assert out.internal_status == TemplateInternalStatus.draft
    finally:
        reset_context(token)


async def test_request_changes_returns_to_draft(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        out = await templates_workflow.request_changes(
            test_db,
            org_id=org_id,
            template_id=template.id,
            reviewer_user_id=uuid.uuid4(),
            note="tweak the subject",
        )
        assert out.internal_status == TemplateInternalStatus.draft

        last = (
            await test_db.execute(
                select(MessageTemplateReview)
                .where(MessageTemplateReview.template_id == template.id)
                .order_by(MessageTemplateReview.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        assert last.action == TemplateReviewAction.request_changes
    finally:
        reset_context(token)


async def test_archive_idempotent(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        t1 = await templates_workflow.archive(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        assert t1.internal_status == TemplateInternalStatus.archived
        t2 = await templates_workflow.archive(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        assert t2.internal_status == TemplateInternalStatus.archived
        # Only one review row (the first archive); the second was a no-op.
        count = (
            await test_db.execute(
                select(MessageTemplateReview).where(
                    MessageTemplateReview.template_id == template.id,
                    MessageTemplateReview.action == TemplateReviewAction.archive,
                )
            )
        ).scalars().all()
        assert len(count) == 1
    finally:
        reset_context(token)


# --- illegal transitions ------------------------------------------------


async def test_cannot_approve_a_draft(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(InvalidWorkflowTransition) as info:
            await templates_workflow.approve(
                test_db,
                org_id=org_id,
                template_id=template.id,
                reviewer_user_id=uuid.uuid4(),
            )
        assert info.value.current == "draft"
        assert info.value.action == "approve"
    finally:
        reset_context(token)


async def test_cannot_publish_with_pending_external(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    template.internal_status = TemplateInternalStatus.approved
    template.external_status = TemplateExternalStatus.pending
    await test_db.commit()

    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(PublishBlockedByExternal):
            await templates_workflow.publish(
                test_db,
                org_id=org_id,
                template_id=template.id,
                user_id=uuid.uuid4(),
            )
    finally:
        reset_context(token)


async def test_reject_requires_note(test_db, org_and_settings):
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        with pytest.raises(TemplateError):
            await templates_workflow.reject(
                test_db,
                org_id=org_id,
                template_id=template.id,
                reviewer_user_id=uuid.uuid4(),
                note="",
            )
    finally:
        reset_context(token)


# --- self-approve guard -------------------------------------------------


async def test_self_approve_blocked_by_default(test_db, org_and_settings):
    org_id, _ = org_and_settings
    author = uuid.uuid4()
    template = await _make_draft(test_db, org_id=org_id, author_uuid=author)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=author,
        )
        with pytest.raises(SelfApproveBlocked):
            await templates_workflow.approve(
                test_db,
                org_id=org_id,
                template_id=template.id,
                reviewer_user_id=author,
            )
    finally:
        reset_context(token)


async def test_self_approve_allowed_when_org_setting_on(
    test_db, org_and_settings
):
    org_id, settings = org_and_settings
    settings.template_review_self_approve_allowed = True
    await test_db.commit()

    author = uuid.uuid4()
    template = await _make_draft(test_db, org_id=org_id, author_uuid=author)
    token = set_context(RequestContext(org_id=org_id))
    try:
        await templates_workflow.submit_for_review(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=author,
        )
        out = await templates_workflow.approve(
            test_db,
            org_id=org_id,
            template_id=template.id,
            reviewer_user_id=author,
        )
        assert out.internal_status == TemplateInternalStatus.approved
    finally:
        reset_context(token)


# --- mandatory-review toggle -------------------------------------------


async def test_publish_from_draft_when_review_optional(
    test_db, org_and_settings
):
    """Default ``template_review_mandatory=false`` lets ``draft →
    published`` happen without an intermediate review."""
    org_id, _ = org_and_settings
    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        out = await templates_workflow.publish(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=uuid.uuid4(),
        )
        assert out.internal_status == TemplateInternalStatus.published
    finally:
        reset_context(token)


async def test_publish_from_draft_blocked_when_review_mandatory(
    test_db, org_and_settings
):
    """With ``template_review_mandatory=true`` the workflow forces
    every template through ``in_review → approved`` first."""
    org_id, settings = org_and_settings
    settings.template_review_mandatory = True
    await test_db.commit()

    template = await _make_draft(test_db, org_id=org_id)
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(InvalidWorkflowTransition) as info:
            await templates_workflow.publish(
                test_db,
                org_id=org_id,
                template_id=template.id,
                user_id=uuid.uuid4(),
            )
        assert info.value.current == "draft"
        assert info.value.action == "publish"
    finally:
        reset_context(token)
