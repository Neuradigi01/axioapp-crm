"""Data-access layer for the automation engine.

Pure query helpers — no transactions, no audit, no commits. Leaf
module; never imports a ``service.py``. Per the locked layered
convention (single-file ``data_access.py``, manager spec 2026-06-25)
trigger lookups + run history queries live here side-by-side.

Step 1 lands the empty file so the convention is in place from the
first commit. The actual query bodies arrive with the consumer
steps:

  * Step 2 — ``list_triggers`` + ``get_trigger`` + ``match_triggers``
    (the matcher reads every enabled trigger for a given
    ``(org_id, event_type)`` pair).
  * Step 4 — ``insert_run`` + idempotency check by
    ``(trigger_id, event_id)`` + ``list_runs`` for the run-history
    endpoint.

Tenant scoping is applied automatically by the ``do_orm_execute``
listener on every SELECT, but consumers SHOULD also pass ``org_id``
explicitly in the WHERE clause as a belt to the suspenders —
defends callers (Celery tasks, scripts) that forget to set
``RequestContext.org_id``.
"""
from __future__ import annotations


__all__: list[str] = []
