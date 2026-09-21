"""Nightly + hourly domain-verify sweeps for ``tbl_organization_email_domains``.

Two Celery beat tasks drive the domain state machine forward:

  * :func:`sweep_email_domain_claims_nightly` — daily at 04:00 UTC.
    Re-verifies every ``pending`` and ``verified`` row against Mailgun.
    Demotes rows whose ``consecutive_failed_checks`` crosses
    ``EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS`` (default 3). Owner is
    notified on the ``pending → verified`` transition and on the
    ``verified → demoted`` transition.

  * :func:`sweep_demoted_domains_hourly` — every hour on the hour.
    Re-verifies ``demoted`` rows only. All-pass triggers the
    ``demoted → verified`` recovery + owner notify. Rows stuck in
    demoted longer than ``EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS``
    (default 14) are auto-released via
    :func:`service.release_domain` + owner notify.

Row lock: ``SELECT ... FOR UPDATE SKIP LOCKED`` at claim time so two
workers running the same beat cadence don't fight over the same
domain. :func:`verify_organization_email_domain` commits per-row on
the passed session, releasing the lock as it goes — the effective
coverage is "no two workers pick the same batch in the same tick",
which is what beat concurrency needs.

Notifications are best-effort — a failing owner-lookup or notify
never rolls back the domain state transition. Failures log at
``warning`` for operator visibility and count as ``skipped`` in the
sweep summary.

Autodiscover: this module is listed in :mod:`src.celery.worker`
(memory ``feedback_celery_task_autodiscover_list.md``). A missing
entry silently drops every beat-enqueued sweep with a ``KeyError``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from src.app.core.email.mailgun.api_client_errors import (
    MailgunApiError,
    MailgunProviderError,
)
from src.app.core.email_sender_setup import data_access
from src.app.core.email_sender_setup.models import (
    VERIFICATION_STATUS_DEMOTED,
    VERIFICATION_STATUS_PENDING,
    VERIFICATION_STATUS_VERIFIED,
)
from src.app.core.email_sender_setup.service import (
    release_domain,
    verify_organization_email_domain,
)
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)


# Thresholds — read at call time (not import) so tests can override
# via ``monkeypatch.setenv``.
def _demote_threshold() -> int:
    return int(os.getenv("EMAIL_DOMAIN_DEMOTE_AFTER_FAILED_CHECKS", "3"))


def _release_after_days() -> int:
    return int(os.getenv("EMAIL_DOMAIN_RELEASE_AFTER_FAILED_DAYS", "14"))


def _sweep_batch_limit() -> int:
    return int(os.getenv("EMAIL_DOMAIN_SWEEP_BATCH_LIMIT", "200"))


# Notification type keys the sweeps fire. All in the ``email.*`` module
# space so a downstream email-preference filter (Owner-in-app-only vs
# Owner-in-app-plus-email) can key on the prefix.
_NOTIF_VERIFIED = "email.sending_domain.verified"
_NOTIF_DEMOTED = "email.sending_domain.demoted"
_NOTIF_RECOVERED = "email.sending_domain.recovered"
_NOTIF_RELEASED_AUTO = "email.sending_domain.released_auto"


@celery.task(
    name="src.app.core.email_sender_setup.tasks.sweep_email_domain_claims_nightly",
    bind=True,
)
def sweep_email_domain_claims_nightly(self) -> dict[str, Any]:  # noqa: ARG001
    """Beat-triggered nightly at 04:00 UTC. See module docstring."""
    return asyncio.run(_sweep_nightly_async())


async def _sweep_nightly_async() -> dict[str, Any]:
    now = datetime.now(UTC)
    verified_count = 0
    demoted_count = 0
    failed_count = 0
    skipped_count = 0
    swept_ids: list[str] = []

    async with async_session() as session:
        rows = await data_access.lock_rows_for_sweep(
            session,
            statuses=[VERIFICATION_STATUS_PENDING, VERIFICATION_STATUS_VERIFIED],
            limit=_sweep_batch_limit(),
        )
        for row in rows:
            prior_status = row.verification_status
            swept_ids.append(str(row.id))
            try:
                updated = await verify_organization_email_domain(
                    session,
                    org_id=row.org_id,
                    id=row.id,
                    actor_user_id=None,
                )
            except MailgunProviderError:
                # 5xx is transient — Step 3 contract: don't bump the
                # failed counter. Retry next cadence.
                logger.warning(
                    "sweep_nightly: mailgun 5xx for domain=%s id=%s (skipped)",
                    row.domain,
                    row.id,
                )
                skipped_count += 1
                continue
            except MailgunApiError:
                logger.exception(
                    "sweep_nightly: mailgun API error for domain=%s id=%s",
                    row.domain,
                    row.id,
                )
                failed_count += 1
                continue

            # Transition: pending → verified (first-time verify).
            if (
                prior_status == VERIFICATION_STATUS_PENDING
                and updated.verification_status == VERIFICATION_STATUS_VERIFIED
            ):
                await _notify_owner_of_transition(
                    session,
                    org_id=row.org_id,
                    domain=row.domain,
                    notification_type=_NOTIF_VERIFIED,
                    title=f"Sending domain verified: {row.domain}",
                    body=(
                        f"All DNS records for {row.domain} are live. Your "
                        "campaigns and workflows can now send from this domain."
                    ),
                )
                verified_count += 1

            # Threshold check: bump-past-threshold triggers demotion.
            # Guard on ``status still verified`` because the recovery
            # branch handles the demoted case above (nightly only
            # sees pending/verified, but be defensive).
            if (
                updated.consecutive_failed_checks >= _demote_threshold()
                and updated.verification_status == VERIFICATION_STATUS_VERIFIED
            ):
                await data_access.mark_demoted(session, id=updated.id)
                await session.commit()
                await _notify_owner_of_transition(
                    session,
                    org_id=row.org_id,
                    domain=row.domain,
                    notification_type=_NOTIF_DEMOTED,
                    title=f"DNS drift detected: {row.domain}",
                    body=(
                        f"{row.domain} failed verification "
                        f"{updated.consecutive_failed_checks} times in a row. "
                        "Sends from this domain are paused until the DNS "
                        "records are restored. Check Settings → Email → "
                        "Sending Domains for details."
                    ),
                )
                demoted_count += 1

    logger.info(
        "sweep_nightly: verified=%d demoted=%d failed=%d skipped=%d ids=%s",
        verified_count,
        demoted_count,
        failed_count,
        skipped_count,
        swept_ids,
    )
    return {
        "verified": verified_count,
        "demoted": demoted_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "swept_ids": swept_ids,
        "at": now.isoformat(),
    }


@celery.task(
    name="src.app.core.email_sender_setup.tasks.sweep_demoted_domains_hourly",
    bind=True,
)
def sweep_demoted_domains_hourly(self) -> dict[str, Any]:  # noqa: ARG001
    """Beat-triggered every hour on the hour. See module docstring."""
    return asyncio.run(_sweep_hourly_async())


async def _sweep_hourly_async() -> dict[str, Any]:
    now = datetime.now(UTC)
    recovered_count = 0
    released_count = 0
    failed_count = 0
    skipped_count = 0
    swept_ids: list[str] = []
    release_cutoff = now - timedelta(days=_release_after_days())

    async with async_session() as session:
        rows = await data_access.lock_rows_for_sweep(
            session,
            statuses=[VERIFICATION_STATUS_DEMOTED],
            limit=_sweep_batch_limit(),
        )
        for row in rows:
            swept_ids.append(str(row.id))
            # Auto-release if stuck longer than the release threshold.
            if row.demoted_at is not None and row.demoted_at < release_cutoff:
                try:
                    await release_domain(
                        session,
                        org_id=row.org_id,
                        id=row.id,
                        actor_user_id=None,
                    )
                except MailgunApiError:
                    logger.exception(
                        "sweep_hourly: release failed for domain=%s id=%s",
                        row.domain,
                        row.id,
                    )
                    failed_count += 1
                    continue
                await _notify_owner_of_transition(
                    session,
                    org_id=row.org_id,
                    domain=row.domain,
                    notification_type=_NOTIF_RELEASED_AUTO,
                    title=f"Sending domain released: {row.domain}",
                    body=(
                        f"{row.domain} has been stuck in the DNS-drift "
                        f"state for {_release_after_days()} days and has "
                        "been released. Sends will fall back to the "
                        "platform's shared sending domain until you claim "
                        "a new one."
                    ),
                )
                released_count += 1
                continue

            # Recovery path — re-verify demoted rows. The service
            # calls mark_verified_after_demotion internally when the
            # verdict is all-pass, so we just watch for the state
            # transition and fire the recovery notification.
            try:
                updated = await verify_organization_email_domain(
                    session,
                    org_id=row.org_id,
                    id=row.id,
                    actor_user_id=None,
                )
            except MailgunProviderError:
                logger.warning(
                    "sweep_hourly: mailgun 5xx for demoted domain=%s id=%s (skipped)",
                    row.domain,
                    row.id,
                )
                skipped_count += 1
                continue
            except MailgunApiError:
                logger.exception(
                    "sweep_hourly: mailgun API error for demoted domain=%s id=%s",
                    row.domain,
                    row.id,
                )
                failed_count += 1
                continue

            if updated.verification_status == VERIFICATION_STATUS_VERIFIED:
                await _notify_owner_of_transition(
                    session,
                    org_id=row.org_id,
                    domain=row.domain,
                    notification_type=_NOTIF_RECOVERED,
                    title=f"Sending domain recovered: {row.domain}",
                    body=(
                        f"DNS records for {row.domain} are back in order. "
                        "Sends from this domain are live again."
                    ),
                )
                recovered_count += 1

    logger.info(
        "sweep_hourly: recovered=%d released=%d failed=%d skipped=%d ids=%s",
        recovered_count,
        released_count,
        failed_count,
        skipped_count,
        swept_ids,
    )
    return {
        "recovered": recovered_count,
        "released": released_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "swept_ids": swept_ids,
        "at": now.isoformat(),
    }


async def _notify_owner_of_transition(
    session,
    *,
    org_id: uuid.UUID,
    domain: str,
    notification_type: str,
    title: str,
    body: str,
) -> None:
    """Send an in-app notification to the org's Owner.

    Best-effort — failures (Owner lookup miss, notify service down,
    audit write error) never propagate. The sweep counts the outcome
    on its own summary; the caller doesn't rely on this succeeding.

    Late imports (notifications, permissions, users) keep the sweep
    module's cold-start narrow — nothing loads the notification
    stack unless a transition actually fires.
    """
    try:
        from src.app.core.notifications.service import notify
        from src.app.core.permissions.models import Role
        from src.app.core.users.models import OrganizationMember, User

        owner_row = (
            await session.execute(
                select(User.legacy_uuid)
                .join(
                    OrganizationMember,
                    OrganizationMember.user_member_id == User.id,
                )
                .join(Role, Role.id == OrganizationMember.role_id)
                .where(OrganizationMember.organization_id == org_id)
                .where(OrganizationMember.is_active.is_(True))
                .where(Role.name == "Owner")
                .where(Role.is_system.is_(True))
                .limit(1)
            )
        ).scalar_one_or_none()
        if owner_row is None:
            logger.warning(
                "sending_domain_notify: no active Owner for org=%s domain=%s "
                "(notification skipped)",
                org_id,
                domain,
            )
            return
        await notify(
            org_id=org_id,
            user_id=owner_row,
            type=notification_type,
            title=title,
            body=body,
            payload={"domain": domain},
        )
    except Exception:
        logger.exception(
            "sending_domain_notify failed org=%s domain=%s type=%s",
            org_id,
            domain,
            notification_type,
        )


__all__ = [
    "sweep_demoted_domains_hourly",
    "sweep_email_domain_claims_nightly",
]
