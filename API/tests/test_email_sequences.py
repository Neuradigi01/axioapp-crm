"""Step 7 — email_sequences tests.

Five groups:

  1. `_validate_template_ids` — rejects unknown / cross-org / soft-
     deleted template ids.
  2. `create_sequence` — happy path materialises step rows; cross-org
     template id raises 400.
  3. `enroll` — bulk path materialises step-1 row per contact;
     duplicate enrollment skipped with reason `already_enrolled`;
     lead_ids length mismatch raises 400.
  4. `pause_enrollment` / `resume_enrollment` / `cancel_enrollment`
     — state machine + pending-step row marking.
  5. `scheduler._has_inbound_reply` / `scheduler._resolve_sender_account`
     — the two helpers the tick loop hinges on.

Convention: no real DB. `_CapturingSession` stages SELECT results in
order so each test scripts the session's view of the world.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.app.core.email_sequences import scheduler as sequence_scheduler
from src.app.core.email_sequences import service as sequences_service
from src.app.core.email_sequences.models import (
    EmailSequence,
    EmailSequenceEnrollment,
    EmailSequenceEnrollmentStep,
    EmailSequenceStep,
    EnrollmentState,
)
from src.app.core.email_sequences.schemas import (
    EmailSequenceCreate,
    EmailSequenceStepCreate,
)

_ORG_ID = uuid.uuid4()
_ACTOR_ID = uuid.uuid4()


# --- session stand-in -----------------------------------------------------


class _ScalarResult:
    """`session.execute(...)` return wrapper. The four observers used
    by service.py + scheduler.py are: scalar_one, scalar_one_or_none,
    scalar, scalars().all()."""

    def __init__(
        self,
        value: Any = None,
        *,
        rows: list[Any] | None = None,
    ) -> None:
        self._value = value
        self._rows = list(rows) if rows is not None else None

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._value

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        if self._rows is not None:
            return list(self._rows)
        return [self._value] if self._value is not None else []


class _CapturingSession:
    """Minimal AsyncSession stand-in — stages execute() responses in
    FIFO order so each test scripts the session's view."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.queue: list[Any] = []
        self.deleted_filters: list[Any] = []

    def stage(self, response: Any) -> None:
        self.queue.append(response)

    async def execute(self, _stmt: Any) -> Any:
        if not self.queue:
            raise AssertionError("no staged response left; called execute() one extra time")
        return self.queue.pop(0)

    def add(self, row: Any) -> None:
        self.added.append(row)
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not getattr(row, "created_at", None):
            row.created_at = now
        if hasattr(row, "updated_at") and not row.updated_at:
            row.updated_at = now

    def add_all(self, rows: list[Any]) -> None:
        for r in rows:
            self.add(r)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def refresh(self, _row: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _silence_audit(monkeypatch):
    """audit.log opens its own session — stub to no-op."""

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(sequences_service.audit, "log", _noop)


# --- 1. _validate_template_ids -------------------------------------------


class TestValidateTemplateIds:
    @pytest.mark.asyncio
    async def test_happy_known_ids(self):
        session = _CapturingSession()
        tids = [uuid.uuid4(), uuid.uuid4()]
        # Stage: a row for each (so the diff finds nothing missing).
        rows = [SimpleRow(id=t) for t in tids]
        session.stage(_ScalarResult(rows=rows))
        # No exception → pass.
        await sequences_service._validate_template_ids(session, org_id=_ORG_ID, template_ids=tids)

    @pytest.mark.asyncio
    async def test_empty_skips_query(self):
        session = _CapturingSession()
        # No stage — proves no DB call.
        await sequences_service._validate_template_ids(session, org_id=_ORG_ID, template_ids=[])

    @pytest.mark.asyncio
    async def test_unknown_id_rejected(self):
        from fastapi import HTTPException

        session = _CapturingSession()
        known = uuid.uuid4()
        unknown = uuid.uuid4()
        session.stage(_ScalarResult(rows=[SimpleRow(id=known)]))
        with pytest.raises(HTTPException) as exc:
            await sequences_service._validate_template_ids(
                session, org_id=_ORG_ID, template_ids=[known, unknown]
            )
        assert exc.value.status_code == 400
        assert str(unknown) in str(exc.value.detail)


# --- 2. create_sequence --------------------------------------------------


class TestCreateSequence:
    @pytest.mark.asyncio
    async def test_happy_materialises_steps(self):
        session = _CapturingSession()
        t1, t2, t3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        payload = EmailSequenceCreate(
            name="Designer outreach",
            is_active=True,
            steps=[
                EmailSequenceStepCreate(delay_days=0, template_id=t1),
                EmailSequenceStepCreate(delay_days=2, template_id=t2),
                EmailSequenceStepCreate(delay_days=5, template_id=t3),
            ],
        )
        # Stage: template validation finds all three.
        session.stage(_ScalarResult(rows=[SimpleRow(id=t1), SimpleRow(id=t2), SimpleRow(id=t3)]))
        seq, steps = await sequences_service.create_sequence(
            session,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            payload=payload,
        )
        assert seq.name == "Designer outreach"
        assert seq.org_id == _ORG_ID
        assert seq.created_by == _ACTOR_ID
        # Three step rows added in order with dense 1-based step_order.
        step_rows = [r for r in session.added if isinstance(r, EmailSequenceStep)]
        assert len(step_rows) == 3
        assert [s.step_order for s in step_rows] == [1, 2, 3]
        assert [s.delay_days for s in step_rows] == [0, 2, 5]
        assert [s.template_id for s in step_rows] == [t1, t2, t3]

    @pytest.mark.asyncio
    async def test_cross_org_template_id_400(self):
        from fastapi import HTTPException

        session = _CapturingSession()
        t1 = uuid.uuid4()
        # Stage: validation returns 0 rows → t1 looks unknown.
        session.stage(_ScalarResult(rows=[]))
        payload = EmailSequenceCreate(
            name="X",
            steps=[EmailSequenceStepCreate(delay_days=0, template_id=t1)],
        )
        with pytest.raises(HTTPException) as exc:
            await sequences_service.create_sequence(
                session,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                payload=payload,
            )
        assert exc.value.status_code == 400


# --- 3. enroll -----------------------------------------------------------


class TestEnroll:
    @pytest.mark.asyncio
    async def test_bulk_happy(self):
        session = _CapturingSession()
        sequence_id = uuid.uuid4()
        seq = _make_sequence(sequence_id=sequence_id)
        step1 = _make_step(sequence_id=sequence_id, step_order=1)
        # get_sequence → seq.
        session.stage(_ScalarResult(value=seq))
        # _load_steps → [step1].
        session.stage(_ScalarResult(rows=[step1]))
        # dedupe lookup → no prior enrollments.
        session.stage(_ScalarResult(rows=[]))
        contact_ids = [uuid.uuid4() for _ in range(5)]
        results = await sequences_service.enroll(
            session,
            sequence_id=sequence_id,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            contact_ids=contact_ids,
        )
        # 5 enrollments + 5 step rows.
        enrollments = [r for r in session.added if isinstance(r, EmailSequenceEnrollment)]
        step_rows = [r for r in session.added if isinstance(r, EmailSequenceEnrollmentStep)]
        assert len(enrollments) == 5
        assert len(step_rows) == 5
        # Every result is enrolled=True with the right contact_id.
        assert {r.contact_id for r in results} == set(contact_ids)
        assert all(r.enrolled for r in results)
        assert all(r.skip_reason is None for r in results)

    @pytest.mark.asyncio
    async def test_dedupe_already_enrolled(self):
        session = _CapturingSession()
        sequence_id = uuid.uuid4()
        seq = _make_sequence(sequence_id=sequence_id)
        step1 = _make_step(sequence_id=sequence_id, step_order=1)
        contact_a, contact_b = uuid.uuid4(), uuid.uuid4()
        existing_id = uuid.uuid4()
        # get_sequence → seq; _load_steps → [step1]; dedupe → contact_a
        # is blocked by an existing enrollment.
        session.stage(_ScalarResult(value=seq))
        session.stage(_ScalarResult(rows=[step1]))
        session.stage(
            _ScalarResult(
                rows=[
                    SimpleRow(contact_id=contact_a, id=existing_id),
                ]
            )
        )
        results = await sequences_service.enroll(
            session,
            sequence_id=sequence_id,
            org_id=_ORG_ID,
            actor_id=_ACTOR_ID,
            contact_ids=[contact_a, contact_b],
        )
        # Order preserved: contact_a first (skipped), contact_b second
        # (enrolled).
        assert results[0].contact_id == contact_a
        assert results[0].enrolled is False
        assert results[0].skip_reason == "already_enrolled"
        assert results[0].enrollment_id == existing_id
        assert results[1].contact_id == contact_b
        assert results[1].enrolled is True

    @pytest.mark.asyncio
    async def test_lead_ids_length_mismatch_400(self):
        from fastapi import HTTPException

        session = _CapturingSession()
        sequence_id = uuid.uuid4()
        seq = _make_sequence(sequence_id=sequence_id)
        step1 = _make_step(sequence_id=sequence_id, step_order=1)
        session.stage(_ScalarResult(value=seq))
        session.stage(_ScalarResult(rows=[step1]))
        with pytest.raises(HTTPException) as exc:
            await sequences_service.enroll(
                session,
                sequence_id=sequence_id,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                contact_ids=[uuid.uuid4(), uuid.uuid4()],
                lead_ids=[uuid.uuid4()],  # mismatched length
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_inactive_sequence_blocks_enroll(self):
        from fastapi import HTTPException

        session = _CapturingSession()
        sequence_id = uuid.uuid4()
        seq = _make_sequence(sequence_id=sequence_id, is_active=False)
        step1 = _make_step(sequence_id=sequence_id, step_order=1)
        session.stage(_ScalarResult(value=seq))
        session.stage(_ScalarResult(rows=[step1]))
        with pytest.raises(HTTPException) as exc:
            await sequences_service.enroll(
                session,
                sequence_id=sequence_id,
                org_id=_ORG_ID,
                actor_id=_ACTOR_ID,
                contact_ids=[uuid.uuid4()],
            )
        assert exc.value.status_code == 409


# --- 4. pause / resume / cancel ------------------------------------------


class TestPauseResumeCancel:
    @pytest.mark.asyncio
    async def test_pause_marks_pending_skipped(self):
        session = _CapturingSession()
        enrollment = _make_enrollment(state=EnrollmentState.active.value)
        session.stage(_ScalarResult(value=enrollment))
        # The pending-step UPDATE is the second execute call.
        session.stage(_ScalarResult(value=None))
        result = await sequences_service.pause_enrollment(
            session, enrollment_id=enrollment.id, actor_id=_ACTOR_ID
        )
        assert result.state == EnrollmentState.paused_manual.value
        # session.commit was called.
        assert session.commits == 1

    @pytest.mark.asyncio
    async def test_pause_terminal_raises_409(self):
        from fastapi import HTTPException

        session = _CapturingSession()
        enrollment = _make_enrollment(state=EnrollmentState.completed.value)
        session.stage(_ScalarResult(value=enrollment))
        with pytest.raises(HTTPException) as exc:
            await sequences_service.pause_enrollment(
                session,
                enrollment_id=enrollment.id,
                actor_id=_ACTOR_ID,
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_resume_reschedules_step(self):
        session = _CapturingSession()
        enrollment = _make_enrollment(
            state=EnrollmentState.paused_manual.value,
            current_step_order=2,
        )
        step2 = _make_step(
            sequence_id=enrollment.sequence_id,
            step_order=2,
            delay_days=3,
        )
        # get_enrollment → enrollment; _load_steps → [step2].
        session.stage(_ScalarResult(value=enrollment))
        session.stage(_ScalarResult(rows=[step2]))
        result = await sequences_service.resume_enrollment(
            session,
            enrollment_id=enrollment.id,
            actor_id=_ACTOR_ID,
        )
        assert result.state == EnrollmentState.active.value
        # A fresh enrollment-step row was added at now + 3 days.
        es = [r for r in session.added if isinstance(r, EmailSequenceEnrollmentStep)]
        assert len(es) == 1
        assert es[0].step_id == step2.id
        delta = es[0].scheduled_at - datetime.now(UTC)
        assert timedelta(days=2, hours=23) < delta < timedelta(days=3, hours=1)

    @pytest.mark.asyncio
    async def test_cancel_is_terminal(self):
        session = _CapturingSession()
        enrollment = _make_enrollment(state=EnrollmentState.active.value)
        session.stage(_ScalarResult(value=enrollment))
        session.stage(_ScalarResult(value=None))  # pending-step UPDATE
        result = await sequences_service.cancel_enrollment(
            session,
            enrollment_id=enrollment.id,
            actor_id=_ACTOR_ID,
        )
        assert result.state == EnrollmentState.cancelled.value

    @pytest.mark.asyncio
    async def test_cancel_terminal_idempotent(self):
        session = _CapturingSession()
        enrollment = _make_enrollment(state=EnrollmentState.cancelled.value)
        session.stage(_ScalarResult(value=enrollment))
        result = await sequences_service.cancel_enrollment(
            session,
            enrollment_id=enrollment.id,
            actor_id=_ACTOR_ID,
        )
        assert result.state == EnrollmentState.cancelled.value
        # No state mutation, no commit.
        assert session.commits == 0


# --- 5. scheduler primitives ---------------------------------------------


class TestSchedulerHelpers:
    @pytest.mark.asyncio
    async def test_has_inbound_reply_true_when_exists(self):
        session = _CapturingSession()
        session.stage(_ScalarResult(value=True))
        result = await sequence_scheduler._has_inbound_reply(
            session,
            contact_id=uuid.uuid4(),
            since=datetime.now(UTC) - timedelta(days=1),
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_has_inbound_reply_false_when_absent(self):
        session = _CapturingSession()
        session.stage(_ScalarResult(value=None))
        result = await sequence_scheduler._has_inbound_reply(
            session,
            contact_id=uuid.uuid4(),
            since=datetime.now(UTC) - timedelta(days=1),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_resolve_sender_account_returns_first_live(self):
        session = _CapturingSession()
        fake_account = SimpleRow(id=uuid.uuid4(), user_id=_ACTOR_ID)
        session.stage(_ScalarResult(value=fake_account))
        result = await sequence_scheduler._resolve_sender_account(session, sender_user_id=_ACTOR_ID)
        assert result is fake_account

    @pytest.mark.asyncio
    async def test_resolve_sender_account_none_when_no_live(self):
        session = _CapturingSession()
        session.stage(_ScalarResult(value=None))
        result = await sequence_scheduler._resolve_sender_account(session, sender_user_id=_ACTOR_ID)
        assert result is None


# --- helpers --------------------------------------------------------------


class SimpleRow:
    """Lightweight stand-in for an ORM row — every kwarg becomes an
    attribute. Used where the service / scheduler only inspects a few
    attributes."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_sequence(
    *,
    sequence_id: uuid.UUID | None = None,
    is_active: bool = True,
) -> EmailSequence:
    seq = EmailSequence(
        org_id=_ORG_ID,
        name="t",
        is_active=is_active,
        created_by=_ACTOR_ID,
    )
    seq.id = sequence_id or uuid.uuid4()
    seq.deleted_at = None
    seq.created_at = datetime.now(UTC)
    seq.updated_at = datetime.now(UTC)
    return seq


def _make_step(
    *,
    sequence_id: uuid.UUID,
    step_order: int,
    delay_days: int = 0,
) -> EmailSequenceStep:
    step = EmailSequenceStep(
        org_id=_ORG_ID,
        sequence_id=sequence_id,
        step_order=step_order,
        delay_days=delay_days,
        template_id=uuid.uuid4(),
    )
    step.id = uuid.uuid4()
    step.created_at = datetime.now(UTC)
    return step


def _make_enrollment(
    *,
    state: str = "active",
    current_step_order: int = 1,
) -> EmailSequenceEnrollment:
    enrollment = EmailSequenceEnrollment(
        org_id=_ORG_ID,
        sequence_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        lead_id=None,
        enrolled_by=_ACTOR_ID,
        state=state,
        current_step_order=current_step_order,
    )
    enrollment.id = uuid.uuid4()
    enrollment.enrolled_at = datetime.now(UTC) - timedelta(days=1)
    enrollment.state_changed_at = datetime.now(UTC)
    return enrollment
