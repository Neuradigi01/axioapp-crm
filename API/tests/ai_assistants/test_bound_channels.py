"""Tests for ``bound_channels`` on ``tbl_ai_assistants``
(``tasks/ai-assistants-omnichannel`` Step 1).

Covers Pydantic enum validation, the service's channel-conflict
pre-flight, and DB defaults / persistence. Skipped when the compose
stack isn't up (DB env vars absent).
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
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
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


async def _pick_two_orgs(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID] | None:
    result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 2"))
    rows = [uuid.UUID(str(r[0])) for r in result.fetchall()]
    return (rows[0], rows[1]) if len(rows) >= 2 else None


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


async def _insert_assistant(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    name: str,
    status_: str = "active",
    bound_channels: list[str] | None = None,
) -> uuid.UUID:
    aid = uuid.uuid4()
    import json

    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_assistants
                (id, org_id, name, status, key_id, model, temperature,
                 stop_keywords, allowed_domains, output_sanitizer_enabled,
                 version, bound_channels)
            VALUES (:id, :org, :name, :st, :kid, 'gpt-4o-mini', 0.5,
                    '{}'::text[], '{}'::text[], true, 1, CAST(:bc AS jsonb))
            """
        ),
        {
            "id": str(aid),
            "org": str(org_id),
            "name": name,
            "st": status_,
            "kid": str(key_id),
            "bc": json.dumps(bound_channels or []),
        },
    )
    return aid


async def _cleanup(
    session: AsyncSession, *, org_ids: list[uuid.UUID], key_ids: list[uuid.UUID]
) -> None:
    for oid in org_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_assistants WHERE org_id = :o"),
            {"o": str(oid)},
        )
    for kid in key_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
            {"id": str(kid)},
        )
    await session.commit()


# --- Pure Pydantic tests (no DB) -----------------------------------------


def test_update_schema_accepts_bound_channels_enum_list() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate

    payload = AiAssistantUpdate(
        version=1,
        bound_channels=["ai_widget", "whatsapp", "email"],  # type: ignore[arg-type]
    )
    assert [c.value for c in (payload.bound_channels or [])] == [
        "ai_widget",
        "whatsapp",
        "email",
    ]


def test_update_schema_rejects_unknown_channel() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate

    with pytest.raises(Exception):
        AiAssistantUpdate(
            version=1,
            bound_channels=["nonsense_channel"],  # type: ignore[arg-type]
        )


def test_update_schema_bound_channels_defaults_to_none() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate

    payload = AiAssistantUpdate(version=1)
    assert payload.bound_channels is None


# --- Service + DB integration tests --------------------------------------


@pytest.fixture
def engine():  # type: ignore[no-untyped-def]
    url = _db_url()
    if url is None:
        pytest.skip("DB env vars absent — run inside the docker compose stack.")
    return create_async_engine(url, poolclass=NullPool)


async def test_new_assistant_has_empty_bound_channels(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants import data_access as _da

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key_ids: list[uuid.UUID] = []
    org_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        kid = await _insert_key(s, org_id=org, label="bc-empty")
        key_ids.append(kid)
        org_ids.append(org)
        aid = await _insert_assistant(
            s, org_id=org, key_id=kid, name=f"bc-empty-{uuid.uuid4().hex[:8]}"
        )
        await s.commit()

        row = await _da.get_assistant_by_id(s, aid)
        assert row is not None
        assert row.bound_channels == []

        await _cleanup(s, org_ids=org_ids, key_ids=key_ids)


async def test_bound_channels_conflict_rejects_second_bind(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate
    from src.app.core.ai_assistants.service import update_assistant

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key_ids: list[uuid.UUID] = []
    org_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        k1 = await _insert_key(s, org_id=org, label="bc-c1")
        k2 = await _insert_key(s, org_id=org, label="bc-c2")
        key_ids.extend([k1, k2])
        org_ids.append(org)
        a1 = await _insert_assistant(
            s,
            org_id=org,
            key_id=k1,
            name=f"bc-first-{uuid.uuid4().hex[:8]}",
            bound_channels=["whatsapp"],
        )
        a2 = await _insert_assistant(
            s, org_id=org, key_id=k2, name=f"bc-second-{uuid.uuid4().hex[:8]}"
        )
        await s.commit()

        with pytest.raises(HTTPException) as exc_info:
            await update_assistant(
                s,
                org_id=org,
                user_id=None,
                assistant_id=a2,
                payload=AiAssistantUpdate(
                    version=1,
                    bound_channels=["whatsapp"],  # type: ignore[arg-type]
                ),
            )
        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert isinstance(detail, dict)
        assert detail["reason"] == "channel_already_bound"
        assert detail["channel"] == "whatsapp"
        assert detail["other_assistant_id"] == str(a1)

        await _cleanup(s, org_ids=org_ids, key_ids=key_ids)


async def test_bound_channels_conflict_ignores_archived(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate
    from src.app.core.ai_assistants.service import update_assistant

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key_ids: list[uuid.UUID] = []
    org_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        k1 = await _insert_key(s, org_id=org, label="bc-ac1")
        k2 = await _insert_key(s, org_id=org, label="bc-ac2")
        key_ids.extend([k1, k2])
        org_ids.append(org)
        # First assistant binds whatsapp but is ARCHIVED — should not conflict.
        await _insert_assistant(
            s,
            org_id=org,
            key_id=k1,
            name=f"bc-arch-{uuid.uuid4().hex[:8]}",
            status_="archived",
            bound_channels=["whatsapp"],
        )
        a2 = await _insert_assistant(
            s, org_id=org, key_id=k2, name=f"bc-live-{uuid.uuid4().hex[:8]}"
        )
        await s.commit()

        # This should succeed — the archived assistant doesn't count.
        row = await update_assistant(
            s,
            org_id=org,
            user_id=None,
            assistant_id=a2,
            payload=AiAssistantUpdate(
                version=1,
                bound_channels=["whatsapp"],  # type: ignore[arg-type]
            ),
        )
        assert row.bound_channels == ["whatsapp"]

        await _cleanup(s, org_ids=org_ids, key_ids=key_ids)


async def test_bound_channels_conflict_ignores_self(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate
    from src.app.core.ai_assistants.service import update_assistant

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key_ids: list[uuid.UUID] = []
    org_ids: list[uuid.UUID] = []
    async with Session() as s:
        org = await _pick_org(s)
        if org is None:
            pytest.skip("No orgs in DB.")
        await _set_rls(s, org)
        k1 = await _insert_key(s, org_id=org, label="bc-self")
        key_ids.append(k1)
        org_ids.append(org)
        a1 = await _insert_assistant(
            s,
            org_id=org,
            key_id=k1,
            name=f"bc-self-{uuid.uuid4().hex[:8]}",
            bound_channels=["whatsapp"],
        )
        await s.commit()

        # Re-save with the SAME binding — no conflict.
        row = await update_assistant(
            s,
            org_id=org,
            user_id=None,
            assistant_id=a1,
            payload=AiAssistantUpdate(
                version=1,
                bound_channels=["whatsapp"],  # type: ignore[arg-type]
            ),
        )
        assert row.bound_channels == ["whatsapp"]

        await _cleanup(s, org_ids=org_ids, key_ids=key_ids)


async def test_bound_channels_cross_org_no_conflict(engine) -> None:  # type: ignore[no-untyped-def]
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate
    from src.app.core.ai_assistants.service import update_assistant

    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    key_ids: list[uuid.UUID] = []
    org_ids: list[uuid.UUID] = []
    async with Session() as s:
        orgs = await _pick_two_orgs(s)
        if orgs is None:
            pytest.skip("Fewer than 2 orgs in DB.")
        org_a, org_b = orgs
        org_ids.extend([org_a, org_b])

        await _set_rls(s, org_a)
        k_a = await _insert_key(s, org_id=org_a, label="bc-xa")
        key_ids.append(k_a)
        await _insert_assistant(
            s,
            org_id=org_a,
            key_id=k_a,
            name=f"bc-xa-{uuid.uuid4().hex[:8]}",
            bound_channels=["whatsapp"],
        )
        await s.commit()

        # Switch RLS to org B; org A's binding must NOT block org B.
        await _set_rls(s, org_b)
        k_b = await _insert_key(s, org_id=org_b, label="bc-xb")
        key_ids.append(k_b)
        a_b = await _insert_assistant(
            s, org_id=org_b, key_id=k_b, name=f"bc-xb-{uuid.uuid4().hex[:8]}"
        )
        await s.commit()

        row = await update_assistant(
            s,
            org_id=org_b,
            user_id=None,
            assistant_id=a_b,
            payload=AiAssistantUpdate(
                version=1,
                bound_channels=["whatsapp"],  # type: ignore[arg-type]
            ),
        )
        assert row.bound_channels == ["whatsapp"]

        await _cleanup(s, org_ids=org_ids, key_ids=key_ids)
