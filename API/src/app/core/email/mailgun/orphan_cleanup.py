"""Orphan sweepers for the Mailgun ingest pipeline.

Two sibling tasks live here:

  * :func:`sweep_staging_orphans` — remove
    ``./storage/{org_id}/staging/{request_id}/`` directories older
    than 1 hour. Staging dirs are only referenced by an in-flight
    ingest task; anything older than that is either a mid-crash
    ingest that never committed or a repro-artifact.

  * :func:`sweep_messages_orphans` — remove committed attachments
    (``{org_id}/messages/{message_id}/`` in the storage backend) whose
    ``tbl_messages`` row no longer exists. ``commit_attachments`` only
    uploads after the row commits, so a missing row always means the
    message was deleted later — no age threshold is needed.

Cadence rationale:
  * Staging sweep every 15 min (fast + cheap; staging dirs are
    small).
  * Messages sweep daily (one storage listing per org; no urgency).

Both are best-effort — a filesystem hiccup logs a warning and moves
on. The next tick picks up whatever the previous tick missed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from src.app.core.email.mailgun import data_access as mailgun_da
from src.app.shared.db import async_session
from src.app.shared.storage import get_storage, storage_root
from src.celery.worker import celery

logger = logging.getLogger(__name__)

_STAGING_MIN_AGE_SECONDS = 3600  # 1 hour


def _iter_org_dirs() -> list[Path]:
    """Every top-level ``./storage/<org_id>/`` — skips reserved
    names like ``pending-inbound`` that live at the same level."""
    root = storage_root()
    if not root.exists():
        return []
    out: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        # UUID-shaped names only — skips pending-inbound/, tmp/, etc.
        try:
            uuid.UUID(entry.name)
        except ValueError:
            continue
        out.append(entry)
    return out


def _rm_dir_quiet(path: Path) -> bool:
    """Delete a directory + all contents. Returns True on success."""
    import shutil

    try:
        shutil.rmtree(path)
        return True
    except FileNotFoundError:
        return True
    except Exception as exc:  # pragma: no cover — filesystem hiccup
        logger.warning("mailgun.orphan_cleanup: failed to remove %s: %s", path, exc)
        return False


@celery.task(
    name="src.app.core.email.mailgun.orphan_cleanup.sweep_staging_orphans",
    bind=True,
)
def sweep_staging_orphans(self) -> int:  # noqa: ARG001
    """Remove staging dirs older than 1 hour."""
    now = time.time()
    removed = 0
    for org_dir in _iter_org_dirs():
        staging_root = org_dir / "staging"
        if not staging_root.exists():
            continue
        for child in staging_root.iterdir():
            if not child.is_dir():
                continue
            try:
                age = now - child.stat().st_mtime
            except FileNotFoundError:
                continue
            if age < _STAGING_MIN_AGE_SECONDS:
                continue
            if _rm_dir_quiet(child):
                removed += 1
    if removed:
        logger.info("mailgun.sweep_staging_orphans removed %d staged dir(s)", removed)
    return removed


@celery.task(
    name="src.app.core.email.mailgun.orphan_cleanup.sweep_messages_orphans",
    bind=True,
)
def sweep_messages_orphans(self) -> int:  # noqa: ARG001
    """Remove committed attachments whose ``tbl_messages`` row is gone."""
    return asyncio.run(_sweep_messages_orphans_async())


async def _sweep_messages_orphans_async() -> int:
    storage = get_storage()
    removed = 0
    async with async_session() as session:
        org_ids = await mailgun_da.list_org_ids(session)
        # {message_id: org_id} for every committed-attachment folder.
        # Keys are `{org}/messages/{message_id}/{file}`.
        stored: dict[uuid.UUID, uuid.UUID] = {}
        for org_id in org_ids:
            async for key in storage.list_keys(f"{org_id}/messages"):
                parts = key.split("/")
                try:
                    stored[uuid.UUID(parts[2])] = org_id
                except (IndexError, ValueError):
                    continue
        if not stored:
            return 0
        existing = await mailgun_da.existing_message_ids(session, set(stored))

    for message_id, org_id in stored.items():
        if message_id in existing:
            continue
        try:
            await storage.delete_directory(f"{org_id}/messages/{message_id}")
        except Exception as exc:  # best-effort; next tick retries
            logger.warning(
                "mailgun.orphan_cleanup: failed to remove message=%s: %s", message_id, exc
            )
            continue
        removed += 1

    if removed:
        logger.info("mailgun.sweep_messages_orphans removed %d orphan message(s)", removed)
    return removed


__all__ = ["sweep_messages_orphans", "sweep_staging_orphans"]
