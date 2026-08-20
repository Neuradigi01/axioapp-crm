"""Tests for the AI pause / resume service
(``tasks/ai-assistants-omnichannel`` Step 3).

Service-level tests that exercise:
  * CAS pause + first-come-first-serve race semantics.
  * System-message insertion on both directions.
  * Holder-or-admin authorization on resume.
  * Cross-org RLS scoping.

Follows the same DB-live style as `tests/ai_assistants/test_bound_channels.py`
so the harness is minimal — skipped when compose env vars are absent.
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Side-effect imports so FK metadata resolves at query-compile time.
import src.app.core.conversations.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402


def _install_kek() -> None:
    if os.environ.get("AI_PROVIDER_KEY_KEK"):
        return
    os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    import config as app_config

    app_config.AI_PROVIDER_KEY_KEK = os.environ["AI_PROVIDER_KEY_KEK"]


_install_kek()


def _db_url() -> str | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


async def _set_rls(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :o, true)"),
        {"o": str(org_id)},
    )


async def _pick_org(session: AsyncSession) -> uuid.UUID | None:
    result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 1"))
    row = result.scalar_one_or_none()
    return uuid.UUID(str(row)) if row is not None else None


async def _pick_two_orgs(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID] | None:
    result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 2"))
    rows = [uuid.UUID(str(r[0])) for r in result.fetchall()]
    return (rows[0], rows[1]) if len(rows) >= 2 else None


async def _insert_conversation(session: AsyncSession, *, org_id: uuid.UUID) -> uuid.UUID:
    cid = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_conversations
                (id, org_id, channel, external_id, status, ai_handling, ai_paused,
                 unread_count, created_at)
            VALUES (:id, :org, 'whatsapp', :ext, 'open', false, false, 0, now())
            """
        ),
        {
            "id": str(cid),
            "org": str(org_id),
            "ext": f"+1555{uuid.uuid4().hex[:8]}",
        },
    )
    return cid


async def _cleanup(session: AsyncSession, *, conv_ids: list[uuid.UUID]) -> None:
    for cid in conv_ids:
        await session.execute(
            text("DELETE FROM tbl_messages WHERE conversation_id = :c"),
            {"c": str(cid)},
        )
        await session.execute(
            text("DELETE FROM tbl_conversations WHERE id = :c"),
            {"c": str(cid)},
        )
    await session.commit()


# --- Fixture ---------------------------------------------------------------


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    url = _db_url()
    if url is None:
        pytest.skip("DB env vars absent — run inside the docker compose stack.")
    return create_async_engine(url, poolclass=NullPool)


# --- Pause -----------------------------------------------------------------


async def test_pause_ai_on_unpaused_conversation(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        actor = uuid.uuid4()
        conv = await pause_ai(s, conversation_id=cid, actor_user_id=actor)
        assert conv.ai_paused is True
        assert conv.ai_paused_by_user_id == actor
        assert conv.ai_paused_at is not None

        # System marker message inserted.
        result = await s.execute(
            text(
                "SELECT text, payload->>'author', payload->>'event' "
                "FROM tbl_messages WHERE conversation_id = :c ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": str(cid)},
        )
        row = result.first()
        assert row is not None
        assert "took over from AI" in row[0]
        assert row[1] == "system"
        assert row[2] == "ai_paused"

        await _cleanup(s, conv_ids=conv_ids)


async def test_pause_ai_race_returns_409_with_holder(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        first = uuid.uuid4()
        await pause_ai(s, conversation_id=cid, actor_user_id=first)

        # Second call must lose.
        second = uuid.uuid4()
        with pytest.raises(HTTPException) as exc_info:
            await pause_ai(s, conversation_id=cid, actor_user_id=second)
        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["reason"] == "already_taken_over"
        assert detail["holder_user_id"] == str(first)

        await _cleanup(s, conv_ids=conv_ids)


# --- Resume ---------------------------------------------------------------


async def test_resume_ai_by_holder(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai, resume_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        holder = uuid.uuid4()
        await pause_ai(s, conversation_id=cid, actor_user_id=holder)
        conv = await resume_ai(
            s,
            conversation_id=cid,
            actor_user_id=holder,
            caller_is_admin=False,
        )
        assert conv.ai_paused is False
        assert conv.ai_paused_by_user_id is None
        assert conv.ai_paused_at is None

        # Marker inserted for resume.
        result = await s.execute(
            text(
                "SELECT payload->>'event' FROM tbl_messages "
                "WHERE conversation_id = :c ORDER BY created_at DESC LIMIT 1"
            ),
            {"c": str(cid)},
        )
        assert result.scalar_one() == "ai_resumed"

        await _cleanup(s, conv_ids=conv_ids)


async def test_resume_ai_by_non_holder_without_admin_forbidden(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai, resume_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        holder = uuid.uuid4()
        stranger = uuid.uuid4()
        await pause_ai(s, conversation_id=cid, actor_user_id=holder)
        with pytest.raises(HTTPException) as exc_info:
            await resume_ai(
                s,
                conversation_id=cid,
                actor_user_id=stranger,
                caller_is_admin=False,
            )
        assert exc_info.value.status_code == 403
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail["reason"] == "not_holder"

        await _cleanup(s, conv_ids=conv_ids)


async def test_resume_ai_by_non_holder_with_admin_allowed(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai, resume_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        holder = uuid.uuid4()
        admin = uuid.uuid4()
        await pause_ai(s, conversation_id=cid, actor_user_id=holder)
        conv = await resume_ai(
            s,
            conversation_id=cid,
            actor_user_id=admin,
            caller_is_admin=True,
        )
        assert conv.ai_paused is False

        await _cleanup(s, conv_ids=conv_ids)


async def test_resume_ai_on_unpaused_returns_409(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import resume_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        cid = await _insert_conversation(s, org_id=org)
        conv_ids.append(cid)
        await s.commit()

        with pytest.raises(HTTPException) as exc_info:
            await resume_ai(
                s,
                conversation_id=cid,
                actor_user_id=uuid.uuid4(),
                caller_is_admin=False,
            )
        assert exc_info.value.status_code == 409
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail["reason"] == "not_paused"

        await _cleanup(s, conv_ids=conv_ids)


# --- Cross-org isolation ---------------------------------------------------


async def test_pause_ai_cross_org_isolation(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.conversations.service import pause_ai

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    conv_ids: list[uuid.UUID] = []
    async with Session() as s:
        orgs = await _pick_two_orgs(s)
        if orgs is None:
            pytest.skip("Fewer than 2 orgs in DB.")
        org_a, org_b = orgs

        await _set_rls(s, org_a)
        cid_a = await _insert_conversation(s, org_id=org_a)
        conv_ids.append(cid_a)
        await s.commit()

        await _set_rls(s, org_b)
        cid_b = await _insert_conversation(s, org_id=org_b)
        conv_ids.append(cid_b)
        await s.commit()

        # Org A pauses its conversation.
        await _set_rls(s, org_a)
        await pause_ai(s, conversation_id=cid_a, actor_user_id=uuid.uuid4())

        # Org B pausing its own conversation still works — no cross-org
        # collision. Different conv_id, different org_id, both CAS win.
        await _set_rls(s, org_b)
        await pause_ai(s, conversation_id=cid_b, actor_user_id=uuid.uuid4())

        # Sanity: both rows are paused independently.
        result = await s.execute(
            text("SELECT id, ai_paused FROM tbl_conversations WHERE id = ANY(:ids)"),
            {"ids": [str(cid_a), str(cid_b)]},
        )
        rows = result.fetchall()
        assert len(rows) == 2
        assert all(r[1] for r in rows)

        # Cleanup: RLS the delete under each org.
        await _set_rls(s, org_a)
        await s.execute(
            text("DELETE FROM tbl_messages WHERE conversation_id = :c"),
            {"c": str(cid_a)},
        )
        await s.execute(
            text("DELETE FROM tbl_conversations WHERE id = :c"),
            {"c": str(cid_a)},
        )
        await _set_rls(s, org_b)
        await s.execute(
            text("DELETE FROM tbl_messages WHERE conversation_id = :c"),
            {"c": str(cid_b)},
        )
        await s.execute(
            text("DELETE FROM tbl_conversations WHERE id = :c"),
            {"c": str(cid_b)},
        )
        await s.commit()
