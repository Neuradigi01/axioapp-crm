"""Timing-parity + tenant-isolation smoke for the get-assistant path.

Two assertions:

  1. Body parity — a wrong-org id and a nonexistent id produce the
     SAME ``HTTPException.detail``. (Also asserted in
     ``test_crud.py::test_get_wrong_org_returns_same_body_as_nonexistent``,
     kept here for the tenant-isolation summary + to co-locate with
     the timing check.)

  2. Timing parity — the wrong-org branch and the nonexistent branch
     both issue exactly one bare-SQL lookup + zero follow-up queries
     (since the 404 fires before the second SELECT). Rather than a
     wall-clock N-samples-vs-N-samples test (fragile under CI load),
     we assert both branches emit **the same set of SQL statements**
     via a SQLAlchemy event listener. This is a stronger + more
     stable version of the intent: no side channel exists that
     distinguishes wrong-org from nonexistent.

Skipped when the compose stack isn't up.
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Side-effect imports so metadata resolves at query-compile time.
import src.app.core.ai_assistants.models  # noqa: F401,E402
import src.app.core.integrations.ai.models  # noqa: F401,E402
import src.app.core.tenants.models  # noqa: F401,E402

pytestmark = pytest.mark.asyncio


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


async def _insert_key(session: AsyncSession, *, org_id: uuid.UUID) -> uuid.UUID:
    kid = uuid.uuid4()
    await session.execute(
        text(
            """
            INSERT INTO tbl_ai_provider_keys
                (id, org_id, provider, label, encrypted_key, nonce,
                 key_version, fingerprint_sha256, last4, test_status)
            VALUES (:id, :o, 'openai', 'timing', :ct, :nn, 1, :fp, 'test', 'untested')
            """
        ),
        {
            "id": str(kid),
            "o": str(org_id),
            "ct": secrets.token_bytes(64),
            "nn": secrets.token_bytes(12),
            "fp": secrets.token_bytes(32),
        },
    )
    return kid


def _shape_of(stmt: str) -> str:
    """Normalise a SQL string to a stable shape for equality across
    the two 404 branches (different id bind values, same statement
    text)."""
    # Strip leading/trailing whitespace + collapse internal spaces.
    return " ".join(stmt.strip().split())


async def test_wrong_org_and_nonexistent_emit_identical_sql() -> None:
    """The 404-generating query set must be the same for both
    branches — no side channel that reveals whether a UUID exists
    in another org vs. doesn't exist anywhere."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Grab two orgs — need a wrong-org row that actually exists.
    async with Session() as bootstrap:
        result = await bootstrap.execute(text("SELECT id FROM tbl_organizations LIMIT 2"))
        rows = [uuid.UUID(str(r[0])) for r in result.fetchall()]
        if len(rows) < 2:
            await engine.dispose()
            pytest.skip("Need >= 2 organizations")
        org_a, org_b = rows[0], rows[1]

        # Seed an assistant in org_b so the wrong-org id is a real row.
        await _set_rls(bootstrap, org_b)
        key_b = await _insert_key(bootstrap, org_id=org_b)
        aid_b = uuid.uuid4()
        await bootstrap.execute(
            text(
                """
                INSERT INTO tbl_ai_assistants (id, org_id, name, status, key_id, model)
                VALUES (:id, :o, :name, 'draft', :k, 'gpt-4o-mini')
                """
            ),
            {
                "id": str(aid_b),
                "o": str(org_b),
                "name": f"timing-{uuid.uuid4().hex[:8]}",
                "k": str(key_b),
            },
        )
        await bootstrap.commit()

    captured_wrong_org: list[str] = []
    captured_nonexistent: list[str] = []

    def _make_capture(bucket: list[str]):
        def _capture(conn, cursor, statement, *a, **kw):  # noqa: ANN001, ARG001
            bucket.append(statement)

        return _capture

    tok = set_context(RequestContext(org_id=org_a))
    try:
        # --- Wrong-org branch ---
        async with Session() as session:
            await _set_rls(session, org_a)
            listener = _make_capture(captured_wrong_org)
            event.listen(engine.sync_engine, "before_cursor_execute", listener)
            try:
                with pytest.raises(HTTPException) as exc:
                    await ai_service.get_assistant(
                        session, org_id=org_a, assistant_id=aid_b
                    )
                assert exc.value.status_code == 404
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", listener)

        # --- Nonexistent branch ---
        async with Session() as session:
            await _set_rls(session, org_a)
            listener = _make_capture(captured_nonexistent)
            event.listen(engine.sync_engine, "before_cursor_execute", listener)
            try:
                with pytest.raises(HTTPException) as exc:
                    await ai_service.get_assistant(
                        session, org_id=org_a, assistant_id=uuid.uuid4()
                    )
                assert exc.value.status_code == 404
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", listener)

        # Filter out the RLS SET LOCAL noise — both branches also
        # emit it, and both emit the same shape.
        def _is_assistant_lookup(s: str) -> bool:
            n = _shape_of(s).lower()
            return "from tbl_ai_assistants" in n

        wrong_lookups = [_shape_of(s) for s in captured_wrong_org if _is_assistant_lookup(s)]
        none_lookups = [_shape_of(s) for s in captured_nonexistent if _is_assistant_lookup(s)]

        # Same COUNT of assistant-table lookups on both branches
        # (exactly one — the bare-SQL check that raises 404).
        assert len(wrong_lookups) == len(none_lookups), (
            f"query count differs: wrong={len(wrong_lookups)} nonexistent={len(none_lookups)}\n"
            f"wrong: {wrong_lookups}\n"
            f"none:  {none_lookups}"
        )
        assert wrong_lookups == none_lookups, (
            "query shape differs between wrong-org and nonexistent branches "
            "— potential side channel:\n"
            f"wrong: {wrong_lookups}\nnone:  {none_lookups}"
        )
        # Belt-and-braces: exactly one bare-SQL lookup, no ORM
        # follow-up (which would fire only on the happy path).
        assert len(wrong_lookups) == 1
    finally:
        reset_context(tok)
        async with Session() as cleanup:
            await _set_rls(cleanup, org_b)
            await cleanup.execute(
                text("DELETE FROM tbl_ai_assistants WHERE id = :id"),
                {"id": str(aid_b)},
            )
            await cleanup.execute(
                text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
                {"id": str(key_b)},
            )
            await cleanup.commit()
        await engine.dispose()


async def test_wrong_org_and_nonexistent_have_same_detail() -> None:
    """Body parity — the detail string is a fixed constant, not a
    templated string that could reveal existence."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.ai_assistants import service as ai_service
    from src.app.shared.context import RequestContext, reset_context, set_context

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 2"))
        rows = [uuid.UUID(str(r[0])) for r in result.fetchall()]
        if len(rows) < 2:
            await engine.dispose()
            pytest.skip("Need >= 2 organizations")
        org_a, org_b = rows[0], rows[1]

        # Seed one row in org_b.
        await _set_rls(session, org_b)
        key_b = await _insert_key(session, org_id=org_b)
        aid_b = uuid.uuid4()
        await session.execute(
            text(
                """
                INSERT INTO tbl_ai_assistants (id, org_id, name, status, key_id, model)
                VALUES (:id, :o, :name, 'draft', :k, 'gpt-4o-mini')
                """
            ),
            {
                "id": str(aid_b),
                "o": str(org_b),
                "name": f"body-parity-{uuid.uuid4().hex[:8]}",
                "k": str(key_b),
            },
        )
        await session.commit()

        tok = set_context(RequestContext(org_id=org_a))
        try:
            await _set_rls(session, org_a)
            with pytest.raises(HTTPException) as wrong_org:
                await ai_service.get_assistant(session, org_id=org_a, assistant_id=aid_b)
            with pytest.raises(HTTPException) as nonexistent:
                await ai_service.get_assistant(session, org_id=org_a, assistant_id=uuid.uuid4())

            assert wrong_org.value.status_code == nonexistent.value.status_code == 404
            assert wrong_org.value.detail == nonexistent.value.detail
            # And that detail is a plain string with no id / org
            # information — no templating that could vary between
            # branches.
            assert isinstance(wrong_org.value.detail, str)
            assert str(aid_b) not in wrong_org.value.detail
            assert str(org_b) not in wrong_org.value.detail
        finally:
            reset_context(tok)
            await _set_rls(session, org_b)
            await session.execute(
                text("DELETE FROM tbl_ai_assistants WHERE id = :id"),
                {"id": str(aid_b)},
            )
            await session.execute(
                text("DELETE FROM tbl_ai_provider_keys WHERE id = :id"),
                {"id": str(key_b)},
            )
            await session.commit()
            await engine.dispose()
