"""Pin tests for the Step-10 email-template merge.

The migration's data block can't be unit-tested directly (alembic
runs SQL via `op.execute`, not via a callable a pytest can import).
Instead this file pins the status-mapping dict the migration uses,
plus a behavioural check that the post-merge email-sequence DAL
filters archived rows correctly.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.conversations.models import ConversationChannel
from src.app.core.email_sequences import data_access as email_seq_da
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import TemplateCategory, TemplateInternalStatus
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.asyncio


def test_email_merge_status_mapping_is_stable():
    """If this fails: a refactor changed how
    `(deleted_at IS NULL, is_active)` maps to `internal_status` in
    migration 0121. Confirm with the manager before adjusting."""
    import importlib.util
    import os

    here = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(here, "alembic", "versions", "0121_email_template_merge.py")
    spec = importlib.util.spec_from_file_location("merge_0121", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.EMAIL_STATUS_MAPPING == {
        (False, True): "archived",
        (False, False): "archived",
        (True, True): "published",
        (True, False): "draft",
    }


# --- behavioural: email_seq_da.list_valid_email_template_ids -----------


@pytest_asyncio.fixture
async def org_id(test_db):
    org_id = uuid.uuid4()
    await test_db.execute(
        sql_text("INSERT INTO tbl_organizations (id, name, slug) VALUES (:id, :name, :slug)"),
        {"id": str(org_id), "name": "Demo", "slug": f"demo-{org_id.hex[:6]}"},
    )
    await test_db.commit()
    return org_id


async def test_email_dal_returns_only_live_email_templates(test_db, org_id):
    """The email-sequences DAL filters out non-email channels +
    archived rows. Cross-org filtering relies on RLS (tested
    separately)."""
    token = set_context(RequestContext(org_id=org_id))
    try:
        live = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="Live email",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Hi",
                subject="Hello",
            ),
        )
        archived = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="Archived email",
                channel=ConversationChannel.email,
                category=TemplateCategory.transactional,
                body_text="Old",
                subject="Old",
            ),
        )
        archived.internal_status = TemplateInternalStatus.archived
        await test_db.commit()

        wa = await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="WA template",
                channel=ConversationChannel.whatsapp,
                body_text="WA",
            ),
        )

        found = await email_seq_da.list_valid_email_template_ids(
            test_db, [live.id, archived.id, wa.id, uuid.uuid4()]
        )
        assert live.id in found
        # Archived + non-email + unknown ids are all filtered out.
        assert archived.id not in found
        assert wa.id not in found
    finally:
        reset_context(token)


async def test_email_dal_empty_input_returns_empty_set(test_db):
    out = await email_seq_da.list_valid_email_template_ids(test_db, [])
    assert out == set()
