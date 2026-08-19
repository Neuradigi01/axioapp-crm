"""Analytics DAL + service tests
(``tasks/ai-assistants`` Step 16).

Pure-Python + DB-dependent. The DB tests skip when the compose
stack isn't up. Covers:

  * Window-days clamping (rejects out-of-range values silently).
  * Empty-data path returns 0 count + $0 cost + empty top-questions.
  * ``LOWER(TRIM(text))`` grouping: "Hi" and "hi " land in the
    same bucket.
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _install_kek_before_crypto_import() -> None:
    """Set AI_PROVIDER_KEY_KEK BEFORE any transitive import fires
    ``crypto.py``'s module-level ``from config import AI_PROVIDER_KEY_KEK``.

    ``chatbots.models`` (imported below for FK metadata) transitively
    pulls in ``integrations.ai.crypto`` which binds its
    ``AI_PROVIDER_KEY_KEK`` name at import time. If we DON'T install
    a KEK first, crypto binds to empty — and no later
    ``config.AI_PROVIDER_KEY_KEK = ...`` in a downstream test file
    can undo that stale binding without also patching
    ``crypto.AI_PROVIDER_KEY_KEK`` directly.
    """
    if not os.environ.get("AI_PROVIDER_KEY_KEK"):
        os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode()
    import config as app_config

    app_config.AI_PROVIDER_KEY_KEK = os.environ["AI_PROVIDER_KEY_KEK"]


_install_kek_before_crypto_import()

# Side-effect imports so FK metadata resolves. The chatbots +
# conversations models are needed for the messages FK graph the
# analytics test builds a conversation into.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.chatbots.models  # noqa: F401,E402
import src.app.core.contacts.models  # noqa: F401,E402
import src.app.core.conversations.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402
import src.app.core.users.models  # noqa: F401,E402


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


async def _insert_key(session: AsyncSession, *, org_id: uuid.UUID, label: str) -> uuid.UUID:
    kid = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_provider_keys
                (id, org_id, provider, label, encrypted_key, nonce,
                 key_version, fingerprint_sha256, last4, test_status)
            VALUES (:id, :org, 'openai', :label,
                    :ct, :nn, 1, :fp, 'test', 'untested')
            """
        ),
        {
            "id": str(kid),
            "org": str(org_id),
            "label": label,
            "ct": secrets.token_bytes(64),
            "nn": secrets.token_bytes(12),
            "fp": secrets.token_bytes(32),
        },
    )
    return kid


async def _cleanup(session: AsyncSession, *, key_ids: list[uuid.UUID]) -> None:
    await session.execute(
        text("DELETE FROM tbl_ai_assistants WHERE key_id = ANY(:k)"),
        {"k": [str(k) for k in key_ids]},
    )
    for kid in key_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
            {"id": str(kid)},
        )
    await session.commit()


# --- Pure-Python bounds ---------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_clamps_window_out_of_range(monkeypatch) -> None:
    """The service clamps ``window_days`` to [1, 365] before hitting
    the DAL. Uses ``monkeypatch`` so the fake DAL doesn't leak into
    later tests that hit the real one."""
    from src.app.core.ai_assistants import (
        data_access as _da_module,
    )
    from src.app.core.ai_assistants import (
        service as ai_service,
    )

    captured: dict[str, int] = {}

    async def _fake_get_assistant(*args, **kwargs):
        return None

    async def _fake_msg_cost(db, *, org_id, assistant_id, window_days):
        captured["window"] = window_days
        return 0, "0"

    async def _fake_top(db, *, org_id, assistant_id, window_days, limit):
        return []

    monkeypatch.setattr(ai_service, "get_assistant", _fake_get_assistant)
    monkeypatch.setattr(_da_module, "analytics_message_and_cost", _fake_msg_cost)
    monkeypatch.setattr(_da_module, "analytics_top_questions", _fake_top)

    await ai_service.get_analytics(
        None,  # type: ignore[arg-type]
        org_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        window_days=99999,
    )
    assert captured["window"] == 365

    await ai_service.get_analytics(
        None,  # type: ignore[arg-type]
        org_id=uuid.uuid4(),
        assistant_id=uuid.uuid4(),
        window_days=-5,
    )
    assert captured["window"] == 1


# --- End-to-end DAL against real DB ---------------------------------------


async def test_analytics_empty_data_returns_zero() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import data_access as _da

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        org = await _pick_org(session)
        if org is None:
            await engine.dispose()
            pytest.skip("No organization to test against")
        await _set_rls(session, org)
        # Never-seen assistant id — analytics returns 0 count + "0" cost.
        n, cost = await _da.analytics_message_and_cost(
            session, org_id=org, assistant_id=uuid.uuid4(), window_days=30
        )
        assert n == 0
        assert Decimal(cost) == Decimal("0")

        top = await _da.analytics_top_questions(
            session, org_id=org, assistant_id=uuid.uuid4(), window_days=30
        )
        assert top == []
    await engine.dispose()


async def test_analytics_top_questions_groups_case_insensitively() -> None:
    """Insert two conversations + user messages with mixed case/whitespace;
    the DAL's ``LOWER(TRIM(text))`` GROUP BY collapses them."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import data_access as _da
    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    keys: list[uuid.UUID] = []
    async with Session() as session:
        org = await _pick_org(session)
        if org is None:
            await engine.dispose()
            pytest.skip("No organization to test against")
        await _set_rls(session, org)
        kid = await _insert_key(session, org_id=org, label="analytics-smoke")
        keys.append(kid)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        try:
            await _set_rls(session, org)
            uniq = uuid.uuid4().hex[:8]
            assistant = await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=f"analytics-{uniq}",
                    key_id=kid,
                    model="gpt-4o-mini",
                ),
            )

            # Create one conversation for this assistant + one assistant
            # reply + one message_meta row + two user messages (mixed
            # case) so the top-questions query finds them via the
            # message_meta → conversation JOIN.
            conv_id = await _da.create_ai_widget_conversation(
                session, org_id=org, external_id=f"analytics-conv-{uniq}"
            )
            asst_msg_id = await _da.insert_assistant_message(
                session, org_id=org, conversation_id=conv_id, text_body="hi!"
            )
            await _da.insert_message_meta_pending(
                session,
                message_id=asst_msg_id,
                org_id=org,
                assistant_id=assistant.id,
                model="gpt-4o-mini",
            )
            await _da.update_message_meta_confirmed(
                session,
                message_id=asst_msg_id,
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                cost_usd=Decimal("0.001"),
                retrieved_chunk_ids=[],
            )
            await _da.insert_user_message(
                session, org_id=org, conversation_id=conv_id, text_body="Hi"
            )
            await _da.insert_user_message(
                session, org_id=org, conversation_id=conv_id, text_body="  hi "
            )
            await _da.insert_user_message(
                session, org_id=org, conversation_id=conv_id, text_body="hello?"
            )
            await session.commit()

            n, cost = await _da.analytics_message_and_cost(
                session, org_id=org, assistant_id=assistant.id, window_days=30
            )
            assert n == 1
            assert Decimal(cost) == Decimal("0.001")

            top = await _da.analytics_top_questions(
                session, org_id=org, assistant_id=assistant.id, window_days=30
            )
            # Two "hi" variants should collapse to one row with count 2;
            # "hello?" is its own row with count 1.
            top_by_norm = {row["normalized"]: row["count"] for row in top}
            assert top_by_norm.get("hi") == 2
            assert top_by_norm.get("hello?") == 1
        finally:
            reset_context(tok)
            await _cleanup(session, key_ids=keys)
    await engine.dispose()
