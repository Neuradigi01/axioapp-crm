"""Step 1 smoke test for the central template library.

Catches typos in :mod:`core.templates.models` + :mod:`core.templates.schemas`
before Step 2 builds on top of them. The actual CRUD + RLS path is
covered by Step 2's ``test_service.py``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates.models import (
    MessageTemplate,
    MessageTemplateReview,
    MessageTemplateTestSend,
    MessageTemplateVersion,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.core.templates.schemas import (
    TemplateCreate,
    TemplateRead,
    TemplateReviewRead,
    TemplateTestSendRead,
    TemplateUpdate,
    TemplateVersionRead,
)


def test_models_importable_and_instantiable():
    """Every model class can be instantiated with the minimum fields.

    No DB session is opened here — we just exercise the ORM mapping.
    """
    org_id = uuid.uuid4()
    template_id = uuid.uuid4()

    template = MessageTemplate(
        org_id=org_id,
        channel=ConversationChannel.email,
        name="Welcome",
        category=TemplateCategory.transactional,
        language="en",
        body_text="Hi {{contact.first_name}}",
        subject="Welcome to {{org.name}}",
        preview_text="Glad to have you",
        internal_status=TemplateInternalStatus.draft,
        external_status=TemplateExternalStatus.n_a,
    )
    assert template.name == "Welcome"
    assert template.channel == ConversationChannel.email

    version = MessageTemplateVersion(
        org_id=org_id,
        template_id=template_id,
        version=1,
        body_text="Hi {{contact.first_name}}",
        subject="Welcome to {{org.name}}",
    )
    assert version.version == 1

    review = MessageTemplateReview(
        org_id=org_id,
        template_id=template_id,
        version=1,
        action=TemplateReviewAction.submit,
    )
    assert review.action == TemplateReviewAction.submit

    test_send = MessageTemplateTestSend(
        org_id=org_id,
        template_id=template_id,
        version=1,
        channel=ConversationChannel.email,
        sent_to="reviewer@example.com",
    )
    assert test_send.sent_to == "reviewer@example.com"


def test_template_create_schema_email_requires_subject():
    """Email channel rejects a missing or blank subject."""
    payload_ok = TemplateCreate(
        name="Welcome",
        channel=ConversationChannel.email,
        body_text="Body",
        subject="Welcome to our store",
    )
    assert payload_ok.subject == "Welcome to our store"

    import pytest

    with pytest.raises(ValueError, match="subject is required"):
        TemplateCreate(
            name="Welcome",
            channel=ConversationChannel.email,
            body_text="Body",
        )

    with pytest.raises(ValueError, match="subject is required"):
        TemplateCreate(
            name="Welcome",
            channel=ConversationChannel.email,
            body_text="Body",
            subject="   ",
        )


def test_template_create_schema_non_email_rejects_subject():
    """Non-email channels reject subject + preview_text — they have no slot for them."""
    import pytest

    # Plain WhatsApp template is fine.
    payload_ok = TemplateCreate(
        name="WA Welcome",
        channel=ConversationChannel.whatsapp,
        body_text="Hi {{contact.first_name}}",
    )
    assert payload_ok.subject is None

    with pytest.raises(ValueError, match="subject is only valid for email"):
        TemplateCreate(
            name="WA Welcome",
            channel=ConversationChannel.whatsapp,
            body_text="Hi",
            subject="not allowed",
        )

    with pytest.raises(ValueError, match="preview_text is only valid for email"):
        TemplateCreate(
            name="WA Welcome",
            channel=ConversationChannel.whatsapp,
            body_text="Hi",
            preview_text="not allowed",
        )


def test_template_read_round_trip_from_model():
    """``TemplateRead.model_validate`` reads from a ``MessageTemplate`` row."""
    now = datetime.now(timezone.utc)
    row = MessageTemplate(
        id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        channel=ConversationChannel.email,
        name="Welcome",
        category=TemplateCategory.transactional,
        language="en",
        body_text="Hi",
        subject="Welcome",
        preview_text=None,
        variables=["contact.first_name"],
        internal_status=TemplateInternalStatus.draft,
        external_status=TemplateExternalStatus.n_a,
        external_provider_id=None,
        current_version=1,
        created_by_user_id=None,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
    out = TemplateRead.model_validate(row)
    assert out.name == "Welcome"
    assert out.channel == ConversationChannel.email
    assert out.internal_status == TemplateInternalStatus.draft
    assert out.variables == ["contact.first_name"]


def test_version_review_test_send_read_schemas_importable():
    """The read schemas at least parse — Step 2 exercises them deeper."""
    assert TemplateVersionRead.model_config["from_attributes"] is True
    assert TemplateReviewRead.model_config["from_attributes"] is True
    assert TemplateTestSendRead.model_config["from_attributes"] is True


def test_template_update_partial_payload_is_legal():
    """``TemplateUpdate`` accepts an empty body (no-op) and any single field."""
    p1 = TemplateUpdate()
    assert p1.name is None
    p2 = TemplateUpdate(name="Renamed")
    assert p2.name == "Renamed"
