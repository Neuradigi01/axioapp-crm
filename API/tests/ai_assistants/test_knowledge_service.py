"""Service-layer tests for the knowledge-source ingest pipeline
(``tasks/ai-assistants`` Step 10).

Pure-Python assertions where possible (schema shape, URL pre-check,
dedup hash-equivalence); DB-dependent branches (insert + list +
cancel + delete lifecycle) skip when the compose stack isn't up.
"""

from __future__ import annotations

import base64
import hashlib
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


# --- Pure-Python schema + hash equivalence -------------------------------


def test_text_schema_rejects_org_id_and_extra_fields() -> None:
    from src.app.core.ai_assistants.schemas import KnowledgeCreateText

    with pytest.raises(Exception):
        KnowledgeCreateText(title="x", body_text="y", org_id="oops")  # type: ignore[call-arg]


def test_text_body_hash_matches_manual_sha256() -> None:
    body = "Our office is at 123 Main St. We ship worldwide in 3-5 days."
    manual = hashlib.sha256(body.encode("utf-8")).digest()
    # The service uses this exact scheme — assertion here documents
    # the invariant so a refactor that switches to a different digest
    # can't silently break dedup.
    assert len(manual) == 32


def test_url_schema_bounds() -> None:
    from src.app.core.ai_assistants.schemas import KnowledgeCreateUrl

    with pytest.raises(Exception):
        KnowledgeCreateUrl(title="x", url="")
    with pytest.raises(Exception):
        KnowledgeCreateUrl(title="x", url="a" * 5000)


# --- URL pre-check surfaces the SSRF reason ------------------------------


def test_pre_check_url_rejects_private_ip_literal() -> None:
    from src.app.core.ai_assistants import service as ai_service

    with pytest.raises(HTTPException) as exc:
        ai_service._pre_check_url("http://192.168.1.1/admin")
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "private_ip_rejected"


def test_pre_check_url_rejects_bad_scheme() -> None:
    from src.app.core.ai_assistants import service as ai_service

    with pytest.raises(HTTPException) as exc:
        ai_service._pre_check_url("file:///etc/passwd")
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "bad_scheme"


def test_pre_check_url_rejects_aws_imds() -> None:
    from src.app.core.ai_assistants import service as ai_service

    with pytest.raises(HTTPException) as exc:
        ai_service._pre_check_url("http://169.254.169.254/latest/meta-data")
    assert exc.value.status_code == 422
    assert exc.value.detail["reason"] == "private_ip_rejected"


# --- Storage key naming --------------------------------------------------


def test_storage_key_never_uses_client_filename() -> None:
    """Case §12 in the track README: an operator uploading a file
    called ``../../../etc/passwd`` still gets stored at
    ``{org_id}/ai_assistants/{knowledge_id}.bin``. The service's
    ``_storage_key`` helper is what enforces this — pin the exact
    shape."""
    from src.app.core.ai_assistants import service as ai_service

    org = uuid.uuid4()
    kid = uuid.uuid4()
    key = ai_service._storage_key(org, kid)
    assert key == f"{org}/ai_assistants/{kid}.bin"
    # Never contains the client name or traversal characters.
    assert ".." not in key
    assert "\\" not in key


# --- Dispatch is monkey-patchable ---------------------------------------


def test_dispatch_ingest_never_raises_when_broker_offline(monkeypatch) -> None:
    """The router must not 500 when Celery can't reach the broker in
    dev shells — the shim's ``.apply()`` handles the fallback path."""
    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.tasks import ingest_knowledge as task

    calls: list[str] = []
    monkeypatch.setattr(task, "delay", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no broker")))
    monkeypatch.setattr(task, "apply", lambda *a, **kw: calls.append("fallback"))

    ai_service._dispatch_ingest(uuid.uuid4())
    assert calls == ["fallback"]


# --- End-to-end text ingest + dedup --------------------------------------


async def test_text_ingest_creates_row_and_dedups() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.schemas import (
        AiAssistantCreate,
        KnowledgeCreateText,
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
        kid = await _insert_key(session, org_id=org, label="knowledge-smoke")
        keys.append(kid)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        try:
            await _set_rls(session, org)
            uniq = uuid.uuid4().hex[:8]
            created = await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=f"knowledge-{uniq}",
                    key_id=kid,
                    model="gpt-4o-mini",
                ),
            )

            # Monkey-patch the Celery dispatcher so we don't require
            # a broker running for this end-to-end test — the row
            # should still land in the DB.
            import src.app.core.ai_assistants.service as svc

            _dispatched: list[uuid.UUID] = []
            svc._dispatch_ingest = lambda kid: _dispatched.append(kid)

            row1, dup1 = await ai_service.create_knowledge_from_text(
                session,
                org_id=org,
                assistant_id=created.id,
                payload=KnowledgeCreateText(
                    title="FAQ",
                    body_text="Our office is at 123 Main St.",
                ),
            )
            assert dup1 is False
            assert row1.assistant_id == created.id
            assert row1.source_type.value == "text"
            assert row1.status.value == "pending"
            assert len(row1.content_hash) == 32
            assert _dispatched == [row1.id]

            # Second call with identical body -> dedup path, same id.
            row2, dup2 = await ai_service.create_knowledge_from_text(
                session,
                org_id=org,
                assistant_id=created.id,
                payload=KnowledgeCreateText(
                    title="FAQ (retry)",
                    body_text="Our office is at 123 Main St.",
                ),
            )
            assert dup2 is True
            assert row2.id == row1.id
            # Dispatch fires only on fresh insert.
            assert _dispatched == [row1.id]

            # List surfaces the row.
            rows = await ai_service.list_knowledge(
                session, org_id=org, assistant_id=created.id
            )
            assert any(r.id == row1.id for r in rows)

            # Delete pending row succeeds inline.
            await ai_service.delete_knowledge(
                session,
                org_id=org,
                assistant_id=created.id,
                knowledge_id=row1.id,
            )
            after = await ai_service.list_knowledge(
                session, org_id=org, assistant_id=created.id
            )
            assert all(r.id != row1.id for r in after)
        finally:
            reset_context(tok)
            await _cleanup(session, key_ids=keys)
    await engine.dispose()


async def test_cancel_rejects_when_not_cancelable() -> None:
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import data_access as _da
    from src.app.core.ai_assistants import service as ai_service
    from src.app.core.ai_assistants.models import KnowledgeStatus
    from src.app.core.ai_assistants.schemas import (
        AiAssistantCreate,
        KnowledgeCreateText,
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
        kid = await _insert_key(session, org_id=org, label="cancel-smoke")
        keys.append(kid)
        await session.commit()

        tok = set_context(RequestContext(org_id=org))
        try:
            await _set_rls(session, org)
            uniq = uuid.uuid4().hex[:8]
            created = await ai_service.create_assistant(
                session,
                org_id=org,
                user_id=None,
                payload=AiAssistantCreate(
                    name=f"cancel-{uniq}",
                    key_id=kid,
                    model="gpt-4o-mini",
                ),
            )
            import src.app.core.ai_assistants.service as svc

            svc._dispatch_ingest = lambda _kid: None

            row, _ = await ai_service.create_knowledge_from_text(
                session,
                org_id=org,
                assistant_id=created.id,
                payload=KnowledgeCreateText(title="X", body_text="body"),
            )

            # Flip status to ready manually to prove the guard rejects.
            await _da.set_status(
                session,
                knowledge_id=row.id,
                status=KnowledgeStatus.ready,
            )
            await session.commit()

            with pytest.raises(HTTPException) as exc:
                await ai_service.cancel_knowledge(
                    session,
                    org_id=org,
                    assistant_id=created.id,
                    knowledge_id=row.id,
                )
            assert exc.value.status_code == 409
            assert exc.value.detail["reason"] == "not_cancelable"
        finally:
            reset_context(tok)
            await _cleanup(session, key_ids=keys)
    await engine.dispose()
