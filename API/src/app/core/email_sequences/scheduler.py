"""Pure async tick loop for the email-sequences beat task.

The Celery wrapper in `tasks.py` calls `tick()` every 60s. This module
holds the business logic so it stays testable without a Celery worker.

### What one tick does

1. **Cross-org sweep** — raw-SQL pick of up to `_TICK_LIMIT` due step
   rows (sorted by `scheduled_at` ASC). Beat has no JWT, so the sweep
   runs without tenant context; the per-row processor sets context
   from the row's `org_id` before any RLS-scoped query.
2. **Per-row processing** (each row gets its own session + transaction):
   * `SELECT … FOR UPDATE SKIP LOCKED` re-acquires the row so two
     workers never double-send.
   * Load enrollment + step def + sequence + template + sender's
     email account. Skip the row when the enrollment isn't active,
     the sequence / template is soft-deleted, or the sender has no
     live email account.
   * **Reply detection**: if any inbound `messages` row exists for
     the contact's email conversation since `enrolled_at`, flip the
     enrollment to `paused_on_reply` and skip the step.
   * **Render** the template via Step 6's `render_template`.
   * **Send** via `core.conversations.adapters.email.send_email`. On
     `HardCapExceeded`, push the scheduled_at to tomorrow same time
     and leave the enrollment active.
   * **Advance**: mark the step row `sent`, capture `messages.id`,
     bump `current_step_order`. If there's a next step, insert a fresh
     pending step row at `now + next.delay_days`. Else mark enrollment
     `completed`.

Per-row exceptions are caught + logged so a single bad row doesn't
kill the tick.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, select
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.conversations.adapters.email import (
    HardCapExceeded,
    send_email,
)
from src.app.core.conversations.models import (
    Conversation,
    ConversationChannel,
    Message,
    MessageDirection,
)
from src.app.core.email.models import (
    EmailAccount,
    EmailAccountSyncState,
)
from src.app.core.email_sequences.models import (
    EmailSequence,
    EmailSequenceEnrollment,
    EmailSequenceEnrollmentStep,
    EmailSequenceStep,
    EnrollmentState,
)
from src.app.core.templates import render as templates_render
from src.app.core.templates.models import (
    MessageTemplate,
    TemplateInternalStatus,
)
from src.app.core.tenants.models import Organization
from src.app.core.users.models import User
from src.app.shared.context import RequestContext, reset_context, set_context
from src.app.shared.db import async_session

log = logging.getLogger(__name__)


# Cap per tick — the beat runs every 60s, so 200 sends per worker per
# minute is 12k/hour throughput. Well within Gmail/Microsoft Graph
# rate limits and bounds wall-clock per tick.
_TICK_LIMIT = 200


async def tick() -> int:
    """No-op.

    Step 20 of the workflows track absorbed sequence runtime into the
    workflow engine + its Celery beat sweep. Existing enrollment-step
    rows on ``tbl_email_sequence_enrollment_steps`` are left in place
    (one release of read-only retention) but no longer fire — new
    enrollments land on ``tbl_workflow_runs`` via
    :func:`email_sequences.service.enroll` which now shims through
    :func:`core.workflows.engine.start_run`.

    The historical body (which selected due rows, sent emails, and
    rescheduled) is preserved in helper functions below for one
    release in case operators need a manual re-run for an in-flight
    enrollment; the beat-driven path is dead. Returns 0 so callers /
    log parsers that branch on the count keep working.
    """
    return 0


async def _pick_due_step_ids(*, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Cross-org raw-SQL sweep. Beat has no tenant context, so we use
    raw SQL (which the daemon DB role can run across all orgs) rather
    than the ORM (which short-circuits without `app.org_id` set).

    Returns `(enrollment_step_id, org_id)` pairs sorted by
    `scheduled_at` ASC. The per-row processor will re-lock the row
    with `FOR UPDATE SKIP LOCKED` inside its own transaction so two
    concurrent workers ticking simultaneously never double-send.
    """
    now = datetime.now(UTC)
    async with async_session() as session:
        rows = (
            (
                await session.execute(
                    sql_text(
                        """
                    SELECT id, org_id
                    FROM tbl_email_sequence_enrollment_steps
                    WHERE sent_at IS NULL
                      AND skipped = false
                      AND scheduled_at <= :now
                    ORDER BY scheduled_at ASC
                    LIMIT :limit
                    """
                    ),
                    {"now": now, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
    return [(r["id"], r["org_id"]) for r in rows]


async def _process_one(*, step_row_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Process a single due step under the row's tenant context."""
    async with async_session() as session:
        token = set_context(RequestContext(org_id=org_id, user_id=None))
        try:
            await _process_one_locked(session, step_row_id=step_row_id)
        finally:
            reset_context(token)


async def _process_one_locked(session: AsyncSession, *, step_row_id: uuid.UUID) -> None:
    """Inner: tenant context is already set on `session`. Wraps the
    step row in `FOR UPDATE SKIP LOCKED` so concurrent workers don't
    double-send."""
    step_row = (
        await session.execute(
            select(EmailSequenceEnrollmentStep)
            .where(
                EmailSequenceEnrollmentStep.id == step_row_id,
                EmailSequenceEnrollmentStep.sent_at.is_(None),
                EmailSequenceEnrollmentStep.skipped.is_(False),
            )
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()
    if step_row is None:
        # Taken by another worker, or already sent/skipped by a
        # pause/cancel that fired between sweep and lock.
        return

    enrollment = (
        await session.execute(
            select(EmailSequenceEnrollment).where(
                EmailSequenceEnrollment.id == step_row.enrollment_id
            )
        )
    ).scalar_one_or_none()
    if enrollment is None or enrollment.state != EnrollmentState.active.value:
        _skip(step_row, "enrollment_not_active")
        await session.commit()
        return

    step_def = (
        await session.execute(
            select(EmailSequenceStep).where(EmailSequenceStep.id == step_row.step_id)
        )
    ).scalar_one_or_none()
    if step_def is None:
        _skip(step_row, "step_definition_missing")
        await session.commit()
        return

    sequence = (
        await session.execute(
            select(EmailSequence).where(EmailSequence.id == enrollment.sequence_id)
        )
    ).scalar_one_or_none()
    if sequence is None or sequence.deleted_at is not None or not sequence.is_active:
        _skip(step_row, "sequence_inactive_or_deleted")
        enrollment.state = EnrollmentState.completed.value
        enrollment.state_changed_at = datetime.now(UTC)
        await session.commit()
        return

    template = (
        await session.execute(
            select(MessageTemplate).where(MessageTemplate.id == step_def.template_id)
        )
    ).scalar_one_or_none()
    if template is None or template.internal_status == TemplateInternalStatus.archived:
        _skip(step_row, "template_archived")
        await session.commit()
        return

    # Reply detection.
    if await _has_inbound_reply(
        session,
        contact_id=enrollment.contact_id,
        since=enrollment.enrolled_at,
    ):
        _skip(step_row, "paused_on_reply")
        enrollment.state = EnrollmentState.paused_on_reply.value
        enrollment.state_changed_at = datetime.now(UTC)
        await session.commit()
        return

    account = await _resolve_sender_account(session, sender_user_id=enrollment.enrolled_by)
    if account is None:
        _skip(step_row, "sender_no_live_email_account")
        await session.commit()
        return

    # Render.
    sender = (
        await session.execute(select(User).where(User.id == enrollment.enrolled_by))
    ).scalar_one_or_none()
    org = (
        await session.execute(select(Organization).where(Organization.id == enrollment.org_id))
    ).scalar_one_or_none()
    try:
        context = await templates_render.build_context(
            session,
            org=org,
            contact_id=enrollment.contact_id,
            lead_id=enrollment.lead_id,
            sender_user_id=enrollment.enrolled_by,
            sender_first_name=getattr(sender, "first_name", None),
            sender_last_name=getattr(sender, "last_name", None),
            sender_email=getattr(sender, "email", None),
            sender_signature=None,
        )
        rendered = templates_render.render_email_template(template, context)
    except Exception:
        log.exception("email_sequences: render failed step_row=%s", step_row.id)
        _skip(step_row, "render_failed")
        await session.commit()
        return

    # Send. HardCapExceeded → reschedule + leave enrollment active.
    try:
        result = await send_email(
            session,
            org_id=enrollment.org_id,
            sender_user_id=enrollment.enrolled_by,
            account_id=account.id,
            contact_id=enrollment.contact_id,
            subject=rendered["subject"],
            body_text=rendered["body_text"],
            body_html=rendered["body_html"],
        )
    except HardCapExceeded:
        step_row.scheduled_at = step_row.scheduled_at + timedelta(days=1)
        await session.commit()
        log.info(
            "email_sequences: daily cap, rescheduled step_row=%s",
            step_row.id,
        )
        return

    # Advance.
    now = datetime.now(UTC)
    step_row.sent_at = now
    step_row.message_id = result.message.id

    next_step = (
        await session.execute(
            select(EmailSequenceStep).where(
                EmailSequenceStep.sequence_id == enrollment.sequence_id,
                EmailSequenceStep.step_order == step_def.step_order + 1,
            )
        )
    ).scalar_one_or_none()
    if next_step is None:
        enrollment.state = EnrollmentState.completed.value
        enrollment.state_changed_at = now
    else:
        enrollment.current_step_order = next_step.step_order
        session.add(
            EmailSequenceEnrollmentStep(
                org_id=enrollment.org_id,
                enrollment_id=enrollment.id,
                step_id=next_step.id,
                scheduled_at=now + timedelta(days=next_step.delay_days),
            )
        )
    await session.commit()


def _skip(step_row: EmailSequenceEnrollmentStep, reason: str) -> None:
    """Mark a step row skipped — caller commits."""
    step_row.skipped = True
    step_row.skip_reason = reason


async def _has_inbound_reply(
    session: AsyncSession,
    *,
    contact_id: uuid.UUID,
    since: datetime,
) -> bool:
    """True iff there's any inbound email `messages` row in the
    contact's email conversation since `since`.

    Joins conversations on `channel='email'` AND `contact_id=…` so a
    WhatsApp reply doesn't count. We rely on `messages.direction`
    rather than the activities-payload JSON flag because the column
    is indexed and the JSON probe would table-scan.
    """
    stmt = select(
        exists().where(
            and_(
                Message.direction == MessageDirection.in_,
                Message.created_at >= since,
                Conversation.id == Message.conversation_id,
                Conversation.channel == ConversationChannel.email,
                Conversation.contact_id == contact_id,
            )
        )
    )
    return bool((await session.execute(stmt)).scalar())


async def _resolve_sender_account(
    session: AsyncSession, *, sender_user_id: uuid.UUID
) -> EmailAccount | None:
    """First live email account owned by the rep — None if none.

    Ordered by `connected_at` so the rep's first-connected mailbox is
    the default sender for sequence sends; reps who later add a second
    mailbox can disconnect the unwanted one to switch.
    """
    row = (
        await session.execute(
            select(EmailAccount)
            .where(
                EmailAccount.user_id == sender_user_id,
                EmailAccount.sync_state == EmailAccountSyncState.live,
            )
            .order_by(EmailAccount.connected_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


__all__ = ["tick"]
