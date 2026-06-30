"""Celery task wrapper for the email-sequences scheduler.

The actual business logic USED TO live in :func:`scheduler.tick`. As
of Step 20 of the workflows track, sequence runtime is absorbed into
:mod:`core.workflows.engine` + its Celery beat sweep — this task is
now a no-op that returns ``{"processed": 0, "deprecated": True}``.

The task entry is intentionally left registered so that:

  * Existing Celery beat schedules / dashboards don't error out on
    missing task names during the transition release.
  * Operators inspecting Flower see the historical task firing as a
    no-op, instead of disappearing without an audit trail.

A follow-up release after one cycle removes both this file + the
``email-sequences-tick`` beat entry from :mod:`src.celery.celery_config`.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task


@shared_task(name="src.app.core.email_sequences.tasks.tick_email_sequences")
def tick_email_sequences() -> dict[str, Any]:
    """No-op. Step 20 absorbed sequence-tick into the workflow engine.

    Returns the shape the historical task returned so log parsers /
    monitoring queries keep working. ``deprecated=True`` flags it for
    the next sweep that removes the registration entirely.
    """
    return {"processed": 0, "deprecated": True}


__all__ = ["tick_email_sequences"]
