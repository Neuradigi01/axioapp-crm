"""End-to-end CRUD + send-through-fake-adapter test.

`CHUNK_SIZE` is 50; we seed 120 contacts so the dispatch path
processes 3 chunks. A fake whatsapp adapter records every send call.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.contacts.models import Contact
from src.app.core.conversations.adapters import (
    ChannelMessageRef,
    InboundMessage,
)
from src.app.core.conversations.models import ConversationChannel
from src.app.core.conversations.registry import (
    list_registered,
    register_channel,
    unregister_channel,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission


class _FakeAdapter:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.fail = False

    async def send(self, *, org_id, external_id, text, attachments):
        if self.fail:
            raise RuntimeError("provider rejected the message")
        self.sent.append({"to": external_id, "text": text})
        return ChannelMessageRef(channel_message_id=f"FAKE-{len(self.sent)}")

    def parse_webhook(self, payload):
        return InboundMessage(
            external_id=str(payload.get("from", "")),
            text=str(payload.get("text", "")),
            raw=payload,
        )


@pytest.fixture(autouse=True)
def _register_fake_whatsapp():
    fake = _FakeAdapter()
    for ch in list(list_registered()):
        unregister_channel(ch)
    register_channel(ConversationChannel.whatsapp, lambda: fake)
    yield fake
    for ch in list(list_registered()):
        unregister_channel(ch)


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug, email, password) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_contacts(org_id: uuid.UUID, n: int) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for i in range(n):
            session.add(
                Contact(
                    org_id=org_id,
                    full_name=f"Contact {i:03d}",
                    phone=f"+9190000{i:05d}",
                    source="seed",
                    tags=["batch"],
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_create_start_chunks_processed(layered_client, seeded_admin, _register_fake_whatsapp):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "campaigns.read",
        "campaigns.write",
        "campaigns.send",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    await _seed_contacts(org.id, 120)

    create = await layered_client.post(
        "/api/v1/campaigns",
        json={
            "name": "Diwali Promo",
            "channel": "whatsapp",
            "audience_filter": {"tag": "batch"},
            "template": "Hi {{full_name}} — 20% off this week!",
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]

    start = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["audience_size"] == 120
    # 120 contacts / chunk_size 50 = 3 chunks
    assert body["chunks_enqueued"] == 3
    assert body["status"] == "running"

    # Adapter received 120 sends, each with the personalised template.
    assert len(_register_fake_whatsapp.sent) == 120
    first_sent_text = _register_fake_whatsapp.sent[0]["text"]
    assert first_sent_text.startswith("Hi Contact ")
    assert "20% off" in first_sent_text

    # Stats reflect 120 sent rows.
    stats = await layered_client.get(f"/api/v1/campaigns/{cid}/stats", headers=headers)
    assert stats.status_code == 200
    s = stats.json()
    assert s["audience_size"] == 120
    assert s["sent"] == 120
    assert s["queued"] == 0
    assert s["failed"] == 0

    # Campaign flipped to `done`.
    detail = await layered_client.get(f"/api/v1/campaigns/{cid}", headers=headers)
    assert detail.json()["status"] == "done"


@pytest.mark.asyncio
async def test_start_with_empty_audience_marks_done_with_zero(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "campaigns.read",
        "campaigns.write",
        "campaigns.send",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/campaigns",
        json={
            "name": "No-one match",
            "channel": "whatsapp",
            "audience_filter": {"source": "does-not-exist"},
            "template": "Hello",
        },
        headers=headers,
    )
    cid = create.json()["id"]

    start = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert start.status_code == 200
    body = start.json()
    assert body["audience_size"] == 0
    assert body["chunks_enqueued"] == 0
    assert body["status"] == "done"


@pytest.mark.asyncio
async def test_cannot_start_unregistered_channel(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "campaigns.read",
        "campaigns.write",
        "campaigns.send",
    )
    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}

    create = await layered_client.post(
        "/api/v1/campaigns",
        json={
            "name": "Bad channel",
            "channel": "sms",  # no adapter registered for sms
            "audience_filter": {},
            "template": "Hi",
        },
        headers=headers,
    )
    cid = create.json()["id"]
    start = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert start.status_code == 400, start.text
    assert "sms" in start.json().get("message", start.json().get("detail", ""))


async def _admin_headers(layered_client, seeded_admin) -> dict[str, str]:
    await _grant(
        seeded_admin["role"].id,
        "campaigns.read",
        "campaigns.write",
        "campaigns.send",
    )
    token = await _login(
        layered_client,
        org_slug=seeded_admin["org"].slug,
        email=seeded_admin["user"].email,
        password=seeded_admin["password"],
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_batch_campaign(layered_client, headers, **extra) -> str:
    create = await layered_client.post(
        "/api/v1/campaigns",
        json={
            "name": "Batch",
            "channel": "whatsapp",
            "audience_filter": {"tag": "batch"},
            "template": "Hi {{full_name}}",
            **extra,
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    return create.json()["id"]


@pytest.mark.asyncio
async def test_all_failed_campaign_settles_failed_then_retry_resends(
    layered_client, seeded_admin, _register_fake_whatsapp
):
    headers = await _admin_headers(layered_client, seeded_admin)
    await _seed_contacts(seeded_admin["org"].id, 3)
    cid = await _create_batch_campaign(layered_client, headers)

    _register_fake_whatsapp.fail = True
    start = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert start.status_code == 200, start.text
    detail = await layered_client.get(f"/api/v1/campaigns/{cid}", headers=headers)
    assert detail.json()["status"] == "failed"

    _register_fake_whatsapp.fail = False
    retry = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert retry.status_code == 200, retry.text
    assert len(_register_fake_whatsapp.sent) == 3
    stats = (await layered_client.get(f"/api/v1/campaigns/{cid}/stats", headers=headers)).json()
    assert stats["sent"] == 3
    assert stats["failed"] == 0
    detail = await layered_client.get(f"/api/v1/campaigns/{cid}", headers=headers)
    assert detail.json()["status"] == "done"


@pytest.mark.asyncio
async def test_redispatching_a_finished_chunk_sends_nothing(
    layered_client, seeded_admin, _register_fake_whatsapp
):
    from sqlalchemy import select

    from src.app.core.campaigns import service as campaigns_service
    from src.app.core.campaigns.models import CampaignMessage
    from src.app.shared.context import RequestContext, reset_context, set_context
    from tests.conftest import TestSession

    headers = await _admin_headers(layered_client, seeded_admin)
    await _seed_contacts(seeded_admin["org"].id, 3)
    cid = await _create_batch_campaign(layered_client, headers)
    start = await layered_client.post(f"/api/v1/campaigns/{cid}/start", headers=headers)
    assert start.status_code == 200, start.text
    assert len(_register_fake_whatsapp.sent) == 3

    token = set_context(RequestContext(org_id=seeded_admin["org"].id, user_id=None))
    try:
        async with TestSession() as session:
            contact_ids = (
                (
                    await session.execute(
                        select(CampaignMessage.contact_id).where(
                            CampaignMessage.campaign_id == uuid.UUID(cid)
                        )
                    )
                )
                .scalars()
                .all()
            )
            await campaigns_service.dispatch_chunk(
                session, campaign_id=uuid.UUID(cid), contact_ids=list(contact_ids)
            )
    finally:
        reset_context(token)
    assert len(_register_fake_whatsapp.sent) == 3


@pytest.mark.asyncio
async def test_scheduled_campaign_fires_once_when_due(
    layered_client, seeded_admin, _register_fake_whatsapp
):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from src.app.core.campaigns import service as campaigns_service
    from src.app.core.campaigns.models import Campaign
    from src.app.shared.context import RequestContext, reset_context, set_context
    from tests.conftest import TestSession

    headers = await _admin_headers(layered_client, seeded_admin)
    await _seed_contacts(seeded_admin["org"].id, 3)
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    cid = await _create_batch_campaign(layered_client, headers, schedule_at=future)

    # A future schedule arms the campaign on create — nothing sent yet.
    detail = await layered_client.get(f"/api/v1/campaigns/{cid}", headers=headers)
    assert detail.json()["status"] == "scheduled"
    assert _register_fake_whatsapp.sent == []

    token = set_context(RequestContext(org_id=seeded_admin["org"].id, user_id=None))
    try:
        async with TestSession() as session:
            await session.execute(
                update(Campaign)
                .where(Campaign.id == uuid.UUID(cid))
                .values(schedule_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await session.commit()
            first = await campaigns_service.start_scheduled_campaign(
                session, campaign_id=uuid.UUID(cid)
            )
            second = await campaigns_service.start_scheduled_campaign(
                session, campaign_id=uuid.UUID(cid)
            )
    finally:
        reset_context(token)

    assert first is True
    assert second is False
    assert len(_register_fake_whatsapp.sent) == 3
    detail = await layered_client.get(f"/api/v1/campaigns/{cid}", headers=headers)
    assert detail.json()["status"] == "done"
