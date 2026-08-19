"""End-to-end reassign + count-by-key smoke tests.

Exercises Step 1's ``reassign_provider_key`` service now that
Step 5 has wired the DAL stubs to real ``tbl_ai_assistants`` bulk
UPDATEs. Uses the container's DB directly; skips if the env vars
aren't present (dev running host Python without compose up).

The full HTTP-router / RBAC / cross-org 404 flows for the
assistants module land in Step 6's test suite; this file focuses
on the Step-5-completes-Step-1 wiring.
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Side-effect imports — pull the FK-target model classes into
# Base.metadata so query compilation can resolve
# `tbl_ai_provider_keys.org_id → tbl_organizations.id` and
# `tbl_ai_assistants.key_id → tbl_ai_provider_keys.id`. Without
# these, SQLAlchemy raises NoReferencedTableError at the first
# ORM statement.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402

pytestmark = pytest.mark.asyncio


def _install_kek_for_test() -> None:
    """Ensure the AES-GCM KEK is available for the crypto module."""
    if os.environ.get("AI_PROVIDER_KEY_KEK"):
        return
    os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode()
    import config as app_config

    app_config.AI_PROVIDER_KEY_KEK = os.environ["AI_PROVIDER_KEY_KEK"]


_install_kek_for_test()


def _async_db_url() -> str | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


async def _set_rls_context(session: AsyncSession, org_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": str(org_id)},
    )


async def _insert_provider_key(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    label: str,
) -> uuid.UUID:
    """Insert a minimal ``tbl_ai_provider_keys`` row so an assistant
    row can FK to it. Bypasses the service to avoid Step 1's dedup
    unique constraint (each label gets fresh fingerprint bytes)."""
    key_id = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_provider_keys
                (id, org_id, provider, label, encrypted_key, nonce,
                 key_version, fingerprint_sha256, last4, test_status)
            VALUES (:id, :org_id, 'openai', :label,
                    :ciphertext, :nonce, 1, :fingerprint, 'test', 'untested')
            """
        ),
        {
            "id": str(key_id),
            "org_id": str(org_id),
            "label": label,
            "ciphertext": secrets.token_bytes(64),
            "nonce": secrets.token_bytes(12),
            "fingerprint": secrets.token_bytes(32),
        },
    )
    return key_id


async def _insert_assistant(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    key_id: uuid.UUID,
    name: str,
) -> uuid.UUID:
    aid = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_assistants
                (id, org_id, name, status, key_id, model)
            VALUES (:id, :org_id, :name, 'draft', :key_id, 'gpt-4o-mini')
            """
        ),
        {
            "id": str(aid),
            "org_id": str(org_id),
            "name": name,
            "key_id": str(key_id),
        },
    )
    return aid


async def _cleanup(
    session: AsyncSession,
    *,
    assistant_ids: list[uuid.UUID],
    key_ids: list[uuid.UUID],
) -> None:
    for aid in assistant_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_assistants WHERE id = :id"),
            {"id": str(aid)},
        )
    for kid in key_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
            {"id": str(kid)},
        )
    await session.commit()


async def test_count_and_reassign_wired_end_to_end() -> None:
    url = _async_db_url()
    if not url:
        pytest.skip("DB env vars not set")

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from src.app.core.integrations.ai import data_access as ai_da
    from src.app.core.integrations.ai import service as ai_service
    from src.app.core.integrations.ai.schemas import AiProviderKeyReassign
    from src.app.shared.context import RequestContext, reset_context, set_context

    async with sessionmaker() as session:
        # Grab any existing org — need real FK targets.
        result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 1"))
        org_row = result.scalar_one_or_none()
        if org_row is None:
            await engine.dispose()
            pytest.skip("No organizations in DB to test against")
        org_id = uuid.UUID(str(org_row))

        # --- Setup ---------------------------------------------------
        await _set_rls_context(session, org_id)
        key_a = await _insert_provider_key(session, org_id=org_id, label="test-reassign-A")
        key_b = await _insert_provider_key(session, org_id=org_id, label="test-reassign-B")
        assistants: list[uuid.UUID] = []
        for i in range(3):
            aid = await _insert_assistant(
                session,
                org_id=org_id,
                key_id=key_a,
                name=f"reassign-smoke-{uuid.uuid4().hex[:8]}-{i}",
            )
            assistants.append(aid)
        await session.commit()

        # Set request-context org so TenantScoped auto-filter fires.
        _ctx_token = set_context(RequestContext(org_id=org_id))
        try:
            # --- count via Step 1 DAL wrapper (delegates to Step 5) ---
            await _set_rls_context(session, org_id)
            count_a = await ai_da.count_assistants_by_key_id(session, key_a)
            assert count_a == 3, f"expected 3 assistants pointing at key_a, got {count_a}"

            # --- reassign via Step 1's service — no more 501 ----------
            rowcount = await ai_service.reassign_provider_key(
                session,
                org_id=org_id,
                payload=AiProviderKeyReassign(from_key_id=key_a, to_key_id=key_b),
            )
            assert rowcount == 3

            # After the service commit, re-set RLS + re-count.
            await _set_rls_context(session, org_id)
            count_a_after = await ai_da.count_assistants_by_key_id(session, key_a)
            count_b_after = await ai_da.count_assistants_by_key_id(session, key_b)
            assert count_a_after == 0, "reassign did not clear key_a"
            assert count_b_after == 3, "reassign did not populate key_b"

            # --- Delete key_a should now succeed (0 references) -------
            await ai_service.delete_provider_key(session, org_id=org_id, key_id=key_a)

            # --- Teardown --------------------------------------------
            await _set_rls_context(session, org_id)
            await _cleanup(session, assistant_ids=assistants, key_ids=[key_b])
        finally:
            reset_context(_ctx_token)
            await engine.dispose()


async def test_reassign_cross_org_returns_404() -> None:
    """A key belonging to org B should return 404 when org A tries
    to reassign to it — the service's cross-org guard prevents any
    UPDATE from firing."""
    url = _async_db_url()
    if not url:
        pytest.skip("DB env vars not set")

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    from fastapi import HTTPException

    from src.app.core.integrations.ai import service as ai_service
    from src.app.core.integrations.ai.schemas import AiProviderKeyReassign
    from src.app.shared.context import RequestContext, reset_context, set_context

    async with sessionmaker() as session:
        result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 2"))
        rows = [uuid.UUID(str(r[0])) for r in result.fetchall()]
        if len(rows) < 2:
            await engine.dispose()
            pytest.skip("Need at least 2 organizations for cross-org test")
        org_a, org_b = rows[0], rows[1]

        await _set_rls_context(session, org_a)
        key_in_a = await _insert_provider_key(session, org_id=org_a, label="cross-a")
        await _set_rls_context(session, org_b)
        key_in_b = await _insert_provider_key(session, org_id=org_b, label="cross-b")
        await session.commit()

        _ctx_token = set_context(RequestContext(org_id=org_a))
        try:
            await _set_rls_context(session, org_a)
            with pytest.raises(HTTPException) as exc_info:
                await ai_service.reassign_provider_key(
                    session,
                    org_id=org_a,
                    payload=AiProviderKeyReassign(
                        from_key_id=key_in_a,
                        to_key_id=key_in_b,  # belongs to org_b — must 404
                    ),
                )
            assert exc_info.value.status_code == 404

            # Teardown — RLS scoped per row's org.
            await _set_rls_context(session, org_a)
            await session.execute(
                text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
                {"id": str(key_in_a)},
            )
            await _set_rls_context(session, org_b)
            await session.execute(
                text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
                {"id": str(key_in_b)},
            )
            await session.commit()
        finally:
            reset_context(_ctx_token)
            await engine.dispose()
