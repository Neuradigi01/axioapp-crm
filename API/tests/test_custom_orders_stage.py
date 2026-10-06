"""Coverage for `POST /api/v1/custom-orders/{id}/move-stage`.

Reuses the core `pipelines.move_card` engine. Asserts:
  - invalid `to_stage` rejected with 400
  - valid move updates the column AND writes audit + activity + a
    `CustomOrderStageHistory` row
  - same-stage move is a no-op (no extra history row)
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity
from src.app.core.audit.models import AuditLog
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.packs.furniture.modules.custom_orders.models import (
    CustomOrderStageHistory,
)
from src.app.shared.context import RequestContext, reset_context, set_context

pytestmark = pytest.mark.usefixtures("furniture_org")


async def _grant(role_id: uuid.UUID, *keys: str) -> None:
    from tests.conftest import TestSession

    async with TestSession() as session:
        for key in keys:
            perm = await register_permission(
                session, key=key, module=key.split(".")[0], description=key
            )
            await session.execute(
                pg_insert(RolePermission)
                .values(role_id=role_id, permission_id=perm.id)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
            )
        await session.commit()


async def _login(client, *, org_slug: str, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "org_slug": org_slug},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _seed_custom_orders_pipeline(org_id: uuid.UUID) -> None:
    """Mirror the pack.yaml stage list locally so tests don't depend
    on the full pack-install flow.
    """
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="custom_orders", name="Custom Orders")
            session.add(p)
            await session.flush()
            for i, (k, name, won, lost) in enumerate(
                [
                    ("measurement_scheduled", "Measurement Scheduled", False, False),
                    ("design_phase", "Design Phase", False, False),
                    ("in_production", "In Production", False, False),
                    ("qc", "QC", False, False),
                    ("installation", "Installation", False, False),
                    ("delivered", "Delivered", True, False),
                    ("cancelled", "Cancelled", False, True),
                ]
            ):
                session.add(
                    PipelineStage(
                        org_id=org_id,
                        pipeline_id=p.id,
                        key=k,
                        name=name,
                        display_order=i,
                        is_won=won,
                        is_lost=lost,
                    )
                )
            await session.commit()
    finally:
        reset_context(token)


async def _create_order(client, headers, title: str = "Test order") -> str:
    resp = await client.post(
        "/api/v1/custom-orders",
        json={"title": title},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_invalid_stage_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
        "custom_orders.move",
    )
    await _seed_custom_orders_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    order_id = await _create_order(layered_client, headers)

    resp = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/move-stage",
        json={"to_stage": "ghost"},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "not part of pipeline" in resp.text


@pytest.mark.asyncio
async def test_valid_move_writes_audit_activity_and_history(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
        "custom_orders.move",
    )
    await _seed_custom_orders_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    order_id = await _create_order(layered_client, headers)

    resp = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/move-stage",
        json={"to_stage": "design_phase", "notes": "kicked off"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["pipeline_stage"] == "design_phase"

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            # Activity from the pipeline engine.
            acts = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "fp_custom_orders")
                        .where(Activity.entity_id == uuid.UUID(order_id))
                    )
                )
                .scalars()
                .all()
            )
            assert len(acts) == 1
            assert acts[0].type.value == "status_change"
            assert acts[0].payload == {
                "pipeline": "custom_orders",
                "from": "measurement_scheduled",
                "to": "design_phase",
            }

            # Audit from the pipeline engine.
            ads = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(AuditLog.action == "pipelines.card_moved")
                        .where(AuditLog.entity_id == uuid.UUID(order_id))
                    )
                )
                .scalars()
                .all()
            )
            assert len(ads) == 1

            # Per-order stage-history rows: one for "create" + one for
            # this transition.
            rows = (
                (
                    await session.execute(
                        select(CustomOrderStageHistory)
                        .where(CustomOrderStageHistory.order_id == uuid.UUID(order_id))
                        .order_by(CustomOrderStageHistory.changed_at.asc())
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 2
            assert rows[0].from_stage is None
            assert rows[0].to_stage == "measurement_scheduled"
            assert rows[1].from_stage == "measurement_scheduled"
            assert rows[1].to_stage == "design_phase"
            assert rows[1].notes == "kicked off"
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_same_stage_move_is_noop(layered_client, seeded_admin):
    """Moving to the current stage doesn't append a history row."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
        "custom_orders.move",
    )
    await _seed_custom_orders_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    order_id = await _create_order(layered_client, headers)

    resp = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/move-stage",
        json={"to_stage": "measurement_scheduled"},
        headers=headers,
    )
    assert resp.status_code == 200

    ctx = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            rows = (
                (
                    await session.execute(
                        select(CustomOrderStageHistory).where(
                            CustomOrderStageHistory.order_id == uuid.UUID(order_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1  # only the creation row
    finally:
        reset_context(ctx)


@pytest.mark.asyncio
async def test_move_requires_move_permission(layered_client, seeded_admin):
    """`custom_orders.write` is not enough — `custom_orders.move` is required."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(
        seeded_admin["role"].id,
        "custom_orders.read",
        "custom_orders.write",
    )
    await _seed_custom_orders_pipeline(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    order_id = await _create_order(layered_client, headers)

    resp = await layered_client.post(
        f"/api/v1/custom-orders/{order_id}/move-stage",
        json={"to_stage": "design_phase"},
        headers=headers,
    )
    assert resp.status_code == 403
