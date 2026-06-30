"""Coverage for `pipelines.move_card`.

Creates an ephemeral `test_pipeline_cards` table with a
`pipeline_stage` column, registers it via
`register_pipeline_table('test_pipeline_cards')`, and exercises:

  - move with a registered table → row updates, activity + audit logged
  - move to the same stage → idempotent no-op
  - unregistered table → 400
  - unknown stage key → 400
  - unknown pipeline key → 404
  - unknown card_id → 404
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from src.app.core import pipelines as pipelines_module
from src.app.core.activities.models import Activity
from src.app.core.audit.models import AuditLog
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.pipelines.service import move_card, register_pipeline_table
from src.app.shared.context import RequestContext, reset_context, set_context

_TEST_TABLE = "test_pipeline_cards"


async def _ensure_test_table() -> None:
    """Create the ephemeral cards table for this test module.

    Runs at module-fixture time; harmless if it already exists. The
    table is intentionally NOT tenant-scoped / RLS-enabled — `move_card`
    only needs `id` + `pipeline_stage` + `updated_at`.
    """
    from tests.conftest import test_engine

    async with test_engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE TABLE IF NOT EXISTS {_TEST_TABLE} ("
                "id UUID PRIMARY KEY, "
                "pipeline_stage VARCHAR(64), "
                "updated_at TIMESTAMPTZ DEFAULT now()"
                ")"
            )
        )


async def _drop_test_table() -> None:
    from tests.conftest import test_engine

    async with test_engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {_TEST_TABLE}"))


@pytest.fixture(autouse=True)
async def _cards_table():
    await _ensure_test_table()
    register_pipeline_table(_TEST_TABLE)
    yield
    await _drop_test_table()


async def _seed_pipeline(org_id: uuid.UUID) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="moves", name="Moves")
            session.add(p)
            await session.flush()
            for i, key in enumerate(("new", "qualified", "won")):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=p.id,
                        key=key,
                        name=key.title(),
                        display_order=i,
                        is_won=(key == "won"),
                    )
                )
            await session.commit()
            return p.id
    finally:
        reset_context(token)


async def _insert_card(stage: str | None = "new") -> uuid.UUID:
    from tests.conftest import test_engine

    cid = uuid.uuid4()
    async with test_engine.begin() as conn:
        await conn.execute(
            text(f"INSERT INTO {_TEST_TABLE} (id, pipeline_stage) VALUES (:id, :s)"),
            {"id": cid, "s": stage},
        )
    return cid


@pytest.mark.asyncio
async def test_move_card_updates_row_and_emits_activity_and_audit(layered_client, seeded_admin):
    """Happy path: registered table, valid stage, card exists."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _seed_pipeline(org.id)
    card_id = await _insert_card("new")

    ctx_token = set_context(RequestContext(org_id=org.id, user_id=user.id))
    try:
        async with TestSession() as session:
            await move_card(
                session,
                pipeline_key="moves",
                card_table=_TEST_TABLE,
                card_id=card_id,
                to_stage_key="qualified",
                user_id=user.id,
            )
    finally:
        reset_context(ctx_token)

    # Row updated
    from tests.conftest import test_engine

    async with test_engine.begin() as conn:
        new_stage = (
            await conn.execute(
                text(f"SELECT pipeline_stage FROM {_TEST_TABLE} WHERE id = :id"),
                {"id": card_id},
            )
        ).scalar_one()
    assert new_stage == "qualified"

    # Activity emitted (type=status_change, payload carries from/to/pipeline)
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            acts = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == _TEST_TABLE)
                        .where(Activity.entity_id == card_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(acts) == 1
            a = acts[0]
            assert a.type.value == "status_change"
            assert a.payload == {
                "pipeline": "moves",
                "from": "new",
                "to": "qualified",
            }
            assert a.user_id == user.id

            audits = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "pipelines.card_moved")
                        .where(AuditLog.entity_id == card_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(audits) == 1
            assert audits[0].before == {"pipeline": "moves", "stage": "new"}
            assert audits[0].after == {
                "pipeline": "moves",
                "stage": "qualified",
            }
    finally:
        reset_context(ctx_token)


@pytest.mark.asyncio
async def test_move_to_same_stage_is_noop(layered_client, seeded_admin):
    """Moving to the current stage neither updates nor logs."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    await _seed_pipeline(org.id)
    card_id = await _insert_card("qualified")

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            await move_card(
                session,
                pipeline_key="moves",
                card_table=_TEST_TABLE,
                card_id=card_id,
                to_stage_key="qualified",
            )
    finally:
        reset_context(ctx_token)

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            acts = (
                (await session.execute(select(Activity).where(Activity.entity_id == card_id)))
                .scalars()
                .all()
            )
            assert acts == []
    finally:
        reset_context(ctx_token)


@pytest.mark.asyncio
async def test_unregistered_table_rejected(layered_client, seeded_admin):
    from fastapi import HTTPException

    from tests.conftest import TestSession

    org = seeded_admin["org"]
    await _seed_pipeline(org.id)
    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            with pytest.raises(HTTPException) as ei:
                await move_card(
                    session,
                    pipeline_key="moves",
                    card_table="not_registered_table",
                    card_id=uuid.uuid4(),
                    to_stage_key="qualified",
                )
            assert ei.value.status_code == 400
            assert "not a registered" in ei.value.detail
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_unknown_stage_or_pipeline_or_card(layered_client, seeded_admin):
    from fastapi import HTTPException

    from tests.conftest import TestSession

    org = seeded_admin["org"]
    await _seed_pipeline(org.id)
    card_id = await _insert_card("new")

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            # Unknown stage → 400
            with pytest.raises(HTTPException) as ei:
                await move_card(
                    session,
                    pipeline_key="moves",
                    card_table=_TEST_TABLE,
                    card_id=card_id,
                    to_stage_key="nonexistent_stage",
                )
            assert ei.value.status_code == 400

            # Unknown pipeline → 404
            with pytest.raises(HTTPException) as ei:
                await move_card(
                    session,
                    pipeline_key="no_such_pipeline",
                    card_table=_TEST_TABLE,
                    card_id=card_id,
                    to_stage_key="qualified",
                )
            assert ei.value.status_code == 404

            # Unknown card_id → 404
            with pytest.raises(HTTPException) as ei:
                await move_card(
                    session,
                    pipeline_key="moves",
                    card_table=_TEST_TABLE,
                    card_id=uuid.uuid4(),
                    to_stage_key="qualified",
                )
            assert ei.value.status_code == 404
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_register_pipeline_table_rejects_unsafe_names():
    """`register_pipeline_table` validates names before they hit raw SQL."""
    with pytest.raises(ValueError):
        register_pipeline_table("Bad-Name")
    with pytest.raises(ValueError):
        register_pipeline_table("1starts_with_digit")
    with pytest.raises(ValueError):
        register_pipeline_table("has spaces")
    with pytest.raises(ValueError):
        register_pipeline_table("drops; DROP TABLE users; --")
    # The keep-this in scope to silence unused-import on the module level:
    assert pipelines_module.move_card is move_card
