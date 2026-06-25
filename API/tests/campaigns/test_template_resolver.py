"""Step-11 campaign template-resolver tests.

Covers the channel-match validator + the new per-channel template
lookup behaviour. The dispatcher's actual Meta send is mocked elsewhere
(the WA adapter has its own integration tests); these tests focus on:

  * Channel-match guard rejects a campaign whose template's channel
    differs from the campaign's channel.
  * Channel-match accepts when the channels align.
  * A/B campaigns validate BOTH variant template ids.
  * A non-existent template id is rejected at create time.

The migration-mapping correctness (every WA → central) is implicit
in the WA backfill test (Step 9's `test_wa_backfill.py`) — Step 11
only swings the FK; the source data was already validated.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import text as sql_text

from src.app.core.campaigns import service as campaigns_service
from src.app.core.campaigns.schemas import CampaignCreate
from src.app.core.conversations.models import ConversationChannel
from src.app.core.templates import service as templates_service
from src.app.core.templates.models import TemplateCategory
from src.app.core.templates.schemas import TemplateCreate
from src.app.shared.context import RequestContext, reset_context, set_context


pytestmark = pytest.mark.asyncio


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


async def _make_template(test_db, *, org_id, channel, name="T"):
    token = set_context(RequestContext(org_id=org_id))
    try:
        payload = TemplateCreate(
            name=name,
            channel=channel,
            category=TemplateCategory.marketing,
            body_text="Hi {{ contact.first_name }}",
            subject="Subj" if channel == ConversationChannel.email else None,
        )
        return await templates_service.create_template(
            test_db,
            org_id=org_id,
            user_id=None,
            payload=payload,
        )
    finally:
        reset_context(token)


# --- channel-match validator -------------------------------------------


async def test_validator_passes_when_channel_matches(test_db, org_id):
    template = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.email
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        # No raise → pass.
        await campaigns_service._validate_template_channel_match(
            test_db,
            org_id=org_id,
            campaign_channel=ConversationChannel.email,
            template_ids=[template.id],
        )
    finally:
        reset_context(token)


async def test_validator_rejects_channel_mismatch(test_db, org_id):
    wa_template = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.whatsapp
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(HTTPException) as info:
            await campaigns_service._validate_template_channel_match(
                test_db,
                org_id=org_id,
                campaign_channel=ConversationChannel.email,
                template_ids=[wa_template.id],
            )
        assert info.value.status_code == 422
        assert "whatsapp" in info.value.detail.lower()
    finally:
        reset_context(token)


async def test_validator_rejects_unknown_template_id(test_db, org_id):
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(HTTPException) as info:
            await campaigns_service._validate_template_channel_match(
                test_db,
                org_id=org_id,
                campaign_channel=ConversationChannel.email,
                template_ids=[uuid.uuid4()],
            )
        assert info.value.status_code == 422
        assert "not found" in info.value.detail.lower()
    finally:
        reset_context(token)


# --- A/B campaigns also validate both variants -------------------------


async def test_validator_accepts_matching_ab_variants(test_db, org_id):
    a = await _make_template(
        test_db,
        org_id=org_id,
        channel=ConversationChannel.whatsapp,
        name="WA-A",
    )
    b = await _make_template(
        test_db,
        org_id=org_id,
        channel=ConversationChannel.whatsapp,
        name="WA-B",
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        # No raise → pass.
        await campaigns_service._validate_template_channel_match(
            test_db,
            org_id=org_id,
            campaign_channel=ConversationChannel.whatsapp,
            template_ids=[a.id, b.id],
        )
    finally:
        reset_context(token)


async def test_validator_rejects_when_one_ab_variant_wrong_channel(
    test_db, org_id
):
    wa = await _make_template(
        test_db,
        org_id=org_id,
        channel=ConversationChannel.whatsapp,
        name="WA",
    )
    email = await _make_template(
        test_db,
        org_id=org_id,
        channel=ConversationChannel.email,
        name="EMAIL",
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        with pytest.raises(HTTPException) as info:
            await campaigns_service._validate_template_channel_match(
                test_db,
                org_id=org_id,
                campaign_channel=ConversationChannel.whatsapp,
                template_ids=[wa.id, email.id],
            )
        assert info.value.status_code == 422
        assert "email" in info.value.detail.lower()
    finally:
        reset_context(token)


# --- WA extension reverse lookup (campaigns DAL) -----------------------


async def test_wa_extension_lookup_returns_none_for_email(test_db, org_id):
    """Email templates have no WA extension row — the campaigns DAL
    returns None, signalling the dispatcher to use the central row's
    body directly (no Meta-template send path)."""
    from src.app.core.campaigns import data_access as campaigns_da

    email_t = await _make_template(
        test_db, org_id=org_id, channel=ConversationChannel.email
    )
    token = set_context(RequestContext(org_id=org_id))
    try:
        wa_row = (
            await campaigns_da.get_wa_extension_for_campaign_template(
                test_db, email_t.id
            )
        )
        assert wa_row is None
    finally:
        reset_context(token)
