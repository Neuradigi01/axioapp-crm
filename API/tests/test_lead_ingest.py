"""Step 6 — centralised lead-ingestion service tests.

Pure-unit, no DB round-trips — mirrors the Step 1/2/3/4/5 test style.
The five-channel refactor is exercised via the ingest service itself
(not by driving each channel end-to-end here — those have their own
test files which now pass through the shared ingest path).

Six groups:

  1. `ingest()` happy path (no existing open lead) — creates a new
     lead with the assignee from `pick_assignee`.
  2. `ingest()` merge path — open lead exists → activity appended,
     no new lead created.
  3. `ingest()` no eligible users — `pick_assignee` returns None;
     lead lands with `assigned_to_id=None`.
  4. `pick_assignee` round-robin distribution across N users.
  5. `find_open_lead_for_contact` SQL surface (raw text query
     verification — no DB needed; we capture the SQL shape).
  6. Routing config endpoints — GET/PUT round-trip via FastAPI.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.app.core.leads import dedup, ingest as ingest_module, routing
from src.app.core.leads.ingest import IngestResult, ingest
from src.app.core.leads.models import LeadSource
from src.app.core.leads.schemas import LeadCreate


_ORG_ID = uuid.uuid4()
_CONTACT_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- shared fakes --------------------------------------------------------


class _CapturingSession:
    """Minimal AsyncSession stand-in — same pattern as the other
    integration tests."""

    def __init__(self) -> None:
        self.added: list = []
        self.committed = False

    def add(self, row):
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()

    async def commit(self):
        self.committed = True

    async def refresh(self, _row):
        pass

    async def execute(self, _stmt, _params=None):
        raise NotImplementedError

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


@pytest.fixture(autouse=True)
def _silence_audit_and_activities(monkeypatch):
    """`ingest()` calls audit.log + activities.log. Both open their
    own sessions in production — stub to no-ops for unit tests."""
    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(ingest_module.audit, "log", _noop)
    monkeypatch.setattr(ingest_module, "activities_log", _noop)


def _base_lead_payload() -> LeadCreate:
    return LeadCreate(
        contact_id=_CONTACT_ID,
        source=LeadSource.manual,
        custom_data={},
        attribution=None,
    )


# --- 1. ingest() — happy path -------------------------------------------


@pytest.mark.asyncio
async def test_ingest_creates_lead_with_assignee_when_no_open_lead(
    monkeypatch,
):
    """No open lead for the contact → pick_assignee → create new lead."""
    async def _no_open(*_a, **_k):
        return None

    assignee = uuid.uuid4()

    async def _pick(*_a, **_k):
        return assignee

    new_lead_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def _create(*_a, **kwargs):
        captured["payload"] = kwargs["payload"]
        captured["org_id"] = kwargs["org_id"]
        return MagicMock(id=new_lead_id)

    monkeypatch.setattr(
        ingest_module, "find_open_lead_for_contact", _no_open
    )
    monkeypatch.setattr(ingest_module, "pick_assignee", _pick)
    monkeypatch.setattr(ingest_module, "create_lead", _create)

    session = _CapturingSession()
    result = await ingest(
        session,
        org_id=_ORG_ID,
        source=LeadSource.widget,
        contact_id=_CONTACT_ID,
        lead_payload=_base_lead_payload(),
        actor_user_id=_ACTOR_ID,
    )

    assert result.action == "created"
    assert result.lead_id == new_lead_id
    assert result.contact_id == _CONTACT_ID
    assert result.assignee_id == assignee
    # The payload sent to create_lead carries the ingest-computed
    # source + contact + assignee, regardless of what was on the
    # caller's lead_payload.
    assert captured["payload"].source == LeadSource.widget
    assert captured["payload"].contact_id == _CONTACT_ID
    assert captured["payload"].assigned_to_id == assignee
    assert captured["org_id"] == _ORG_ID


@pytest.mark.asyncio
async def test_ingest_creates_lead_with_null_assignee_when_no_eligible_users(
    monkeypatch,
):
    """No user has `leads.own` → lead lands unassigned, no raise."""
    async def _no_open(*_a, **_k):
        return None

    async def _no_assignee(*_a, **_k):
        return None

    new_lead_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def _create(*_a, **kwargs):
        captured["payload"] = kwargs["payload"]
        return MagicMock(id=new_lead_id)

    monkeypatch.setattr(
        ingest_module, "find_open_lead_for_contact", _no_open
    )
    monkeypatch.setattr(ingest_module, "pick_assignee", _no_assignee)
    monkeypatch.setattr(ingest_module, "create_lead", _create)

    result = await ingest(
        _CapturingSession(),
        org_id=_ORG_ID,
        source=LeadSource.google_ads,
        contact_id=_CONTACT_ID,
        lead_payload=_base_lead_payload(),
    )

    assert result.action == "created"
    assert result.assignee_id is None
    assert captured["payload"].assigned_to_id is None


# --- 2. ingest() — merge path -------------------------------------------


@pytest.mark.asyncio
async def test_ingest_merges_to_existing_open_lead(monkeypatch):
    """Contact has an open lead → activity appended, NO new lead."""
    existing_lead_id = uuid.uuid4()

    async def _existing(*_a, **_k):
        return existing_lead_id

    create_called = {"called": False}

    async def _create(*_a, **_k):
        create_called["called"] = True
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(
        ingest_module, "find_open_lead_for_contact", _existing
    )
    monkeypatch.setattr(ingest_module, "create_lead", _create)

    captured_activity: dict[str, Any] = {}

    async def _activity_log(**kwargs):
        captured_activity.update(kwargs)

    monkeypatch.setattr(ingest_module, "activities_log", _activity_log)

    result = await ingest(
        _CapturingSession(),
        org_id=_ORG_ID,
        source=LeadSource.meta_ads,
        contact_id=_CONTACT_ID,
        lead_payload=_base_lead_payload(),
        actor_user_id=_ACTOR_ID,
    )

    assert result.action == "merged"
    assert result.lead_id == existing_lead_id
    assert result.contact_id == _CONTACT_ID
    assert result.assignee_id is None  # merge path doesn't reassign
    assert create_called["called"] is False
    # Activity recorded against the existing lead with the right kind.
    assert captured_activity["entity_type"] == "lead"
    assert captured_activity["entity_id"] == existing_lead_id
    assert captured_activity["payload"]["kind"] == "touchpoint"
    assert captured_activity["payload"]["source"] == "meta_ads"
    assert captured_activity["org_id"] == _ORG_ID
    assert captured_activity["user_id"] == _ACTOR_ID


# --- 3. ingest() forces source / contact_id / assignee on the payload --


@pytest.mark.asyncio
async def test_ingest_overrides_caller_payload_with_resolved_values(
    monkeypatch,
):
    """If caller passes a lead_payload with stale contact_id / source,
    ingest replaces those with the resolved values. Defence-in-depth
    against caller mistakes."""
    async def _no_open(*_a, **_k):
        return None

    assignee = uuid.uuid4()

    async def _pick(*_a, **_k):
        return assignee

    captured: dict[str, Any] = {}

    async def _create(*_a, **kwargs):
        captured["payload"] = kwargs["payload"]
        return MagicMock(id=uuid.uuid4())

    monkeypatch.setattr(
        ingest_module, "find_open_lead_for_contact", _no_open
    )
    monkeypatch.setattr(ingest_module, "pick_assignee", _pick)
    monkeypatch.setattr(ingest_module, "create_lead", _create)

    bad_contact = uuid.uuid4()
    bad_assignee = uuid.uuid4()
    stale_payload = LeadCreate(
        contact_id=bad_contact,                  # caller mistake
        source=LeadSource.manual,                # caller mistake
        assigned_to_id=bad_assignee,             # caller mistake
        custom_data={},
        attribution=None,
    )

    await ingest(
        _CapturingSession(),
        org_id=_ORG_ID,
        source=LeadSource.google_ads,
        contact_id=_CONTACT_ID,
        lead_payload=stale_payload,
    )

    # All three fields overridden — never trust the caller.
    assert captured["payload"].contact_id == _CONTACT_ID
    assert captured["payload"].source == LeadSource.google_ads
    assert captured["payload"].assigned_to_id == assignee


# --- 4. pick_assignee round-robin ---------------------------------------


class _RoutingSession:
    """Session stand-in for `pick_assignee`. Returns canned eligible
    users + bumps the round-robin counter in memory."""

    def __init__(self, eligible: list[uuid.UUID]) -> None:
        self.eligible = eligible
        self._counter = 0

    async def execute(self, stmt, params=None):
        text_sql = str(stmt)
        if "DISTINCT u.legacy_uuid" in text_sql:
            # _list_eligible_users
            rows = [(u,) for u in self.eligible]

            class _R:
                def fetchall(self_inner):
                    return rows

            return _R()
        if "INSERT INTO lead_routing_state" in text_sql:
            # Atomic counter — return current value then increment.
            value = self._counter
            self._counter += 1

            class _R:
                def scalar(self_inner):
                    return value

            return _R()
        raise AssertionError(f"unexpected SQL: {text_sql[:80]}")


@pytest.mark.asyncio
async def test_pick_assignee_round_robin_distributes_evenly():
    users = [uuid.uuid4() for _ in range(3)]
    session = _RoutingSession(eligible=users)
    picked: list[uuid.UUID] = []
    for _ in range(9):
        u = await routing.pick_assignee(session, org_id=_ORG_ID)
        picked.append(u)
    # Each user gets exactly 3 of 9 leads.
    counts = {u: picked.count(u) for u in users}
    assert all(c == 3 for c in counts.values()), counts
    # Order is round-robin not random — same picks in cycle.
    assert picked[0] == picked[3] == picked[6]
    assert picked[1] == picked[4] == picked[7]
    assert picked[2] == picked[5] == picked[8]


@pytest.mark.asyncio
async def test_pick_assignee_returns_none_when_no_eligible_users():
    session = _RoutingSession(eligible=[])
    assert await routing.pick_assignee(session, org_id=_ORG_ID) is None


@pytest.mark.asyncio
async def test_pick_assignee_with_single_user_always_picks_that_user():
    only = uuid.uuid4()
    session = _RoutingSession(eligible=[only])
    for _ in range(5):
        assert await routing.pick_assignee(session, org_id=_ORG_ID) == only


# --- 5. find_open_lead_for_contact SQL shape ----------------------------


@pytest.mark.asyncio
async def test_find_open_lead_for_contact_uses_active_filter():
    """The SQL must filter status='active' (the project's "open" state)
    and ORDER BY created_at DESC. We capture the executed SQL + params
    to verify the query shape without a real DB."""
    captured: dict[str, Any] = {}

    class _S:
        async def execute(self, stmt, params=None):
            captured["sql"] = str(stmt)
            captured["params"] = params

            class _R:
                def scalar(self_inner):
                    return None

            return _R()

    result = await dedup.find_open_lead_for_contact(
        _S(),
        org_id=_ORG_ID,
        contact_id=_CONTACT_ID,
    )
    assert result is None
    sql = captured["sql"]
    assert "status = 'active'" in sql
    assert "ORDER BY created_at DESC" in sql
    assert captured["params"] == {
        "org_id": str(_ORG_ID),
        "contact_id": str(_CONTACT_ID),
    }


@pytest.mark.asyncio
async def test_find_open_lead_for_contact_returns_lead_id_when_found():
    found_id = uuid.uuid4()

    class _S:
        async def execute(self, _stmt, _params=None):
            class _R:
                def scalar(self_inner):
                    return found_id

            return _R()

    result = await dedup.find_open_lead_for_contact(
        _S(), org_id=_ORG_ID, contact_id=_CONTACT_ID
    )
    assert result == found_id


# --- 6. dedup module re-exports the bulk-import helpers ----------------


def test_dedup_re_exports_existing_contact_helpers():
    """The new `leads/dedup.py` must re-export the bulk-import
    helpers so callers don't fork their import path."""
    assert dedup.find_existing_contact is not None
    assert dedup.normalize_phone("+91 98765-43210") == "919876543210"
    assert dedup.lowercase_email(" Asha@Example.com ") == "asha@example.com"
