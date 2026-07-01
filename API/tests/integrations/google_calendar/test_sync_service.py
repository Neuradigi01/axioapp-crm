"""Step 3 — Google Calendar sync-service decision-tree tests.

Instead of hitting Google's HTTP surface these tests replace the
:mod:`api_client` module's four public functions with async stubs so
the focus stays on ``sync_service.sync_appointment``'s branching:

  * fresh appointment → ``create_event`` fires + event_id/etag stored
  * updated appointment → ``patch_event`` fires + etag refreshed
  * cancelled / unassigned / gone → ``delete_event`` fires + local
    cleanup
  * assignee without a token row → no API call, ``'skipped'``
  * Google 404 on PATCH → drop local id + re-raise (task re-syncs)
  * Google 412 on PATCH → mark ``last_error`` + no overwrite

Row constructs are lightweight dataclass-style objects with the
minimum surface the sync service touches; a real ORM session isn't
opened. The token row's ``last_synced_at`` bump happens via a stubbed
DAL that records the call.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.app.core.appointments.models import AppointmentStatus
from src.app.core.integrations.google_calendar.exceptions import (
    GoogleCalendarConcurrencyConflict,
    GoogleCalendarEventGone,
)


# --- Fakes -----------------------------------------------------------


_ORG_ID = uuid.uuid4()
_USER_ID = 42
_OTHER_USER_ID = 99
_CONTACT_ID = uuid.uuid4()


class _FakeAppointment:
    """Duck-typed :class:`Appointment` — only the fields the sync
    service reads. Same-as attributes are mutable so tests can assert
    the sync loop wrote back the event_id + etag correctly."""

    def __init__(
        self,
        *,
        title: str = "Onboarding call",
        purpose: str | None = "Kick-off",
        scheduled_at: datetime | None = None,
        duration_min: int = 30,
        location: str | None = "Zoom",
        status: AppointmentStatus = AppointmentStatus.scheduled,
        assigned_to_id: Any = None,
        google_calendar_event_id: str | None = None,
        google_calendar_etag: str | None = None,
    ) -> None:
        self.id = uuid.uuid4()
        self.org_id = _ORG_ID
        self.contact_id = _CONTACT_ID
        self.title = title
        self.purpose = purpose
        self.scheduled_at = scheduled_at or datetime.now(UTC)
        self.duration_min = duration_min
        self.location = location
        self.status = status
        # By default the appointment is assigned to _USER_ID. Tests
        # override for reassignment / unassigned cases.
        self.assigned_to_id = assigned_to_id if assigned_to_id is not None else _USER_ID
        self.google_calendar_event_id = google_calendar_event_id
        self.google_calendar_etag = google_calendar_etag


class _FakeContact:
    def __init__(self, *, email: str | None = "asha@example.com") -> None:
        self.id = _CONTACT_ID
        self.email = email
        self.full_name = "Asha Pillai"


class _FakeOrg:
    def __init__(self) -> None:
        self.id = _ORG_ID
        self.timezone = "Asia/Kolkata"


class _FakeToken:
    def __init__(
        self,
        *,
        user_id: int = _USER_ID,
        primary_calendar_id: str | None = "primary",
        status: str = "active",
    ) -> None:
        self.id = uuid.uuid4()
        self.org_id = _ORG_ID
        self.user_id = user_id
        self.primary_calendar_id = primary_calendar_id
        self.status = status


class _FakeSession:
    """Records commit() calls so tests can assert transactions
    finalised. Everything else no-ops — the sync service's ORM writes
    are direct attribute mutations on the appointment / token
    instances, not `session.execute` statements."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _StubDA:
    """In-place stand-in for :mod:`data_access`."""

    def __init__(self, token: _FakeToken | None) -> None:
        self.token = token
        self.marked: list[dict] = []
        self.synced_bumps: list[dict] = []

    async def get_active_token_for_user(self, _s, *, org_id, user_id):
        if self.token and self.token.user_id == user_id and self.token.status == "active":
            return self.token
        return None

    async def mark_status(self, _s, *, token_id, status, error=None):
        self.marked.append(
            {"token_id": token_id, "status": status, "error": error}
        )

    async def touch_last_synced(self, _s, *, token_id, when):
        self.synced_bumps.append({"token_id": token_id, "when": when})


class _StubClient:
    """Records the calls the sync service makes into the Google
    Calendar API surface + returns canned responses / raises canned
    exceptions."""

    def __init__(self) -> None:
        self.creates: list[dict] = []
        self.patches: list[dict] = []
        self.deletes: list[dict] = []
        self.create_returns = ("gc-event-1", "etag-1")
        self.patch_returns = ("gc-event-1", "etag-2")
        self.patch_raises: Exception | None = None

    async def create_event(
        self, _s, *, org_id, user_id, calendar_id, event_body, http_client=None
    ):
        self.creates.append(
            {
                "org_id": org_id,
                "user_id": user_id,
                "calendar_id": calendar_id,
                "event_body": event_body,
            }
        )
        return self.create_returns

    async def patch_event(
        self,
        _s,
        *,
        org_id,
        user_id,
        calendar_id,
        event_id,
        event_body,
        etag,
        http_client=None,
    ):
        self.patches.append(
            {
                "org_id": org_id,
                "user_id": user_id,
                "calendar_id": calendar_id,
                "event_id": event_id,
                "event_body": event_body,
                "etag": etag,
            }
        )
        if self.patch_raises:
            raise self.patch_raises
        return self.patch_returns

    async def delete_event(
        self, _s, *, org_id, user_id, calendar_id, event_id, http_client=None
    ):
        self.deletes.append(
            {
                "org_id": org_id,
                "user_id": user_id,
                "calendar_id": calendar_id,
                "event_id": event_id,
            }
        )

    async def get_primary_calendar_id(
        self, _s, *, org_id, user_id, http_client=None
    ):
        return "primary"


# --- Wiring helper -----------------------------------------------------


@pytest.fixture
def _wire(monkeypatch):
    """Rewire :mod:`sync_service` against stubs. Yields a bundle
    tests can populate + inspect."""
    from src.app.core.integrations.google_calendar import (
        sync_service as _sync,
    )

    token = _FakeToken()
    da = _StubDA(token)
    client = _StubClient()

    appointment_holder: dict[str, Any] = {"appointment": None}
    contact = _FakeContact()
    org = _FakeOrg()

    async def _load_appointment(_s, _id):
        return appointment_holder["appointment"]

    async def _load_contact(_s, _cid):
        return contact

    async def _load_org(_s, _oid):
        return org

    monkeypatch.setattr(_sync, "_da", da)
    monkeypatch.setattr(_sync, "_client", client)
    monkeypatch.setattr(_sync, "_load_appointment", _load_appointment)
    monkeypatch.setattr(_sync, "_load_contact", _load_contact)
    monkeypatch.setattr(_sync, "_load_org", _load_org)

    return {
        "sync": _sync,
        "da": da,
        "client": client,
        "token": token,
        "appointment_holder": appointment_holder,
    }


# --- 1. Create path ----------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_appointment_creates_event(_wire):
    """No stored event_id → CREATE fires + event_id/etag persisted."""
    appt = _FakeAppointment()
    _wire["appointment_holder"]["appointment"] = appt

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )

    assert result == "created"
    assert appt.google_calendar_event_id == "gc-event-1"
    assert appt.google_calendar_etag == "etag-1"
    assert len(_wire["client"].creates) == 1
    assert not _wire["client"].patches
    assert not _wire["client"].deletes


# --- 2. Update path ----------------------------------------------------


@pytest.mark.asyncio
async def test_updated_appointment_patches_event(_wire):
    """Stored event_id → PATCH fires with the If-Match ETag; new etag
    persisted."""
    appt = _FakeAppointment(
        google_calendar_event_id="gc-event-1",
        google_calendar_etag="etag-1",
    )
    _wire["appointment_holder"]["appointment"] = appt

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )

    assert result == "updated"
    assert appt.google_calendar_etag == "etag-2"
    assert len(_wire["client"].patches) == 1
    call = _wire["client"].patches[0]
    assert call["event_id"] == "gc-event-1"
    assert call["etag"] == "etag-1"
    assert not _wire["client"].creates
    assert not _wire["client"].deletes


# --- 3. Delete path (cancelled) ----------------------------------------


@pytest.mark.asyncio
async def test_cancelled_appointment_deletes_event(_wire):
    """Status=cancelled + stored event_id → DELETE fires + local ids
    nulled out."""
    appt = _FakeAppointment(
        status=AppointmentStatus.cancelled,
        google_calendar_event_id="gc-event-1",
        google_calendar_etag="etag-1",
    )
    _wire["appointment_holder"]["appointment"] = appt

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )

    assert result == "deleted"
    assert appt.google_calendar_event_id is None
    assert appt.google_calendar_etag is None
    assert len(_wire["client"].deletes) == 1


# --- 4. Delete path (appointment gone) --------------------------------


@pytest.mark.asyncio
async def test_missing_appointment_no_ops_when_never_synced(_wire):
    """Appointment was deleted + never synced → nothing to reconcile."""
    _wire["appointment_holder"]["appointment"] = None
    # The sync service's ``_org_id_of`` returns a synthetic UUID when
    # the appointment is missing, so the token lookup misses + we
    # early-return.
    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=uuid.uuid4(), user_id=_USER_ID
    )
    assert result == "skipped"
    assert not _wire["client"].creates
    assert not _wire["client"].patches
    assert not _wire["client"].deletes


# --- 5. Assignee without connection -----------------------------------


@pytest.mark.asyncio
async def test_no_token_row_is_a_no_op(_wire):
    """Assignee never connected Calendar → skipped, no error."""
    _wire["appointment_holder"]["appointment"] = _FakeAppointment()
    # Rewire the DA to return None for our user (simulate no token).
    _wire["da"].token = None

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=uuid.uuid4(), user_id=_USER_ID
    )
    assert result == "skipped"
    assert not _wire["client"].creates


# --- 6. Google 404 on PATCH → drop id + re-raise ---------------------


@pytest.mark.asyncio
async def test_patch_404_drops_local_id_and_raises(_wire):
    """404 = "someone deleted the event out-of-band". Sync service
    nulls the local event_id/etag + re-raises so the task's next
    reconciliation pass recreates."""
    appt = _FakeAppointment(
        google_calendar_event_id="gc-event-gone",
        google_calendar_etag="etag-old",
    )
    _wire["appointment_holder"]["appointment"] = appt
    _wire["client"].patch_raises = GoogleCalendarEventGone("event gone")

    with pytest.raises(GoogleCalendarEventGone):
        await _wire["sync"].sync_appointment(
            _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
        )
    assert appt.google_calendar_event_id is None
    assert appt.google_calendar_etag is None


# --- 7. Google 412 on PATCH → mark last_error, don't overwrite --------


@pytest.mark.asyncio
async def test_patch_412_marks_last_error_no_overwrite(_wire):
    """v1 policy: concurrency conflict → mark last_error, keep the
    Google-side event intact."""
    appt = _FakeAppointment(
        google_calendar_event_id="gc-event-1",
        google_calendar_etag="etag-1",
    )
    _wire["appointment_holder"]["appointment"] = appt
    _wire["client"].patch_raises = GoogleCalendarConcurrencyConflict(
        "if-match mismatch"
    )

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )
    assert result == "skipped"
    # Local event_id / etag NOT nulled — we still own the row.
    assert appt.google_calendar_event_id == "gc-event-1"
    assert appt.google_calendar_etag == "etag-1"
    # Token row surfaced the concurrency error.
    assert len(_wire["da"].marked) == 1
    entry = _wire["da"].marked[0]
    assert entry["status"] == "error"
    assert "concurrency_conflict" in (entry["error"] or "")


# --- 8. Reassignment: sync a delete for the OLD assignee -------------


@pytest.mark.asyncio
async def test_delete_when_appointment_assigned_to_someone_else(_wire):
    """Reassignment path: the old-assignee's task looks up the
    appointment, sees ``assigned_to_id`` no longer matches, deletes
    the event from THEIR calendar + nulls the local id."""
    appt = _FakeAppointment(
        assigned_to_id=_OTHER_USER_ID,
        google_calendar_event_id="gc-event-1",
        google_calendar_etag="etag-1",
    )
    _wire["appointment_holder"]["appointment"] = appt

    result = await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )
    assert result == "deleted"
    assert appt.google_calendar_event_id is None
    assert len(_wire["client"].deletes) == 1


# --- 9. Event body translation carries the expected shape -----------


@pytest.mark.asyncio
async def test_event_body_carries_expected_fields(_wire):
    """CRM Appointment → Google Event body: summary, description,
    start/end with the org timezone, location, extended metadata."""
    appt = _FakeAppointment(
        title="Discovery",
        purpose="Explore fit",
        duration_min=45,
        scheduled_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )
    _wire["appointment_holder"]["appointment"] = appt

    await _wire["sync"].sync_appointment(
        _FakeSession(), appointment_id=appt.id, user_id=_USER_ID
    )
    body = _wire["client"].creates[0]["event_body"]
    assert body["summary"] == "Discovery"
    assert body["start"]["timeZone"] == "Asia/Kolkata"
    assert body["end"]["timeZone"] == "Asia/Kolkata"
    assert body["location"] == "Zoom"
    assert body["extendedProperties"]["private"]["crm_appointment_id"] == str(appt.id)
    # end = start + duration
    from dateutil.parser import isoparse  # type: ignore[import-not-found]

    end = isoparse(body["end"]["dateTime"])
    start = isoparse(body["start"]["dateTime"])
    assert (end - start) == timedelta(minutes=45)
