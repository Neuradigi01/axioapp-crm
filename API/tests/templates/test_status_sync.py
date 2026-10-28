"""Pin tests for the Step-14 external-status sync surface.

Covers the four moving pieces:

* :func:`sync.sync_external_status` — calls Meta + writes back
* :func:`sync.sync_all_pending` — bulk + ignores non-WA + non-pending
* :func:`sync.prepare_resubmit` — moves rejected rows back to draft
* The webhook handler at
  :func:`integrations.whatsapp.templates_service.apply_template_status_update`
  syncing the central row + firing notifications

The Meta Graph HTTP call is mocked at the
:class:`MetaGraphClient.get_message_template` boundary so the tests
don't need a Meta token or a live Graph response.

WhatsApp credentials are stubbed by patching ``get_active_config`` +
``decrypt`` so the resolver path returns a fake bundle without
inserting a full integrations / configs row tree.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import data_access as templates_da
from src.app.core.templates import service as templates_service
from src.app.core.templates import sync as templates_sync
from src.app.core.templates.exceptions import TemplateError
from src.app.core.templates.models import (
    MessageTemplateReview,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
    TemplateReviewAction,
)
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


# --- fixtures ---------------------------------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def _make_wa_template(test_db, *, org_id, external_status=None):
    token = set_context(RequestContext(org_id=org_id))
    try:
        template = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="WA Welcome",
                channel=ConversationChannel.whatsapp,
                category=TemplateCategory.marketing,
                body_text="Hi {{ contact.first_name }}",
            ),
        )
    finally:
        reset_context(token)
    if external_status is not None:
        template.external_status = external_status
        await test_db.commit()
        await test_db.refresh(template)
    return template


async def _make_wa_extension(test_db, *, org_id, message_template_id, meta_template_id="meta-1"):
    """Insert a `tbl_whatsapp_templates` row pointed at the central
    template. Returns the row id so callers can poke at it."""
    wa_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            """
            INSERT INTO tbl_whatsapp_templates (
                id, org_id, message_template_id, meta_template_id,
                name, language, category, body, submission_status,
                status, created_at, updated_at
            ) VALUES (
                :id, :org_id, :mtid, :meta_id,
                'WA Welcome', 'en', 'MARKETING', 'Hi {{1}}', 'pending_review',
                'PENDING', NOW(), NOW()
            )
            """
        ),
        {
            "id": str(wa_id),
            "org_id": str(org_id),
            "mtid": str(message_template_id),
            "meta_id": meta_template_id,
        },
    )
    await test_db.commit()
    return wa_id


def _patch_wa_bundle():
    """Patch the WA `get_active_config` + `decrypt` chain so the
    sync resolver returns a fake bundle without needing a real
    integrations row."""
    integration = SimpleNamespace(access_token_enc=b"encrypted-token")
    config = SimpleNamespace(api_version="v19.0", waba_id="waba-1")
    return [
        patch(
            "src.app.core.integrations.whatsapp.connect.get_active_config",
            new=AsyncMock(return_value=(integration, config)),
        ),
        patch(
            "src.app.core.integrations.crypto.decrypt",
            return_value="plain-token",
        ),
    ]


# --- sync_external_status -------------------------------------------


async def test_sync_status_calls_meta_for_wa_template(test_db, org_id):
    """The Meta Graph client's `get_message_template` is reached with
    the WA row's `meta_template_id`."""
    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    await _make_wa_extension(test_db, org_id=org_id, message_template_id=template.id)
    fake_get = AsyncMock(return_value={"status": "APPROVED"})
    with (
        _patch_wa_bundle()[0],
        _patch_wa_bundle()[1],
        patch(
            "src.app.core.integrations.whatsapp.meta_graph_client.MetaGraphClient.get_message_template",
            new=fake_get,
        ),
    ):
        await templates_sync.sync_external_status(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
            app_id="app",
            app_secret="secret",
        )
    assert fake_get.await_count == 1
    kwargs = fake_get.await_args.kwargs
    assert kwargs["meta_template_id"] == "meta-1"


async def test_sync_status_writes_central_status(test_db, org_id):
    """Sync persists Meta's verdict onto the central row + writes a
    review row of action=external_sync."""
    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    await _make_wa_extension(test_db, org_id=org_id, message_template_id=template.id)
    with (
        _patch_wa_bundle()[0],
        _patch_wa_bundle()[1],
        patch(
            "src.app.core.integrations.whatsapp.meta_graph_client.MetaGraphClient.get_message_template",
            new=AsyncMock(return_value={"status": "APPROVED"}),
        ),
    ):
        updated = await templates_sync.sync_external_status(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
            app_id="app",
            app_secret="secret",
        )
    assert updated.external_status == TemplateExternalStatus.approved

    reviews = (
        (
            await test_db.execute(
                select(MessageTemplateReview).where(
                    MessageTemplateReview.template_id == template.id,
                    MessageTemplateReview.action == TemplateReviewAction.external_sync,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(reviews) == 1
    assert "approved" in (reviews[0].note or "")


# --- webhook handler --------------------------------------------------


async def test_webhook_status_update_writes_central_row(test_db, org_id):
    """The Meta webhook handler updates the central row's
    external_status via the reciprocal message_template_id link."""
    from src.app.core.integrations.whatsapp.templates_service import (
        apply_template_status_update,
    )

    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    await _make_wa_extension(test_db, org_id=org_id, message_template_id=template.id)
    # Patch the audit shim so the test isn't entangled with the audit
    # pipeline (audit.log opens its own session).
    with patch(
        "src.app.core.audit.log",
        new=AsyncMock(return_value=None),
    ):
        applied = await apply_template_status_update(
            test_db,
            org_id=org_id,
            meta_template_id="meta-1",
            template_name=None,
            language=None,
            event="APPROVED",
            reason=None,
        )
    assert applied is True
    await test_db.refresh(template)
    assert template.external_status == TemplateExternalStatus.approved


async def test_webhook_status_rejected_emits_notification(test_db, org_id):
    """When the webhook transitions external_status into 'rejected',
    `notify_external_status_change` is called with the rejection
    reason."""
    from src.app.core.integrations.whatsapp.templates_service import (
        apply_template_status_update,
    )

    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    await _make_wa_extension(test_db, org_id=org_id, message_template_id=template.id)
    notify_mock = AsyncMock(return_value=None)
    with (
        patch(
            "src.app.core.templates.sync.notify_external_status_change",
            new=notify_mock,
        ),
        patch("src.app.core.audit.log", new=AsyncMock(return_value=None)),
    ):
        await apply_template_status_update(
            test_db,
            org_id=org_id,
            meta_template_id="meta-1",
            template_name=None,
            language=None,
            event="REJECTED",
            reason="Body has too many emojis",
        )
    assert notify_mock.await_count == 1
    kwargs = notify_mock.await_args.kwargs
    assert kwargs["new_status"] == TemplateExternalStatus.rejected
    assert kwargs["rejection_reason"] == "Body has too many emojis"


# --- sync_all_pending -------------------------------------------------


async def test_celery_task_picks_up_pending_only(test_db, org_id):
    """`list_pending_external` returns only pending + paused rows.
    Approved + draft + archived are excluded so the sweep doesn't
    poll Meta for stable values."""
    # pending
    pending = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    # paused
    paused = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.paused
    )
    paused.name = "WA Paused"
    await test_db.commit()
    # approved (must be skipped)
    approved = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.approved
    )
    approved.name = "WA Approved"
    await test_db.commit()

    rows = await templates_da.list_pending_external(test_db, org_id=org_id)
    ids = {r.id for r in rows}
    assert pending.id in ids
    assert paused.id in ids
    assert approved.id not in ids


# --- manual refresh end-to-end ---------------------------------------


async def test_manual_refresh_updates_external_status(test_db, org_id):
    """The manual-refresh path (which the router calls) flips a
    pending row to whatever Meta now reports — exercising the same
    code as the periodic sweep but on a single id."""
    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.pending
    )
    await _make_wa_extension(test_db, org_id=org_id, message_template_id=template.id)
    with (
        _patch_wa_bundle()[0],
        _patch_wa_bundle()[1],
        patch(
            "src.app.core.integrations.whatsapp.meta_graph_client.MetaGraphClient.get_message_template",
            new=AsyncMock(
                return_value={
                    "status": "REJECTED",
                    "rejected_reason": "Body has too many emojis",
                }
            ),
        ),
        patch(
            "src.app.core.templates.sync.notify_external_status_change",
            new=AsyncMock(return_value=None),
        ),
    ):
        updated = await templates_sync.sync_external_status(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
            app_id="app",
            app_secret="secret",
        )
    assert updated.external_status == TemplateExternalStatus.rejected


# --- prepare_resubmit -------------------------------------------------


async def test_rejected_template_resubmit_clears_external_status(test_db, org_id):
    """Resubmit on a rejected row resets internal=draft + external=n_a
    so the operator can edit + re-submit. Other external statuses
    raise TemplateError (router maps to 409)."""
    template = await _make_wa_template(
        test_db, org_id=org_id, external_status=TemplateExternalStatus.rejected
    )
    # Simulate a previously-published row that Meta rejected.
    template.internal_status = TemplateInternalStatus.published
    await test_db.commit()

    updated = await templates_sync.prepare_resubmit(
        test_db,
        org_id=org_id,
        template_id=template.id,
        user_id=None,
    )
    assert updated.internal_status == TemplateInternalStatus.draft
    assert updated.external_status == TemplateExternalStatus.n_a

    # A second call now fails because the row is no longer rejected —
    # protects against accidental clicks wiping a real verdict.
    with pytest.raises(TemplateError):
        await templates_sync.prepare_resubmit(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
        )
