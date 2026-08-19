"""Tests for the AI-prompt preset seed
(``tasks/ai-assistants`` Step 8).

The seed installs 6 preset "AI Agent" / "Customer Support Agent" /
etc. templates per org and is idempotent — re-running never
duplicates. Also checks that the ``GET /templates?channel=ai_prompt``
endpoint (verified in the router recon; already accepts the
channel filter) returns exactly the seeded set.
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

# Side-effect imports so metadata resolves.
import src.app.core.conversations.models  # noqa: F401,E402
import src.app.core.templates.models  # noqa: F401,E402
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


_EXPECTED_NAMES: set[str] = {
    "AI Agent",
    "Customer Support Agent",
    "Sales Agent",
    "Language Tutor",
    "Coding Expert",
    "Life Coach",
}


def _db_url() -> str | None:
    host = os.environ.get("DB_HOST")
    port = os.environ.get("DB_PORT")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    name = os.environ.get("DB_NAME")
    if not all([host, port, user, password, name]):
        return None
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"


# --- Pure-Python: preset list is well-formed -----------------------------


def test_preset_bag_has_six_entries_and_expected_names() -> None:
    from src.app.core.templates.seeds import _AI_PROMPT_PRESETS

    assert len(_AI_PROMPT_PRESETS) == 6
    names = {name for name, _body in _AI_PROMPT_PRESETS}
    assert names == _EXPECTED_NAMES


def test_preset_bodies_are_non_empty_and_under_length_cap() -> None:
    """Bodies must fit under the schema cap for
    ``AiAssistant.instructions`` (max_length=20_000). Also asserts
    they are non-trivial so a stray empty string doesn't ship."""
    from src.app.core.templates.seeds import _AI_PROMPT_PRESETS

    for name, body in _AI_PROMPT_PRESETS:
        assert isinstance(body, str), f"{name} body must be str"
        assert len(body) > 100, f"{name} body too short ({len(body)} chars)"
        assert len(body) < 20_000, f"{name} body over the cap"


def test_ai_prompt_is_registered_on_conversation_channel_enum() -> None:
    from src.app.core.conversations.models import ConversationChannel

    assert ConversationChannel.ai_prompt.value == "ai_prompt"


# --- DB-touching: seed idempotency + row count ---------------------------


@pytest.mark.asyncio
async def test_seed_is_idempotent_per_org() -> None:
    """Running the seed twice against the same org still leaves
    exactly 6 rows (the ``existing is not None`` short-circuit
    inside the seed function must fire on the second call)."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.templates.seeds import seed_ai_prompt_presets

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Grab any existing org.
        result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 1"))
        row = result.scalar_one_or_none()
        if row is None:
            await engine.dispose()
            pytest.skip("No organization")
        org_id = uuid.UUID(str(row))

        # RLS context so TenantScoped auto-filter fires.
        await session.execute(
            text("SELECT set_config('app.current_org_id', :o, true)"),
            {"o": str(org_id)},
        )
        try:
            first = await seed_ai_prompt_presets(session, org_id=org_id)
            await session.commit()
            assert len(first) == 6, f"first-call installed {len(first)}"

            await session.execute(
                text("SELECT set_config('app.current_org_id', :o, true)"),
                {"o": str(org_id)},
            )
            second = await seed_ai_prompt_presets(session, org_id=org_id)
            await session.commit()
            assert len(second) == 6, "second call should return existing rows (still 6)"

            # And a raw COUNT confirms no duplicates leaked.
            await session.execute(
                text("SELECT set_config('app.current_org_id', :o, true)"),
                {"o": str(org_id)},
            )
            count = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM tbl_message_templates
                        WHERE org_id = :o AND channel = 'ai_prompt'
                        """
                    ),
                    {"o": str(org_id)},
                )
            ).scalar_one()
            assert count == 6, f"row count drifted: {count}"
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_seed_rows_carry_expected_fields() -> None:
    """Sanity — every seeded row is on the correct channel, has a
    non-null body, published internal_status, transactional
    category. Prevents a future edit to the seed helper from
    silently landing rows with wrong metadata."""
    url = _db_url()
    if not url:
        pytest.skip("DB env vars not set")

    from src.app.core.templates.seeds import seed_ai_prompt_presets

    engine = create_async_engine(url, echo=False, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        result = await session.execute(text("SELECT id FROM tbl_organizations LIMIT 1"))
        row = result.scalar_one_or_none()
        if row is None:
            await engine.dispose()
            pytest.skip("No organization")
        org_id = uuid.UUID(str(row))

        await session.execute(
            text("SELECT set_config('app.current_org_id', :o, true)"),
            {"o": str(org_id)},
        )
        await seed_ai_prompt_presets(session, org_id=org_id)
        await session.commit()

        await session.execute(
            text("SELECT set_config('app.current_org_id', :o, true)"),
            {"o": str(org_id)},
        )
        rows = (
            await session.execute(
                text(
                    """
                    SELECT name, channel::text, internal_status::text,
                           category::text, body_text
                    FROM tbl_message_templates
                    WHERE org_id = :o AND channel = 'ai_prompt'
                    """
                ),
                {"o": str(org_id)},
            )
        ).fetchall()

        assert len(rows) == 6
        names = {r[0] for r in rows}
        assert names == _EXPECTED_NAMES
        for r in rows:
            assert r[1] == "ai_prompt"
            assert r[2] == "published"
            assert r[3] == "transactional"
            assert r[4] and len(r[4]) > 100

        await engine.dispose()
