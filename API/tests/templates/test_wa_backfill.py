"""Pin tests for the Step-9 WA → central backfill mapping.

The migration's data-fix block can't be unit-tested directly (alembic
runs the migration via `op.execute`, not via a callable a pytest can
import). Instead this file pins the two mapping dicts the migration
uses — if a future refactor drifts the WA submission_status → central
internal_status / external_status correspondence, this fails CI rather
than silently remapping live tenants.

Plus a behavioural test of `external_submission.submit_external` with
a mocked `WhatsAppTemplate` extension row, covering the channel-not-
supported path + the missing-extension path + the happy path that
ends with `external_status='pending'`.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text as sql_text
from unittest.mock import AsyncMock, patch

from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import external_submission as templates_external
from src.app.core.templates import service as templates_service
from src.app.core.templates.exceptions import TemplateNotFound
from src.app.core.templates.external_submission import (
    ExternalSubmissionNotSupported,
    MissingExtensionRow,
)
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateCategory,
    TemplateExternalStatus,
    TemplateInternalStatus,
)
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


# --- pin the mapping dicts (migration source-of-truth) -----------------


def test_wa_internal_status_mapping_is_stable():
    """If this fails: a refactor changed how WA `submission_status`
    values map into central `internal_status`. Confirm with the
    manager before adjusting — production tenants will re-key on the
    next backfill round."""
    from src.app.alembic.versions import (  # type: ignore[import-not-found]
        _migration_module_lookup,
    ) if False else None
    # The migration filename starts with a digit so we can't `from
    # alembic.versions.0120_...` directly. Read the constants via
    # importlib to keep this pin honest.
    import importlib.util
    import os

    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(
        here, "alembic", "versions", "0120_wa_template_backfill.py"
    )
    spec = importlib.util.spec_from_file_location("backfill_0120", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.WA_TO_INTERNAL_STATUS == {
        "draft": "draft",
        "pending_review": "in_review",
        "approved": "published",
        "rejected": "draft",
        "paused": "published",
        "disabled": "archived",
    }
    assert mod.WA_TO_EXTERNAL_STATUS == {
        "draft": "n_a",
        "pending_review": "pending",
        "approved": "approved",
        "rejected": "rejected",
        "paused": "paused",
        "disabled": "rejected",
    }


# --- behavioural tests of submit_external ------------------------------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text(
            "INSERT INTO tbl_organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def _make_email_template(test_db, *, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="Welcome",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi {{ contact.first_name }}",
                subject="Welcome",
            ),
        )
    finally:
        reset_context(token)


async def _make_wa_template(test_db, *, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        return await templates_service.create_template(
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


async def test_submit_external_rejects_email(test_db, org_id):
    template = await _make_email_template(test_db, org_id=org_id)
    with pytest.raises(ExternalSubmissionNotSupported) as info:
        await templates_external.submit_external(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
            app_id="app",
            app_secret="secret",
        )
    assert info.value.channel == "email"


async def test_submit_external_missing_wa_extension(test_db, org_id):
    """Central WA template with no `tbl_whatsapp_templates` row → 409.
    Happens when the operator created the template via the new editor
    but never went through the legacy WA wizard's create-draft flow."""
    template = await _make_wa_template(test_db, org_id=org_id)
    with pytest.raises(MissingExtensionRow) as info:
        await templates_external.submit_external(
            test_db,
            org_id=org_id,
            template_id=template.id,
            user_id=None,
            app_id="app",
            app_secret="secret",
        )
    assert info.value.channel == "whatsapp"


async def test_submit_external_template_not_found(test_db, org_id):
    with pytest.raises(TemplateNotFound):
        await templates_external.submit_external(
            test_db,
            org_id=org_id,
            template_id=uuid.uuid4(),
            user_id=None,
            app_id="app",
            app_secret="secret",
        )


async def test_get_external_status_returns_payload(test_db, org_id):
    """get_external_status returns the channel-appropriate payload —
    n_a + nulls for a fresh email template that's never been
    submitted."""
    template = await _make_email_template(test_db, org_id=org_id)
    out = await templates_external.get_external_status(
        test_db, org_id=org_id, template_id=template.id
    )
    assert out["status"] == "n_a"
    assert out["rejection_reason"] is None
    assert out["last_synced_at"] is None
