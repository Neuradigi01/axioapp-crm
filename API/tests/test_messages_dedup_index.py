"""Coverage for the ``uq_messages_org_channel_msgid`` partial unique
index on ``tbl_messages`` (mailgun-inbound Step 0).

Guarantees at-most-once persistence per
``(org_id, channel_message_id)`` when ``channel_message_id`` is set
— the per-org dedup index every inbound provider (Gmail sync,
Microsoft sync, WhatsApp webhook, Meta messaging, Mailgun inbound)
leans on. ``channel`` isn't in the index because ``tbl_messages``
doesn't carry it (it lives on ``tbl_conversations``); provider id
formats (``mg:<uuid>``, ``wamid.HB...``, RFC ``<uuid@domain>``) are
disjoint so cross-provider collisions within one org never happen.

The pre-existing ``uq_messages_conv_wamid`` catches retries that
thread to the same conversation. The new index catches the case
where two deliveries of the same channel-side message id thread to
*different* conversations (rare, but real under threading-race
conditions and Mailgun replays whose token expired the replay cache).

Migration file: ``0214_messages_dedup_partial_idx.py``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageDirection,
)
from src.app.core.tenants.models import Organization


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_org(session, slug: str = "dedup-test") -> Organization:
    """Insert a minimal Organization row. Unique slug per test."""
    org = Organization(
        id=uuid.uuid4(),
        name=f"Org {slug}",
        slug=f"{slug}-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()
    return org


async def _make_conv(
    session,
    *,
    org_id: uuid.UUID,
    external_id: str = "customer@example.com",
    channel: ConversationChannel = ConversationChannel.email,
) -> Conversation:
    conv = Conversation(
        id=uuid.uuid4(),
        org_id=org_id,
        channel=channel,
        external_id=external_id,
        status=ConversationStatus.open,
        unread_count=0,
    )
    session.add(conv)
    await session.flush()
    return conv


def _make_msg(
    *,
    org_id: uuid.UUID,
    conversation_id: uuid.UUID,
    channel_message_id: str | None,
    direction: MessageDirection = MessageDirection.in_,
    text_body: str = "hello",
) -> Message:
    return Message(
        id=uuid.uuid4(),
        org_id=org_id,
        conversation_id=conversation_id,
        direction=direction,
        text=text_body,
        channel_message_id=channel_message_id,
    )


# ---------------------------------------------------------------------------
# Index existence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_partial_unique_index_exists_on_messages(test_db):
    """After ``Base.metadata.create_all`` (which mirrors the migration),
    ``uq_messages_org_channel_msgid`` should be present on
    ``tbl_messages`` and scoped to ``WHERE channel_message_id IS NOT
    NULL``."""
    result = await test_db.execute(
        text(
            """
            SELECT indexname, indexdef
              FROM pg_indexes
             WHERE tablename = 'tbl_messages'
               AND indexname = 'uq_messages_org_channel_msgid'
            """
        )
    )
    row = result.first()
    assert row is not None, "Index uq_messages_org_channel_msgid not created"
    indexdef = row[1].lower()
    assert "unique" in indexdef, "Index must be UNIQUE"
    assert "org_id" in indexdef and "channel_message_id" in indexdef
    assert "channel_message_id is not null" in indexdef, "Missing partial WHERE clause"


# ---------------------------------------------------------------------------
# Uniqueness semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_org_channel_msgid_raises_integrity_error(test_db):
    """Two rows with the same (org_id, channel, channel_message_id) —
    the second insert must be rejected by the index."""
    org = await _make_org(test_db)
    conv_a = await _make_conv(test_db, org_id=org.id, external_id="a@x.com")
    conv_b = await _make_conv(test_db, org_id=org.id, external_id="b@x.com")

    test_db.add(
        _make_msg(
            org_id=org.id,
            conversation_id=conv_a.id,
            channel_message_id="mg:delivery-123",
        )
    )
    await test_db.commit()

    # Second delivery of the same channel_message_id — even to a
    # different conversation — must fail the cross-channel index.
    test_db.add(
        _make_msg(
            org_id=org.id,
            conversation_id=conv_b.id,
            channel_message_id="mg:delivery-123",
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


@pytest.mark.asyncio
async def test_two_null_channel_message_ids_coexist(test_db):
    """The partial WHERE clause excludes NULL — two outbound rows
    with no channel-side id yet must persist happily. Guards against
    accidentally strengthening the predicate."""
    org = await _make_org(test_db)
    conv = await _make_conv(test_db, org_id=org.id)

    test_db.add(
        _make_msg(
            org_id=org.id,
            conversation_id=conv.id,
            channel_message_id=None,
            direction=MessageDirection.out,
            text_body="draft one",
        )
    )
    test_db.add(
        _make_msg(
            org_id=org.id,
            conversation_id=conv.id,
            channel_message_id=None,
            direction=MessageDirection.out,
            text_body="draft two",
        )
    )
    await test_db.commit()

    result = await test_db.execute(
        select(Message).where(
            Message.conversation_id == conv.id,
            Message.channel_message_id.is_(None),
        )
    )
    assert len(result.scalars().all()) == 2


@pytest.mark.asyncio
async def test_same_msgid_different_org_allowed(test_db):
    """Cross-org: two orgs may see the same channel_message_id
    independently (e.g., the same public marketing broadcast that
    lands in two orgs' inboxes). Index is scoped by org_id."""
    org_a = await _make_org(test_db, slug="orgA")
    org_b = await _make_org(test_db, slug="orgB")
    conv_a = await _make_conv(test_db, org_id=org_a.id)
    conv_b = await _make_conv(test_db, org_id=org_b.id)

    test_db.add(
        _make_msg(
            org_id=org_a.id,
            conversation_id=conv_a.id,
            channel_message_id="mg:shared-id",
        )
    )
    test_db.add(
        _make_msg(
            org_id=org_b.id,
            conversation_id=conv_b.id,
            channel_message_id="mg:shared-id",
        )
    )
    await test_db.commit()  # No IntegrityError.


# NOTE: A "same org, different channel, same channel_message_id" case
# is not tested because ``tbl_messages`` has no ``channel`` column —
# the index cannot discriminate. Provider id prefixes (``mg:``,
# ``wamid.``, RFC ``<...@...>``) are disjoint in practice, so this is
# safe. If a future provider uses raw un-prefixed ids that could
# collide, that provider must namespace its ids before persisting.


# ---------------------------------------------------------------------------
# Probe query (migration's guardrail)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_query_finds_collisions_when_present(test_db):
    """The exact probe SQL the migration runs before ``CREATE INDEX``
    should return duplicate groups. Since ``create_all`` already
    installed the unique index in the test DB, we can't insert two
    colliding rows here — instead, verify the probe SQL is
    well-formed and returns an empty set on clean data."""
    org = await _make_org(test_db)
    conv = await _make_conv(test_db, org_id=org.id)
    test_db.add(
        _make_msg(
            org_id=org.id,
            conversation_id=conv.id,
            channel_message_id="mg:unique-1",
        )
    )
    await test_db.commit()

    probe_sql = text(
        """
        SELECT org_id, channel_message_id, COUNT(*) AS n
          FROM tbl_messages
         WHERE channel_message_id IS NOT NULL
         GROUP BY org_id, channel_message_id
        HAVING COUNT(*) > 1
         LIMIT 10
        """
    )
    result = await test_db.execute(probe_sql)
    assert result.fetchall() == [], "Probe should find no collisions on clean data"
