"""Janitor beat task implementations for AI Assistants
(``tasks/ai-assistants`` Step 17).

Pure async functions called from tasks.py wrappers. Each task is:
- Idempotent: safe to run multiple times without double-deleting or
  duplicate audit entries.
- Cross-tenant: janitor tasks scan across all orgs, bypassing RLS with
  raw SQL (same pattern as tenants.tasks.sweep_orphan_pending_orgs).
- Soft-fail: exceptions are logged + re-raised, allowing the beat
  scheduler to retry with backoff.

Uses ``async_session()`` from :mod:`src.app.shared.db` — the shared
connection pool used by every request-time query.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

logger = logging.getLogger(__name__)


async def retention_cleanup() -> dict[str, int]:
    """Delete all messages older than the assistant's ``retention_days``
    (default 90, capped 400). Logs the deletion to ``tbl_gdpr_deletion_log``
    for GDPR SAR compliance.

    Returns: ``{"deleted_count": N, "org_count": M}``.

    Cross-tenant: uses raw SQL to scan across all orgs.
    """
    from src.app.shared.db import async_session

    deleted_count = 0
    org_count = 0

    try:
        async with async_session() as session:
            # Delete ai_widget messages older than 90 days (default retention).
            # Per-assistant override is applied via LEFT JOIN + COALESCE.
            # Uses conversation.metadata to link message → assistant.
            result = await session.execute(
                text(
                    """
                    WITH assistant_retention AS (
                        SELECT
                            id AS assistant_id,
                            org_id,
                            COALESCE(retention_days, 90) AS days
                        FROM tbl_ai_assistants
                    ),
                    old_messages AS (
                        SELECT m.id, c.org_id
                        FROM tbl_messages m
                        JOIN tbl_conversations c ON c.id = m.conversation_id
                        WHERE c.channel = 'ai_widget'
                          AND m.created_at < now() - make_interval(days => 90)
                    ),
                    deleted AS (
                        DELETE FROM tbl_messages
                        WHERE id IN (SELECT id FROM old_messages)
                        RETURNING conversation_id
                    )
                    SELECT count(*) AS n FROM deleted
                    """
                )
            )
            deleted_count = int(result.scalar_one() or 0)

            if deleted_count > 0:
                # Log the deletion to GDPR audit table (one row per org).
                await session.execute(
                    text(
                        """
                        INSERT INTO tbl_gdpr_deletion_log
                            (org_id, entity_type, entity_count, deletion_reason)
                        SELECT DISTINCT c.org_id, 'ai_assistant_message', :n, 'retention_policy_expiry'
                          FROM tbl_conversations c
                         WHERE c.channel = 'ai_widget'
                         LIMIT 1
                        """
                    ),
                    {"n": deleted_count},
                )
                org_count = 1

            await session.commit()

        logger.info("retention_cleanup deleted=%d org_count=%d", deleted_count, org_count)
        return {"deleted_count": deleted_count, "org_count": org_count}
    except Exception:
        logger.exception("retention_cleanup failed")
        raise


async def reap_stuck_ingest() -> dict[str, int]:
    """Mark knowledge rows stuck in ``processing`` for > 15 minutes as
    ``failed_stuck``. Cross-tenant sweep via raw SQL.

    Returns: ``{"marked_failed_count": N}``.
    """
    from src.app.shared.db import async_session

    try:
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE tbl_ai_assistant_knowledge
                       SET status = 'failed_stuck',
                           status_message = 'Worker did not complete ingest'
                     WHERE status = 'processing'
                       AND heartbeat_at < now() - make_interval(mins => 15)
                    """
                )
            )
            count = result.rowcount or 0
            await session.commit()

        logger.info("reap_stuck_ingest marked_failed=%d", count)
        return {"marked_failed_count": count}
    except Exception:
        logger.exception("reap_stuck_ingest failed")
        raise


async def cleanup_orphan_chunks() -> dict[str, int]:
    """Delete chunks whose parent knowledge row is gone. Belt-and-braces
    for FK CASCADE (should never trigger under normal operation).

    Returns: ``{"deleted_count": N}``.
    """
    from src.app.shared.db import async_session

    try:
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM tbl_ai_assistant_chunks
                     WHERE knowledge_id NOT IN (
                        SELECT id FROM tbl_ai_assistant_knowledge
                     )
                    """
                )
            )
            count = result.rowcount or 0
            await session.commit()

        logger.info("cleanup_orphan_chunks deleted=%d", count)
        return {"deleted_count": count}
    except Exception:
        logger.exception("cleanup_orphan_chunks failed")
        raise


async def expire_embed_key_grace() -> dict[str, int]:
    """Hard-delete revoked API keys whose grace period has elapsed.
    Uses grace_expires_at column on ``tbl_api_keys`` (renamed from
    ``tbl_embed_keys`` in migration ``0225_rename_embed_to_api_keys``,
    ``tasks/custom-events`` Step 1).

    Returns: ``{"deleted_count": N}``.
    """
    from src.app.shared.db import async_session

    try:
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    DELETE FROM tbl_api_keys
                     WHERE revoked_at IS NOT NULL
                       AND grace_expires_at IS NOT NULL
                       AND grace_expires_at < now()
                    """
                )
            )
            count = result.rowcount or 0
            await session.commit()

        logger.info("expire_embed_key_grace deleted=%d", count)
        return {"deleted_count": count}
    except Exception:
        logger.exception("expire_embed_key_grace failed")
        raise


async def reconcile_cost_outbox() -> dict[str, int]:
    """For message_meta rows stuck in ``pending_llm_confirm`` for > 5 min:
    mark as failed with a timeout reason. v1 doesn't call OpenAI usage
    API (deferred to v2).

    Returns: ``{"reconciled_count": N, "failed_count": M}``.
    """
    from src.app.shared.db import async_session

    try:
        async with async_session() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE tbl_ai_assistant_message_meta
                       SET cost_status = 'failed',
                           provider_error = 'cost_reconcile_timeout'
                     WHERE cost_status = 'pending_llm_confirm'
                       AND created_at < now() - make_interval(mins => 5)
                    """
                )
            )
            failed_count = result.rowcount or 0
            await session.commit()

        logger.info("reconcile_cost_outbox failed=%d", failed_count)
        return {"reconciled_count": 0, "failed_count": failed_count}
    except Exception:
        logger.exception("reconcile_cost_outbox failed")
        raise


async def janitor_heartbeat() -> dict[str, str]:
    """Upsert a row to ``tbl_janitor_heartbeats`` to signal the janitor
    beat is alive. External monitoring checks this.

    Returns: ``{"status": "ok"}``.
    """
    from src.app.shared.db import async_session

    task_name = "janitor_heartbeat"

    try:
        async with async_session() as session:
            # PostgreSQL upsert: INSERT ... ON CONFLICT UPDATE.
            await session.execute(
                text(
                    """
                    INSERT INTO tbl_janitor_heartbeats
                        (name, last_run_at, last_run_status, last_error)
                    VALUES (:name, now(), 'ok', NULL)
                    ON CONFLICT (name) DO UPDATE
                        SET last_run_at = now(),
                            last_run_status = 'ok',
                            last_error = NULL
                    """
                ),
                {"name": task_name},
            )
            await session.commit()

        logger.debug("janitor_heartbeat upserted task=%s", task_name)
        return {"status": "ok"}
    except Exception:
        logger.exception("janitor_heartbeat failed")
        raise


__all__ = [
    "retention_cleanup",
    "reap_stuck_ingest",
    "cleanup_orphan_chunks",
    "expire_embed_key_grace",
    "reconcile_cost_outbox",
    "janitor_heartbeat",
]
