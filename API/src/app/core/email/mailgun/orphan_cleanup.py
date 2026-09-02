"""Filesystem orphan sweepers for the Mailgun ingest pipeline.

Two sibling tasks live here:

  * :func:`sweep_staging_orphans` — remove
    ``./storage/{org_id}/staging/{request_id}/`` directories older
    than 1 hour. Staging dirs are only referenced by an in-flight
    ingest task; anything older than that is either a mid-crash
    ingest that never committed or a repro-artifact.

  * :func:`sweep_messages_orphans` — remove
    ``./storage/{org_id}/messages/{message_id}/`` directories that
    don't correspond to a ``tbl_messages`` row and are older than
    24 hours. Catches the (rare) case where a Message row was
    deleted or its transaction rolled back after commit_attachments
    already moved the files in.

Cadence rationale:
  * Staging sweep every 15 min (fast + cheap; staging dirs are
    small).
  * Messages sweep daily (slow + orphaned files here are already
    24h old; no urgency).

Both are best-effort — a filesystem hiccup logs a warning and moves
on. The next tick picks up whatever the previous tick missed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from sqlalchemy import select

from src.app.core.conversations.models import Message
from src.app.shared.db import async_session
from src.celery.worker import celery

logger = logging.getLogger(__name__)

_STORAGE_ROOT_ENV = "STORAGE_ROOT"
_DEFAULT_STORAGE_ROOT = "./storage"
_STAGING_MIN_AGE_SECONDS = 3600  # 1 hour
_MESSAGES_ORPHAN_MIN_AGE_SECONDS = 86400  # 24 hours


def _storage_root() -> Path:
    return Path(os.getenv(_STORAGE_ROOT_ENV, _DEFAULT_STORAGE_ROOT))


def _iter_org_dirs() -> list[Path]:
    """Every top-level ``./storage/<org_id>/`` — skips reserved
    names like ``pending-inbound`` that live at the same level."""
    root = _storage_root()
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
        logger.warning(
            "mailgun.orphan_cleanup: failed to remove %s: %s", path, exc
        )
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
        logger.info(
            "mailgun.sweep_staging_orphans removed %d staged dir(s)", removed
        )
    return removed


@celery.task(
    name="src.app.core.email.mailgun.orphan_cleanup.sweep_messages_orphans",
    bind=True,
)
def sweep_messages_orphans(self) -> int:  # noqa: ARG001
    """Remove messages/{msg_id}/ dirs older than 24h with no matching
    ``tbl_messages`` row."""
    return asyncio.run(_sweep_messages_orphans_async())


async def _sweep_messages_orphans_async() -> int:
    now = time.time()
    removed = 0
    async with async_session() as session:
        for org_dir in _iter_org_dirs():
            messages_root = org_dir / "messages"
            if not messages_root.exists():
                continue

            # Collect candidate dirs older than the threshold. Batch
            # the row-existence check into one query per org to keep
            # the sweep O(orgs) not O(orphans).
            candidates: list[tuple[Path, uuid.UUID]] = []
            for child in messages_root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    msg_uuid = uuid.UUID(child.name)
                except ValueError:
                    continue
                try:
                    age = now - child.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age < _MESSAGES_ORPHAN_MIN_AGE_SECONDS:
                    continue
                candidates.append((child, msg_uuid))

            if not candidates:
                continue

            existing = {
                row[0]
                for row in (
                    await session.execute(
                        select(Message.id).where(
                            Message.id.in_([mid for _, mid in candidates])
                        )
                    )
                ).all()
            }
            for child_path, mid in candidates:
                if mid in existing:
                    continue
                if _rm_dir_quiet(child_path):
                    removed += 1

    if removed:
        logger.info(
            "mailgun.sweep_messages_orphans removed %d orphan dir(s)", removed
        )
    return removed


__all__ = ["sweep_messages_orphans", "sweep_staging_orphans"]
