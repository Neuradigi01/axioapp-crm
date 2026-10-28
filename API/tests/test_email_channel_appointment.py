"""Email channel coverage for appointment notifications (Step 6 of
update-appointments-page).

`notifications.service.notify()` ships an in-app row + WebSocket push +
(opt-in) an email. These tests verify the email path:

  - Email defaults to OFF; explicit pref row required to dispatch.
  - SMTP failure must NOT roll back the persisted in-app notification.
  - Renderer-unsupported types skip email cleanly (no raise, no send).
  - Subject + body carry the appointment payload data.

We patch `src.app.shared.email.get_email_backend` to a recording or
raising fake so SMTP credentials aren't required in CI.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text

from src.app.core.appointments.models import Appointment, AppointmentStatus
from src.app.core.audit.models import AuditLog
from src.app.core.contacts.models import Contact
from src.app.core.notifications import service as notif_service
from src.app.core.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationPreference,
)
from src.app.core.permissions.models import RolePermission
from src.app.core.permissions.service import register_permission
from src.app.core.users.models import OrganizationMember, UserInfo
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.security.password import hash_password as _hp
from src.models.user import UserLogin

# --- fake email backend ----------------------------------------------------


@dataclass
class _SentEmail:
    to: str
    subject: str
    body_text: str
    body_html: str | None


class _RecordingBackend:
    """Captures every `send()` call. Use in tests that assert content."""

    def __init__(self) -> None:
        self.sent: list[_SentEmail] = []

    async def send(self, email) -> None:  # type: ignore[no-untyped-def]
        self.sent.append(
            _SentEmail(
                to=email.to,
                subject=email.subject,
                body_text=email.body_text,
                body_html=email.body_html,
            )
        )


class _RaisingBackend:
    """Simulates SMTP failure — `send()` always raises."""

    async def send(self, email) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("SMTP server is down")


def _install_backend(monkeypatch, backend) -> None:
    """Patch `get_email_backend()` so `_send_email_for` picks up `backend`.

    Patches BOTH the symbol in `shared.email` (the lazy-imported name)
    AND the cached module-level `_backend` so other call sites that
    grabbed the original singleton at import time are unaffected.
    """
    from src.app.shared import email as email_pkg

    monkeypatch.setattr(email_pkg, "get_email_backend", lambda: backend)


# --- shared helpers (mirrored from test_appointments_notifications_emitted) -


from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402


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


async def _seed_contact(org_id: uuid.UUID, *, name: str = "Asha") -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            c = Contact(
                org_id=org_id,
                full_name=name,
                custom_data={},
                tags=[],
            )
            session.add(c)
            await session.commit()
            return c.id
    finally:
        reset_context(token)


async def _seed_second_user(
    org_id: uuid.UUID,
    *,
    role_id: uuid.UUID,
    first_name: str = "Priya",
) -> tuple[uuid.UUID, str]:
    """Insert a second user; return (legacy_uuid, email)."""
    from tests.conftest import TestSession

    user_uuid = uuid.uuid4()
    login_handle = f"second-{uuid.uuid4().hex[:8]}"
    email = f"{first_name.lower()}-{uuid.uuid4().hex[:6]}@demo.local"

    async with TestSession() as session:
        login = UserLogin(
            user_id=login_handle,
            password=_hp("Pass@123"),
            is_active=True,
        )
        session.add(login)
        await session.flush()

        await session.execute(
            sql_text("UPDATE tbl_user_login SET legacy_uuid = :u WHERE id = :i"),
            {"u": str(user_uuid), "i": login.id},
        )
        await session.execute(
            sql_text("INSERT INTO users (id) VALUES (:u) ON CONFLICT DO NOTHING"),
            {"u": str(user_uuid)},
        )
        session.add(
            UserInfo(
                member_id=login.id,
                first_name=first_name,
                last_name="Test",
                email=email,
                mobile_no="0000000099",
            )
        )
        session.add(
            OrganizationMember(
                organization_id=org_id,
                user_member_id=login.id,
                role_id=role_id,
                status="active",
                is_active=True,
                is_demo=False,
            )
        )
        await session.commit()
    return user_uuid, email


async def _seed_appointment(
    org_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    assigned_to_id: uuid.UUID,
    status: AppointmentStatus = AppointmentStatus.scheduled,
    scheduled_at: datetime | None = None,
) -> uuid.UUID:
    from tests.conftest import TestSession

    token = set_context(RequestContext(org_id=org_id))
    try:
        async with TestSession() as session:
            a = Appointment(
                org_id=org_id,
                contact_id=contact_id,
                title="Showroom visit",
                scheduled_at=scheduled_at or datetime.now(UTC) + timedelta(days=1, hours=2),
                duration_min=60,
                assigned_to_id=assigned_to_id,
                status=status,
                custom_data={},
            )
            session.add(a)
            await session.commit()
            return a.id
    finally:
        reset_context(token)


async def _opt_in_email(org_id: uuid.UUID, *, user_id: uuid.UUID, type_: str) -> None:
    """Insert an explicit `enabled=True` row for `(user, type, email)`."""
    from tests.conftest import TestSession

    async with TestSession() as session:
        session.add(
            NotificationPreference(
                org_id=org_id,
                user_id=user_id,
                type=type_,
                channel=NotificationChannel.email,
                enabled=True,
            )
        )
        await session.commit()


async def _notifications_for(user_id: uuid.UUID, *, type_: str | None = None) -> list[Notification]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if type_ is not None:
            stmt = stmt.where(Notification.type == type_)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


async def _audit_actions(*, action: str) -> list[AuditLog]:
    from tests.conftest import TestSession

    async with TestSession() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.action == action)))
            .scalars()
            .all()
        )
        return list(rows)


def _ts(hour: int, days_offset: int = 1) -> str:
    base = datetime.now(UTC).replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(
        days=days_offset
    )
    return base.isoformat()


# --- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_pref_on_dispatches_email(layered_client, seeded_admin, monkeypatch):
    """Email pref ON for `appointment.assigned` -> SMTP send() called once
    with subject carrying the appointment title."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="Asha Reddy")
    priya_uuid, priya_email = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="Priya"
    )
    await _opt_in_email(org.id, user_id=priya_uuid, type_="appointment.assigned")

    backend = _RecordingBackend()
    _install_backend(monkeypatch, backend)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Sofa selection",
            "scheduled_at": _ts(10),
            "duration_min": 60,
            "location": "Banjara Hills",
            "assigned_to_id": str(priya_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text

    assert len(backend.sent) == 1
    sent = backend.sent[0]
    assert sent.to == priya_email
    assert "Sofa selection" in sent.subject
    assert "Asha Reddy" in sent.body_text


@pytest.mark.asyncio
async def test_email_pref_off_skips_email(layered_client, seeded_admin, monkeypatch):
    """No explicit email pref row -> default OFF -> no SMTP send()."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    priya_uuid, _ = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaOff"
    )

    backend = _RecordingBackend()
    _install_backend(monkeypatch, backend)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "No email please",
            "scheduled_at": _ts(11),
            "duration_min": 30,
            "assigned_to_id": str(priya_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text

    assert backend.sent == []
    # In-app row still written.
    notifs = await _notifications_for(priya_uuid, type_="appointment.assigned")
    assert len(notifs) == 1


@pytest.mark.asyncio
async def test_smtp_failure_does_not_rollback_notification(
    layered_client, seeded_admin, monkeypatch
):
    """Backend raises -> in-app notification row still persisted, an
    audit row `notification.email.failed` is written, parent request
    returns 201."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="SmtpDown")
    priya_uuid, _ = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaFail"
    )
    await _opt_in_email(org.id, user_id=priya_uuid, type_="appointment.assigned")

    _install_backend(monkeypatch, _RaisingBackend())

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.post(
        "/api/v1/appointments",
        json={
            "contact_id": str(contact_id),
            "title": "Survive SMTP failure",
            "scheduled_at": _ts(13),
            "duration_min": 30,
            "assigned_to_id": str(priya_uuid),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text

    notifs = await _notifications_for(priya_uuid, type_="appointment.assigned")
    assert len(notifs) == 1
    failed = await _audit_actions(action="notification.email.failed")
    assert len(failed) == 1
    assert failed[0].after["type"] == "appointment.assigned"


@pytest.mark.asyncio
async def test_rescheduled_email_carries_new_scheduled_at(
    layered_client, seeded_admin, monkeypatch
):
    """Reschedule -> email body contains the new ISO scheduled_at."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id)
    priya_uuid, _ = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaR"
    )
    await _opt_in_email(org.id, user_id=priya_uuid, type_="appointment.rescheduled")
    appt_id = await _seed_appointment(org.id, contact_id=contact_id, assigned_to_id=priya_uuid)

    backend = _RecordingBackend()
    _install_backend(monkeypatch, backend)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    new_at = (datetime.now(UTC) + timedelta(days=3, hours=5)).isoformat()
    resp = await layered_client.post(
        f"/api/v1/appointments/{appt_id}/reschedule",
        json={"scheduled_at": new_at, "reason": "vendor delay"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    assert len(backend.sent) == 1
    sent = backend.sent[0]
    assert "rescheduled" in sent.subject.lower()
    # The renderer emits the payload's `scheduled_at` ISO string.
    assert new_at[:13] in sent.body_text  # YYYY-MM-DDTHH


@pytest.mark.asyncio
async def test_cancelled_email_carries_contact_and_time(layered_client, seeded_admin, monkeypatch):
    """Cancel -> email body contains the contact name + original
    scheduled_at."""
    org = seeded_admin["org"]
    actor = seeded_admin["user"]
    await _grant(seeded_admin["role"].id, "appointments.read", "appointments.write")
    contact_id = await _seed_contact(org.id, name="Mr Cancel")
    priya_uuid, _ = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaC"
    )
    await _opt_in_email(org.id, user_id=priya_uuid, type_="appointment.cancelled")
    scheduled = datetime.now(UTC) + timedelta(days=1, hours=4)
    appt_id = await _seed_appointment(
        org.id,
        contact_id=contact_id,
        assigned_to_id=priya_uuid,
        scheduled_at=scheduled,
    )

    backend = _RecordingBackend()
    _install_backend(monkeypatch, backend)

    token = await _login(
        layered_client,
        org_slug=org.slug,
        email=actor.email,
        password=seeded_admin["password"],
    )

    resp = await layered_client.patch(
        f"/api/v1/appointments/{appt_id}",
        json={"status": "cancelled"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text

    assert len(backend.sent) == 1
    sent = backend.sent[0]
    assert "cancelled" in sent.subject.lower()
    assert "Mr Cancel" in sent.body_text
    # Original scheduled_at appears as the ISO prefix.
    assert scheduled.isoformat()[:13] in sent.body_text


@pytest.mark.asyncio
async def test_unknown_type_skips_email(seeded_admin, monkeypatch):
    """Notify with a non-appointment.* type -> renderer returns None ->
    backend.send() not called even when email pref is ON."""
    org = seeded_admin["org"]
    priya_uuid, _ = await _seed_second_user(
        org.id, role_id=seeded_admin["role"].id, first_name="PriyaU"
    )
    # Opt in email for a hypothetical "lead.assigned" type — not handled
    # by the appointment renderer.
    await _opt_in_email(org.id, user_id=priya_uuid, type_="lead.assigned")

    backend = _RecordingBackend()
    _install_backend(monkeypatch, backend)

    await notif_service.notify(
        org_id=org.id,
        user_id=priya_uuid,
        type="lead.assigned",
        title="New lead",
        body="someone",
        payload={"lead_id": str(uuid.uuid4())},
    )

    assert backend.sent == []
    # In-app row still persisted.
    notifs = await _notifications_for(priya_uuid, type_="lead.assigned")
    assert len(notifs) == 1
