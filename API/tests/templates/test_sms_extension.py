"""Pin tests for the Step-12 SMS DLT extension + stub adapter.

Covers:
  * `set_dlt_metadata` upsert (create + update) preserves untouched
    fields and normalises ``dlt_header`` to uppercase six chars.
  * `get_dlt_metadata` returns ``None`` for a fresh SMS template.
  * The DAL reverse lookup `find_by_dlt_template_id` finds the row.
  * The DLT enum rejects unknown content categories.
  * The SMS stub adapter is registered with the channel registry
    and `send()` raises ``SMSNotConfigured``.
  * Importing the adapter does not introduce a hard provider
    dependency (the registry resolves to the stub without a config
    table).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from src.app.core.conversations import registry as channel_registry
from src.app.core.conversations.adapters.sms import (
    SMSAdapter,
    SMSNotConfigured,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates import sms_extension
from src.app.core.templates.data_access import sms_dlt as sms_dlt_da
from src.app.core.templates.schemas import TemplateCreate
from src.app.core.templates.sms_extension import (
    SMSDLTContentCategory,
    SMSDLTTemplateStatus,
)
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


async def _make_sms_template(test_db, *, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=TemplateCreate(
                name="OTP",
                channel=ConversationChannel.sms,
                body_text="Your OTP is {{ otp.code }}.",
            ),
        )
    finally:
        reset_context(token)


# --- enum hygiene -----------------------------------------------------


def test_sms_dlt_content_category_values_are_stable():
    """If this fails: a refactor renamed one of the four TRAI content
    categories. Production rows hold these literal strings, so confirm
    with the manager + plan a data migration before changing."""
    assert {m.value for m in SMSDLTContentCategory} == {
        "transactional",
        "promotional",
        "service_explicit",
        "service_implicit",
    }


def test_sms_dlt_template_status_values_are_stable():
    assert {m.value for m in SMSDLTTemplateStatus} == {
        "registered",
        "pending",
        "rejected",
    }


# --- DAL + service round-trip ------------------------------------------


async def test_get_dlt_metadata_returns_none_for_fresh_template(test_db, org_id):
    template = await _make_sms_template(test_db, org_id=org_id)
    out = await sms_extension.get_dlt_metadata(test_db, org_id=org_id, template_id=template.id)
    assert out is None


async def test_set_dlt_metadata_creates_then_updates(test_db, org_id):
    template = await _make_sms_template(test_db, org_id=org_id)

    row = await sms_extension.set_dlt_metadata(
        test_db,
        org_id=org_id,
        template_id=template.id,
        user_id=None,
        payload={
            "dlt_entity_id": "1101234567890123456",
            "dlt_template_id": "1707169876543210987",
            "dlt_content_category": "promotional",
            "dlt_header": "acmefr",  # lowercase → normalised
            "dlt_template_status": "registered",
        },
    )
    assert row.dlt_entity_id == "1101234567890123456"
    assert row.dlt_template_id == "1707169876543210987"
    assert row.dlt_content_category == SMSDLTContentCategory.promotional
    assert row.dlt_header == "ACMEFR"
    assert row.dlt_template_status == SMSDLTTemplateStatus.registered

    # Second call updates only the supplied fields; the rest survive.
    row2 = await sms_extension.set_dlt_metadata(
        test_db,
        org_id=org_id,
        template_id=template.id,
        user_id=None,
        payload={"dlt_template_status": "rejected"},
    )
    assert row2.id == row.id
    assert row2.dlt_template_status == SMSDLTTemplateStatus.rejected
    # Other fields untouched.
    assert row2.dlt_entity_id == "1101234567890123456"
    assert row2.dlt_header == "ACMEFR"


async def test_find_by_dlt_template_id_reverse_lookup(test_db, org_id):
    template = await _make_sms_template(test_db, org_id=org_id)
    await sms_extension.set_dlt_metadata(
        test_db,
        org_id=org_id,
        template_id=template.id,
        user_id=None,
        payload={"dlt_template_id": "1707169876543210987"},
    )
    hit = await sms_dlt_da.find_by_dlt_template_id(
        test_db, org_id=org_id, dlt_template_id="1707169876543210987"
    )
    assert hit is not None
    assert hit.message_template_id == template.id
    # Missing id returns None — the future status-sync path uses this
    # to ignore portal callbacks for templates not in our library.
    miss = await sms_dlt_da.find_by_dlt_template_id(
        test_db, org_id=org_id, dlt_template_id="does-not-exist"
    )
    assert miss is None


# --- adapter registration ----------------------------------------------


def test_sms_adapter_is_registered():
    """Importing the conversations package side-effect-registers SMS
    so the editor + dispatcher can resolve the channel without
    `ChannelNotRegistered`. Sends still fail until a provider lands."""
    adapter = channel_registry.resolve(ConversationChannel.sms)
    assert isinstance(adapter, SMSAdapter)


async def test_sms_adapter_send_raises_not_configured():
    adapter = SMSAdapter()
    with pytest.raises(SMSNotConfigured):
        await adapter.send(
            org_id=uuid.uuid4(),
            external_id="+919876543210",
            text="hi",
            attachments=[],
        )


def test_sms_adapter_parse_webhook_is_not_implemented():
    adapter = SMSAdapter()
    with pytest.raises(NotImplementedError):
        adapter.parse_webhook({"any": "payload"})
