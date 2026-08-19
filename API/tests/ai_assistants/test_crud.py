"""End-to-end CRUD tests for the AI Assistants service.

Calls the service layer directly against the real DB (same pattern
as Step 5's reassign tests). This tests everything except the
FastAPI request/response envelope + auth dependency — those live
in ``test_rbac.py`` (permission dependency) and rely on the same
production dependency injection at runtime.

Skipped when the compose stack isn't up (DB env vars absent).
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Side-effect imports so FK metadata resolves at query-compile time.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402

# ``pytest-asyncio`` in ``asyncio_mode = "auto"`` (see
# pyproject.toml) treats every `async def test_...` as an asyncio
# test automatically — no `pytestmark` needed. Removing the
# `pytestmark = pytest.mark.asyncio` block that was here previously
# because it also applied to the sync Pydantic-shape tests and
# emitted a warning per each.


def _install_kek() -> None:
    if os.environ.get("AI_PROVIDER_KEY_KEK"):
        return
    os.environ["AI_PROVIDER_KEY_KEK"] = base64.urlsafe_b64encode(
        secrets.token_bytes(32)
    ).decode()
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
    # Assistants cascade knowledge/chunks/audit; message_meta SET NULL.
    # Keys have RESTRICT — must delete assistants first (or reassign).
    await session.execute(text("DELETE FROM tbl_ai_assistants WHERE key_id = ANY(:k)"), {"k": [str(k) for k in key_ids]})
    for kid in key_ids:
        await session.execute(
            text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
            {"id": str(kid)},
        )
    await session.commit()


# --- Mass-assignment defence (pure Pydantic) -----------------------------


def test_create_schema_rejects_org_id() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantCreate

    with pytest.raises(Exception):
        AiAssistantCreate(
            name="X",
            key_id=uuid.uuid4(),
            model="gpt-4o-mini",
            org_id=uuid.uuid4(),  # type: ignore[call-arg]
        )


def test_create_schema_rejects_forged_id_and_version() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantCreate

    for field in ("id", "version", "created_by_user_id", "status"):
        with pytest.raises(Exception):
            AiAssistantCreate(**{
                "name": "X",
                "key_id": uuid.uuid4(),
                "model": "gpt-4o-mini",
                field: "junk",
            })  # type: ignore[arg-type]


def test_update_schema_requires_version() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate

    with pytest.raises(Exception):
        AiAssistantUpdate(name="new name")  # type: ignore[call-arg]


def test_update_schema_rejects_disallowed_fields() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantUpdate

    for field in ("id", "org_id", "created_by_user_id", "status"):
        with pytest.raises(Exception):
            AiAssistantUpdate(**{"version": 1, field: "junk"})  # type: ignore[arg-type]


def test_temperature_bounds() -> None:
    from src.app.core.ai_assistants.schemas import AiAssistantCreate

    for bad in ("-0.1", "2.1", "10"):
        with pytest.raises(Exception):
            AiAssistantCreate(
                name="X",
                key_id=uuid.uuid4(),
                model="gpt-4o-mini",
                temperature=Decimal(bad),
            )
    ok = AiAssistantCreate(
        name="X",
        key_id=uuid.uuid4(),
        model="gpt-4o-mini",
        temperature=Decimal("1.5"),
    )
    assert ok.temperature == Decimal("1.5")


# --- End-to-end CRUD -----------------------------------------------------


async def test_create_read_update_archive_delete_end_to_end() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.schemas import (
        AiAssistantCreate,
        AiAssistantUpdate,
    )
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
        key = await _insert_key(session, org_id=org, label="crud-smoke")
        keys.append(key)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        try:
            await _set_rls(session, org)
            uniq = uuid.uuid4().hex[:8]
            # --- Create ---
            created = await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=f"crud-{uniq}",
                    key_id=key,
                    model="gpt-4o-mini",
                    temperature=Decimal("0.7"),
                    instructions="You help customers.",
                ),
            )
            assert created.version == 1
            assert created.status.value == "draft"
            assert created.temperature == Decimal("0.70")

            # Create-time audit row landed (instructions was set).
            await _set_rls(session, org)
            audit_rows = (
                await session.execute(
                    text(
                        "SELECT field_name, old_value, new_value FROM "
                        "tbl_ai_assistant_instruction_audit WHERE assistant_id = :a "
                        "ORDER BY changed_at"
                    ),
                    {"a": str(created.id)},
                )
            ).fetchall()
            assert len(audit_rows) == 1
            assert audit_rows[0][0] == "instructions"
            assert audit_rows[0][1] is None
            assert audit_rows[0][2] == "You help customers."

            # --- Read (happy path) ---
            await _set_rls(session, org)
            fetched = await ai_service.get_assistant(
                session, org_id=org, assistant_id=created.id
            )
            assert fetched.id == created.id

            # --- Update (bumps version + writes audit for instructions) ---
            updated = await ai_service.update_assistant(
                session,
                org_id=org,
                user_id=None,
                assistant_id=created.id,
                payload=AiAssistantUpdate(
                    version=1,
                    instructions="You are a friendly customer support agent.",
                    temperature=Decimal("0.3"),
                ),
            )
            assert updated.version == 2, f"version should have bumped to 2, got {updated.version}"
            assert updated.temperature == Decimal("0.30")
            assert updated.instructions == "You are a friendly customer support agent."

            await _set_rls(session, org)
            audit_after = (
                await session.execute(
                    text(
                        "SELECT field_name FROM tbl_ai_assistant_instruction_audit "
                        "WHERE assistant_id = :a ORDER BY changed_at"
                    ),
                    {"a": str(created.id)},
                )
            ).fetchall()
            fields_logged = [r[0] for r in audit_after]
            assert "instructions" in fields_logged  # from create + update
            assert "temperature" in fields_logged  # from update

            # --- OCC: stale version → 409 ---
            with pytest.raises(HTTPException) as exc:
                await ai_service.update_assistant(
                    session,
                    org_id=org,
                    user_id=None,
                    assistant_id=created.id,
                    payload=AiAssistantUpdate(version=1, name="different"),
                )
            assert exc.value.status_code == 409

            # --- Archive → status=archived ---
            await _set_rls(session, org)
            await ai_service.archive_assistant(
                session, org_id=org, assistant_id=created.id
            )
            await _set_rls(session, org)
            after_archive = await ai_service.get_assistant(
                session, org_id=org, assistant_id=created.id
            )
            assert after_archive.status.value == "archived"

            # --- Delete → row + cascaded audit rows gone ---
            await ai_service.delete_assistant(
                session, org_id=org, assistant_id=created.id
            )
            with pytest.raises(HTTPException) as exc:
                await _set_rls(session, org)
                await ai_service.get_assistant(
                    session, org_id=org, assistant_id=created.id
                )
            assert exc.value.status_code == 404

            await _set_rls(session, org)
            remaining_audit = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM tbl_ai_assistant_instruction_audit "
                        "WHERE assistant_id = :a"
                    ),
                    {"a": str(created.id)},
                )
            ).scalar_one()
            assert remaining_audit == 0, "audit rows should cascade-delete"
        finally:
            reset_context(tok)
            await _set_rls(session, org)
            await _cleanup(session, key_ids=keys)
            await engine.dispose()


async def test_create_with_cross_org_key_returns_404() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    keys: list[uuid.UUID] = []

    async with Session() as session:
        orgs = await _pick_two_orgs(session)
        if orgs is None:
            await engine.dispose()
            pytest.skip("Need >= 2 organizations")
        org_a, org_b = orgs

        await _set_rls(session, org_b)
        key_in_b = await _insert_key(session, org_id=org_b, label="cross-org-src")
        keys.append(key_in_b)
        await session.commit()

        tok = set_context(RequestContext(org_id=org_a))
        try:
            await _set_rls(session, org_a)
            with pytest.raises(HTTPException) as exc:
                await ai_service.create_assistant(
                    session,
                    org_id=org_a,
                    user_id=None,
                    payload=AiAssistantCreate(
                        name=f"cross-{uuid.uuid4().hex[:8]}",
                        key_id=key_in_b,  # belongs to org_b, not org_a!
                        model="gpt-4o-mini",
                    ),
                )
            assert exc.value.status_code == 404
            # Must NOT be 403 — that would leak the key's existence.
            assert exc.value.detail == "assistant not found"
        finally:
            reset_context(tok)
            await _set_rls(session, org_b)
            await _cleanup(session, key_ids=keys)
            await engine.dispose()


async def test_get_wrong_org_returns_same_body_as_nonexistent() -> None:
    """Body-parity portion of the timing-safe 404 spec. Both a
    wrong-org id and a nonexistent id must surface the SAME
    HTTPException with the SAME detail string."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    keys: list[uuid.UUID] = []

    async with Session() as session:
        orgs = await _pick_two_orgs(session)
        if orgs is None:
            await engine.dispose()
            pytest.skip("Need >= 2 organizations")
        org_a, org_b = orgs

        # Seed an assistant in org_b so we have a real "wrong-org id".
        await _set_rls(session, org_b)
        key_b = await _insert_key(session, org_id=org_b, label="wrong-org-owner")
        keys.append(key_b)
        aid_b = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO tbl_ai_assistants (id, org_id, name, status, key_id, model)
                VALUES (:id, :org, :name, 'draft', :key, 'gpt-4o-mini')
                """
            ),
            {
                "id": str(aid_b),
                "org": str(org_b),
                "name": f"wrong-org-{uuid.uuid4().hex[:8]}",
                "key": str(key_b),
            },
        )
        await session.commit()

        tok = set_context(RequestContext(org_id=org_a))
        try:
            await _set_rls(session, org_a)
            with pytest.raises(HTTPException) as wrong_org:
                await ai_service.get_assistant(
                    session, org_id=org_a, assistant_id=aid_b
                )
            with pytest.raises(HTTPException) as nonexistent:
                await ai_service.get_assistant(
                    session, org_id=org_a, assistant_id=uuid.uuid4()
                )
            assert wrong_org.value.status_code == 404
            assert nonexistent.value.status_code == 404
            assert wrong_org.value.detail == nonexistent.value.detail
        finally:
            reset_context(tok)
            # Delete the seed row in org_b before cleaning the key.
            await _set_rls(session, org_b)
            await session.execute(
                text("DELETE FROM tbl_ai_assistants WHERE id = :id"),
                {"id": str(aid_b)},
            )
            await _cleanup(session, key_ids=keys)
            await engine.dispose()


async def test_list_paginates_and_filters() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.models import AiAssistantStatus
    from src.app.core.ai_assistants.schemas import AiAssistantCreate
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    keys: list[uuid.UUID] = []

    async with Session() as session:
        org = await _pick_org(session)
        if org is None:
            await engine.dispose()
            pytest.skip("No organization")

        await _set_rls(session, org)
        key = await _insert_key(session, org_id=org, label="list-smoke")
        keys.append(key)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        prefix = f"list-{uuid.uuid4().hex[:8]}"
        try:
            await _set_rls(session, org)
            # Seed 3 assistants — first two active, third archived.
            aids = []
            for i in range(3):
                a = await ai_service.create_assistant(
                    session,
                    org_id=org,
                    user_id=None,
                    payload=AiAssistantCreate(
                        name=f"{prefix}-{i}",
                        key_id=key,
                        model="gpt-4o-mini",
                    ),
                )
                aids.append(a.id)
            await _set_rls(session, org)
            await ai_service.archive_assistant(
                session, org_id=org, assistant_id=aids[2]
            )

            # Filter by search prefix so we don't collide with other
            # tests' seed data in the same org.
            await _set_rls(session, org)
            rows, total = await ai_service.list_assistants(
                session, search=prefix, limit=10, offset=0
            )
            assert total == 3
            assert len(rows) == 3

            # Pagination — limit=2 returns 2 rows, offset=2 returns 1.
            await _set_rls(session, org)
            page1, _ = await ai_service.list_assistants(
                session, search=prefix, limit=2, offset=0
            )
            page2, _ = await ai_service.list_assistants(
                session, search=prefix, limit=2, offset=2
            )
            assert len(page1) == 2
            assert len(page2) == 1

            # Filter by status.
            await _set_rls(session, org)
            archived_rows, archived_total = await ai_service.list_assistants(
                session,
                search=prefix,
                filter_status=AiAssistantStatus.archived,
            )
            assert archived_total == 1
            assert archived_rows[0].id == aids[2]
        finally:
            reset_context(tok)
            await _set_rls(session, org)
            await _cleanup(session, key_ids=keys)
            await engine.dispose()


async def test_duplicate_name_returns_409() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

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
            pytest.skip("No organization")

        await _set_rls(session, org)
        key = await _insert_key(session, org_id=org, label="dup-smoke")
        keys.append(key)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        name = f"dup-{uuid.uuid4().hex[:8]}"
        try:
            await _set_rls(session, org)
            await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=name, key_id=key, model="gpt-4o-mini"
                ),
            )
            await _set_rls(session, org)
            with pytest.raises(HTTPException) as exc:
                await ai_service.create_assistant(
                    session,
                    org_id=org,
                    user_id=None,
                    payload=AiAssistantCreate(
                        name=name.upper(),  # case-insensitive unique
                        key_id=key,
                        model="gpt-4o-mini",
                    ),
                )
            assert exc.value.status_code == 409
        finally:
            reset_context(tok)
            await _set_rls(session, org)
            await _cleanup(session, key_ids=keys)
            await engine.dispose()
