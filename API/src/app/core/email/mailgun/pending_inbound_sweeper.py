"""Broker-down safety net for pending-inbound directories.

The Mailgun webhook writes each delivery to
``./storage/pending-inbound/<uuid>/`` **before** calling ``.delay()``
on the Celery ingest task. When Celery/Redis are down at delivery
time, we still return 200 to Mailgun (because the payload is safely
on disk), and this sweeper — running every 5 minutes on the
Celery-beat schedule — picks up any pending directory older than
5 minutes and re-enqueues the ingest task.

Cadence rationale: 5-min age threshold matches the beat cadence so a
directory is either enqueued at write-time OR picked up on the next
beat, never both (each task deletes its own directory on success).
On broker outage, deliveries queue on disk and drain when the broker
recovers.

Step 3 vs Step 4 boundary:
  * Step 3 (here) — sweep + re-enqueue. Nothing more.
  * Step 4's task body — decides success/failure and either deletes
    the directory (success) or writes a DLQ row (exhausted retries).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from src.celery.worker import celery

logger = logging.getLogger(__name__)

_STORAGE_ROOT_ENV = "STORAGE_ROOT"
_DEFAULT_STORAGE_ROOT = "./storage"
_PENDING_SUBDIR = "pending-inbound"
_MIN_AGE_SECONDS = 300  # 5 minutes


def _storage_root() -> Path:
    return Path(os.getenv(_STORAGE_ROOT_ENV, _DEFAULT_STORAGE_ROOT))


@celery.task(
    name="src.app.core.email.mailgun.pending_inbound_sweeper.sweep_pending_inbound",
    bind=True,
)
def sweep_pending_inbound(self) -> int:  # noqa: ARG001
    """Re-enqueue every pending-inbound directory older than 5 min.

    Returns the count of directories re-enqueued so the beat log has
    an at-a-glance drain rate.
    """
    pending_root = _storage_root() / _PENDING_SUBDIR
    if not pending_root.exists():
        return 0

    from src.app.core.email.mailgun.tasks import process_mailgun_inbound

    now = time.time()
    reenqueued = 0
    for child in pending_root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = now - child.stat().st_mtime
        except FileNotFoundError:
            # Directory was consumed between iterdir and stat — fine.
            continue
        if age < _MIN_AGE_SECONDS:
            continue
        try:
            process_mailgun_inbound.delay(str(child))
            reenqueued += 1
        except Exception:  # pragma: no cover — broker still down
            logger.warning(
                "mailgun.sweep_pending_inbound: broker still refusing enqueue for %s",
                child,
            )
            # Leave the directory in place; the next tick tries again.
            continue

    if reenqueued:
        logger.info(
            "mailgun.sweep_pending_inbound re-enqueued %d directory(ies)",
            reenqueued,
        )
    return reenqueued


__all__ = ["sweep_pending_inbound"]
