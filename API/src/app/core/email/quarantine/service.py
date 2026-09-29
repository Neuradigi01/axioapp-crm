"""Service layer for the quarantine + filter-rules module.

Owns transactions. Router delegates every mutation to a function here;
DAL does the SQL. Audit events fire on every state transition.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.core.audit import service as audit
from src.app.core.email.quarantine import data_access
from src.app.core.email.quarantine.models import (
    REASON_RATE_CAPPED,
    REASON_VIRUS_VERDICT,
    STATUS_HELD,
    EmailFilterRule,
    EmailQuarantine,
)
from src.app.core.email.quarantine.schemas import (
    BulkReleaseResult,
    FilterRuleIn,
    FilterRuleOut,
    QuarantineOut,
)
from src.app.shared.storage import get_storage
from src.app.shared.storage.keys import content_type_for, validate_prefix

logger = logging.getLogger(__name__)


_DEFAULT_FILTER_RULE_CAP_PER_ORG = 500


def _rule_cap_per_org() -> int:
    try:
        return max(
            1,
            int(
                os.getenv(
                    "EMAIL_FILTER_RULES_MAX_PER_ORG",
                    str(_DEFAULT_FILTER_RULE_CAP_PER_ORG),
                )
            ),
        )
    except ValueError:
        return _DEFAULT_FILTER_RULE_CAP_PER_ORG


class FilterRuleCapExceededError(Exception):
    """Router maps to 409."""


class FilterRuleDuplicateError(Exception):
    """Router maps to 409."""


class QuarantineReleaseBlockedError(Exception):
    """Router maps to 403 (virus_verdict / operator-locked rows)."""


# ---------------------------------------------------------------------------
# Filter rules
# ---------------------------------------------------------------------------


async def list_filter_rules(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID | None = None,
) -> list[FilterRuleOut]:
    rows = await data_access.list_filter_rules(db, org_id=org_id, endpoint_id=endpoint_id)
    return [FilterRuleOut.model_validate(r) for r in rows]


async def create_filter_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: FilterRuleIn,
) -> FilterRuleOut:
    """Add a rule for this org. 409 on cap breach or duplicate."""
    cap = _rule_cap_per_org()
    count = await data_access.count_rules_for_org(db, org_id=org_id)
    if count >= cap:
        raise FilterRuleCapExceededError(f"org has {count} rules; cap is {cap}")
    dupe = await data_access.find_rule_by_dedupe(
        db,
        org_id=org_id,
        endpoint_id=payload.endpoint_id,
        rule_type=payload.rule_type,
        match_kind=payload.match_kind,
        match_value=payload.match_value,
    )
    if dupe is not None:
        raise FilterRuleDuplicateError("a rule with this type + kind + value already exists")

    row = EmailFilterRule(
        org_id=org_id,
        endpoint_id=payload.endpoint_id,
        rule_type=payload.rule_type,
        match_kind=payload.match_kind,
        match_value=payload.match_value,
        label=payload.label,
        created_by_user_id=actor_user_id,
    )
    data_access.add_filter_rule(db, row)
    await db.commit()
    await db.refresh(row)

    await audit.log(
        "email_filter_rule.created",
        entity_type="email_filter_rule",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "rule_type": row.rule_type,
            "match_kind": row.match_kind,
            "match_value": row.match_value,
            "endpoint_id": str(row.endpoint_id) if row.endpoint_id else None,
        },
    )
    return FilterRuleOut.model_validate(row)


async def delete_filter_rule(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    id: uuid.UUID,
) -> None:
    row = await data_access.find_filter_rule_by_id(db, id=id, org_id=org_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="filter rule not found",
        )
    await data_access.delete_filter_rule(db, row)
    await db.commit()
    await audit.log(
        "email_filter_rule.deleted",
        entity_type="email_filter_rule",
        entity_id=id,
        org_id=org_id,
        user_id=actor_user_id,
        after={
            "rule_type": row.rule_type,
            "match_kind": row.match_kind,
            "match_value": row.match_value,
        },
    )


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------


async def list_quarantine(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    status: str | None = None,
    reason_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[QuarantineOut], int]:
    rows, total = await data_access.list_quarantine_for_org(
        db,
        org_id=org_id,
        status=status,
        reason_code=reason_code,
        limit=limit,
        offset=offset,
    )
    return [QuarantineOut.model_validate(r) for r in rows], total


async def enqueue_quarantine(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    endpoint_id: uuid.UUID | None,
    mailgun_delivery_id: str | None,
    from_address: str,
    from_display_name: str | None,
    to_recipient: str,
    subject: str | None,
    body_snippet: str | None,
    attachment_summary: list[dict[str, Any]],
    reason_code: str,
    reason_detail: dict[str, Any],
    pending_dir: Path,
) -> EmailQuarantine:
    """Insert one quarantine row. Called by the gate chain in
    :mod:`src.app.core.email.mailgun.tasks` (Step 4).

    The delivery's files (``payload.json`` + attachments) are copied
    from the short-lived local ``pending_dir`` into the storage backend
    under ``{org_id}/quarantine/{row_id}/`` so the held mail survives
    the ingest task's cleanup and a server rebuild. ``payload_path``
    stores that storage prefix.

    Virus verdicts land with ``blocked_release=True`` — the operator
    can only discard, never re-release.
    """
    blocked_release = reason_code == REASON_VIRUS_VERDICT
    row_id = uuid.uuid4()
    payload_prefix = f"{org_id}/quarantine/{row_id}"
    await _store_payload(pending_dir, payload_prefix)
    row = EmailQuarantine(
        id=row_id,
        org_id=org_id,
        endpoint_id=endpoint_id,
        mailgun_delivery_id=mailgun_delivery_id,
        from_address=from_address.lower().strip(),
        from_display_name=from_display_name,
        to_recipient=to_recipient.lower().strip(),
        subject=subject,
        body_snippet=body_snippet,
        attachment_summary=attachment_summary,
        reason_code=reason_code,
        reason_detail=reason_detail,
        payload_path=payload_prefix,
        blocked_release=blocked_release,
    )
    data_access.add_quarantine(db, row)
    await db.commit()
    await db.refresh(row)
    return row


async def release(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    id: uuid.UUID,
) -> QuarantineOut:
    """Re-play a held message through the normal ingest path.

    The actual re-persist happens in Step 4 (needs the ingest shared
    helper). Here we flip the row to ``released`` + emit audit. When
    Step 4 wires the persist replay, it re-reads the on-disk payload
    and calls ``_persist_inbound_email``.
    """
    row = await data_access.find_quarantine_by_id(db, id=id, org_id=org_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="quarantine row not found",
        )
    if row.status != STATUS_HELD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"quarantine row is already {row.status}",
        )
    if row.blocked_release:
        raise QuarantineReleaseBlockedError("virus_verdict rows can only be discarded")

    now = datetime.now(UTC)
    await data_access.mark_released(
        db,
        id=row.id,
        resolved_by_user_id=actor_user_id,
        now=now,
    )
    await db.commit()
    await db.refresh(row)

    await audit.log(
        "email_quarantine.released",
        entity_type="email_quarantine",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={"reason_code": row.reason_code, "from_address": row.from_address},
    )
    return QuarantineOut.model_validate(row)


async def discard(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    id: uuid.UUID,
) -> None:
    row = await data_access.find_quarantine_by_id(db, id=id, org_id=org_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="quarantine row not found",
        )
    if row.status != STATUS_HELD:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"quarantine row is already {row.status}",
        )
    now = datetime.now(UTC)
    await data_access.mark_discarded(db, id=row.id, resolved_by_user_id=actor_user_id, now=now)
    await db.commit()
    await _delete_payload(row.payload_path)
    await audit.log(
        "email_quarantine.discarded",
        entity_type="email_quarantine",
        entity_id=row.id,
        org_id=org_id,
        user_id=actor_user_id,
        after={"reason_code": row.reason_code, "from_address": row.from_address},
    )


async def bulk_release(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    ids: list[uuid.UUID],
) -> BulkReleaseResult:
    """Only ``rate_capped`` rows are safe to bulk-release (per plan).
    Other reasons return a per-id rejection reason.
    """
    released: list[uuid.UUID] = []
    rejected: list[dict[str, Any]] = []
    for row_id in ids:
        row = await data_access.find_quarantine_by_id(db, id=row_id, org_id=org_id)
        if row is None:
            rejected.append({"id": str(row_id), "reason": "not_found"})
            continue
        if row.reason_code != REASON_RATE_CAPPED:
            rejected.append({"id": str(row_id), "reason": "bulk_only_rate_capped"})
            continue
        if row.status != STATUS_HELD:
            rejected.append({"id": str(row_id), "reason": f"already_{row.status}"})
            continue
        if row.blocked_release:
            rejected.append({"id": str(row_id), "reason": "blocked_release"})
            continue
        now = datetime.now(UTC)
        await data_access.mark_released(db, id=row.id, resolved_by_user_id=actor_user_id, now=now)
        released.append(row.id)
    if released:
        await db.commit()
        await audit.log(
            "email_quarantine.bulk_released",
            entity_type="email_quarantine",
            entity_id=None,
            org_id=org_id,
            user_id=actor_user_id,
            after={"released_count": len(released), "rejected_count": len(rejected)},
        )
    return BulkReleaseResult(released=released, rejected=rejected)


async def _store_payload(pending_dir: Path, prefix: str) -> None:
    """Copy every file of a pending delivery into storage under
    `prefix`. Best-effort per file: a failed upload is logged and the
    row is still written, so the operator sees the held mail."""
    storage = get_storage()
    files = await asyncio.to_thread(
        lambda: (
            sorted(p for p in pending_dir.iterdir() if p.is_file()) if pending_dir.is_dir() else []
        )
    )
    for path in files:
        try:
            data = await asyncio.to_thread(path.read_bytes)
            await storage.put(
                f"{prefix}/{path.name}", data, content_type=content_type_for(path.name)
            )
        except Exception:
            logger.exception("quarantine.service: failed to store %s under %s", path.name, prefix)


async def _delete_payload(payload_path: str) -> None:
    """Delete a held payload from storage. Best-effort; missing = success.

    Rows written before payloads moved to storage hold a local
    ``pending-inbound/`` path instead of a storage prefix; the ingest
    task already removed that folder, so there is nothing to delete.
    """
    try:
        prefix = validate_prefix(payload_path)
    except ValueError:
        return
    try:
        await get_storage().delete_directory(prefix)
    except Exception as exc:  # noqa: BLE001
        logger.warning("quarantine.service: failed to remove %s: %s", payload_path, exc)


# ---------------------------------------------------------------------------
# Auto-purge (called by Step 3's Celery beat)
# ---------------------------------------------------------------------------


def _auto_purge_days() -> int:
    try:
        return max(
            1,
            int(os.getenv("EMAIL_QUARANTINE_AUTO_PURGE_DAYS", "30")),
        )
    except ValueError:
        return 30


async def auto_purge(db: AsyncSession) -> dict[str, Any]:
    """Delete held rows older than the retention window."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=_auto_purge_days())
    rows = await data_access.list_held_older_than(db, cutoff=cutoff)
    purged = 0
    for row in rows:
        await data_access.mark_auto_purged(db, id=row.id, now=now)
        purged += 1
    if purged:
        await db.commit()
        for row in rows:
            await _delete_payload(row.payload_path)
        logger.info("quarantine.auto_purge purged=%d cutoff=%s", purged, cutoff.isoformat())
    return {"purged": purged, "cutoff": cutoff.isoformat(), "at": now.isoformat()}


__all__ = [
    "FilterRuleCapExceededError",
    "FilterRuleDuplicateError",
    "QuarantineReleaseBlockedError",
    "auto_purge",
    "bulk_release",
    "create_filter_rule",
    "delete_filter_rule",
    "discard",
    "enqueue_quarantine",
    "list_filter_rules",
    "list_quarantine",
    "release",
]
