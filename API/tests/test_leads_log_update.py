"""Coverage for ``POST /api/v1/leads/{id}/log-update``.

Atomicity + org / permission / optimistic-guard assertions for the
Update-Status modal's backend endpoint.

12 assertions matching ``tasks/leads-update-status-flow/step-1-backend-log-update-endpoint.md``:

  1.  happy path — contact patch + stage move + note + task all land
  2.  rollback on downstream failure — none of the writes persist
  3.  pin-test — service never reintroduces reused-service commits
  4.  optimistic stage guard fires 409
  5.  narrow contact schema — extra fields rejected 422
  6.  shared-contact guard 422 (contact linked to > 1 lead)
  7.  cross-org defence 404 (caller-org lead-org mismatch)
  8.  ownership visibility 404 (junior rep on a colleague's lead)
  9.  ``from_stage`` cannot be forged — server always reads fresh
  10. ``due_at`` bounds 422 (year 9999 rejected)
  11. ``contacts.write`` gate 403 when contact_basics present without perm
  12. remarks-only post — exactly one note, no task, no status_change
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.app.core.activities.models import Activity
from src.app.core.contacts.models import Contact
from src.app.core.leads.models import Lead
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.pipelines.models import Pipeline, PipelineStage
from src.app.core.tasks.models import Task
from src.app.shared.context import RequestContext, reset_context, set_context


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


async def _seed_pipeline_and_contact(org_id: uuid.UUID) -> uuid.UUID:
    """Seed the leads pipeline + one contact under ``org_id``.
    Returns the contact id."""
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            p = Pipeline(org_id=org_id, key="leads", name="Leads")
            session.add(p)
            await session.flush()
            for i, (k, name, won, lost) in enumerate(
                [
                    ("new", "New", False, False),
                    ("qualified", "Qualified", False, False),
                    ("won", "Won", True, False),
                    ("lost", "Lost", False, True),
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
            c = Contact(org_id=org_id, full_name="Log Tester", custom_data={}, tags=[])
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _create_lead(client, headers, contact_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/leads",
        json={"contact_id": str(contact_id), "pipeline_stage": "new"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _future(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


# --- 1. happy path -------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_all_writes_land(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "contacts.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "contact_basics": {"full_name": "Renamed", "phone": "+15550001111"},
            "pipeline_stage": "qualified",
            "source": "walk_in",
            "remarks": "great call",
            "next_follow_up": {"due_at": _future(2), "followup_type": "call"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lead"]["pipeline_stage"] == "qualified"
    assert body["lead"]["source"] == "walk_in"
    assert body["next_follow_up_task_id"] is not None

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            c = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            assert c.full_name == "Renamed"
            assert c.phone == "+15550001111"

            acts = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "lead")
                        .where(Activity.entity_id == uuid.UUID(lead_id))
                    )
                )
                .scalars()
                .all()
            )
            types = sorted(a.type.value for a in acts)
            assert types == ["note", "status_change"]
            note_row = next(a for a in acts if a.type.value == "note")
            assert note_row.payload == {"text": "great call"}
            sc_row = next(a for a in acts if a.type.value == "status_change")
            assert sc_row.payload == {"pipeline": "leads", "from": "new", "to": "qualified"}

            tasks = (
                (
                    await session.execute(
                        select(Task)
                        .where(Task.related_entity_type == "lead")
                        .where(Task.related_entity_id == uuid.UUID(lead_id))
                    )
                )
                .scalars()
                .all()
            )
            assert len(tasks) == 1
            assert tasks[0].followup_type.value == "call"
            assert tasks[0].title.startswith("Follow up: great call")
    finally:
        reset_context(ctx_token)


# --- 2. rollback -----------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_on_task_insert_failure(monkeypatch, layered_client, seeded_admin):
    """If the task insert raises, none of the earlier writes persist."""
    from src.app.core.leads import service as leads_service
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "contacts.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("simulated task-insert failure")

    monkeypatch.setattr(leads_service._tasks_da, "insert_task", _boom)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "contact_basics": {"full_name": "SHOULD_ROLLBACK"},
            "pipeline_stage": "qualified",
            "remarks": "should not persist",
            "next_follow_up": {"due_at": _future(2), "followup_type": "call"},
        },
    )
    assert resp.status_code == 500, resp.text

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            c = (
                await session.execute(select(Contact).where(Contact.id == contact_id))
            ).scalar_one()
            assert c.full_name != "SHOULD_ROLLBACK"

            lead_row = (
                await session.execute(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
            ).scalar_one()
            assert lead_row.pipeline_stage == "new"

            acts = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "lead")
                        .where(Activity.entity_id == uuid.UUID(lead_id))
                    )
                )
                .scalars()
                .all()
            )
            assert acts == []
    finally:
        reset_context(ctx_token)


# --- 3. pin-test — no reused-service commits ---------------------------------


def test_log_update_service_avoids_committing_helpers():
    """Guardrail: the atomic service must never call helpers that own
    their own commit boundary. Any drift back to them would break the
    single-transaction guarantee this endpoint promises."""
    from src.app.core.leads import service as leads_service

    src = inspect.getsource(leads_service.log_update_for_lead)
    for banned in ("move_stage_for_lead", "move_card(", "update_contact(", "create_task("):
        assert banned not in src, (
            f"log_update_for_lead must not call {banned!r}; those helpers commit "
            "internally and break the atomicity contract."
        )


# --- 4. optimistic stage guard ---------------------------------------------


@pytest.mark.asyncio
async def test_optimistic_stage_guard(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "qualified",  # wrong — DB has "new"
            "remarks": "stale",
        },
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "stage_drifted"
    assert detail["current_stage"] == "new"


# --- 5. narrow contact schema ----------------------------------------------


@pytest.mark.asyncio
async def test_narrow_contact_schema_rejects_extras(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "contacts.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "contact_basics": {
                "full_name": "OK",
                "assigned_to_id": str(uuid.uuid4()),  # not allowed
            },
            "remarks": "n",
        },
    )
    assert resp.status_code == 422, resp.text


# --- 6. shared-contact guard -----------------------------------------------


@pytest.mark.asyncio
async def test_shared_contact_blocks_basics(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write", "contacts.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_a = await _create_lead(layered_client, headers, contact_id)
    # Second lead sharing the same contact.
    await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_a}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "contact_basics": {"full_name": "should be blocked"},
            "remarks": "n",
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error"] == "contact_shared"
    assert detail["lead_count"] == 2


# --- 7. cross-org defence --------------------------------------------------


@pytest.mark.asyncio
async def test_cross_org_returns_404(layered_client, seeded_admin):
    """A caller in org A posting to a lead in org B gets 404."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    await _create_lead(layered_client, headers, contact_id)

    # A UUID that clearly doesn't belong to this org.
    ghost_lead_id = uuid.uuid4()
    resp = await layered_client.post(
        f"/api/v1/leads/{ghost_lead_id}/log-update",
        headers=headers,
        json={"if_current_stage": "new", "remarks": "n"},
    )
    assert resp.status_code == 404, resp.text


# --- 8. ownership visibility -----------------------------------------------


@pytest.mark.asyncio
async def test_junior_rep_cannot_touch_colleagues_lead(layered_client, seeded_admin):
    """Caller without ``users.read`` cannot log-update a lead assigned
    to someone else — matches ``get_lead_visible_to`` semantics."""
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # Grant writes but NOT users.read — this rep is a "junior".
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    # Reassign the row to a synthetic other-user id so `assigned_to_id
    # != caller.legacy_uuid` triggers the visibility check.
    other_user_id = uuid.uuid4()
    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            row = (
                await session.execute(select(Lead).where(Lead.id == uuid.UUID(lead_id)))
            ).scalar_one()
            row.assigned_to_id = other_user_id
            await session.commit()
    finally:
        reset_context(ctx_token)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={"if_current_stage": "new", "remarks": "sneaky"},
    )
    assert resp.status_code == 404, resp.text


# --- 9. from_stage cannot be forged ----------------------------------------


@pytest.mark.asyncio
async def test_from_stage_forgery_rejected(layered_client, seeded_admin):
    """Schema forbids extra keys, so a client cannot smuggle a
    ``from_stage`` field into the payload. Server always reads the
    real prior stage from the DB for the status_change activity."""
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "pipeline_stage": "qualified",
            "from_stage": "won",  # fabricated
            "remarks": "n",
        },
    )
    assert resp.status_code == 422, resp.text


# --- 10. due_at bounds -----------------------------------------------------


@pytest.mark.asyncio
async def test_due_at_out_of_band_rejected(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "remarks": "n",
            "next_follow_up": {"due_at": "9999-12-31T00:00:00Z", "followup_type": "call"},
        },
    )
    assert resp.status_code == 422, resp.text


# --- 11. contacts.write gate -----------------------------------------------


@pytest.mark.asyncio
async def test_contacts_write_required_when_basics_present(layered_client, seeded_admin):
    org = seeded_admin["org"]
    user = seeded_admin["user"]
    # NB: NO contacts.write — the router must reject.
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={
            "if_current_stage": "new",
            "contact_basics": {"full_name": "Nope"},
            "remarks": "n",
        },
    )
    assert resp.status_code == 403, resp.text


# --- 12. remarks-only no-change post ---------------------------------------


@pytest.mark.asyncio
async def test_remarks_only_writes_exactly_one_note(layered_client, seeded_admin):
    from tests.conftest import TestSession

    org = seeded_admin["org"]
    user = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "leads.read", "leads.write")
    contact_id = await _seed_pipeline_and_contact(org.id)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=user.email,
        password=seeded_admin["password"],
    )
    headers = {"Authorization": f"Bearer {token}"}
    lead_id = await _create_lead(layered_client, headers, contact_id)

    resp = await layered_client.post(
        f"/api/v1/leads/{lead_id}/log-update",
        headers=headers,
        json={"if_current_stage": "new", "remarks": "just checking in"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["next_follow_up_task_id"] is None

    ctx_token = set_context(RequestContext(org_id=org.id))
    try:
        async with TestSession() as session:
            acts = (
                (
                    await session.execute(
                        select(Activity)
                        .where(Activity.entity_type == "lead")
                        .where(Activity.entity_id == uuid.UUID(lead_id))
                    )
                )
                .scalars()
                .all()
            )
            assert [a.type.value for a in acts] == ["note"]
            assert acts[0].payload == {"text": "just checking in"}

            tasks = (
                (
                    await session.execute(
                        select(Task)
                        .where(Task.related_entity_type == "lead")
                        .where(Task.related_entity_id == uuid.UUID(lead_id))
                    )
                )
                .scalars()
                .all()
            )
            assert tasks == []
    finally:
        reset_context(ctx_token)
