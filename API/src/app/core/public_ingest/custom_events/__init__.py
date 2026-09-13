"""Custom-events sub-package under ``core.public_ingest``.

Filled in by:

  * Step 5 — ``models.py`` (``tbl_custom_events``,
    ``tbl_custom_event_occurrences`` [+ month-partitioned archive],
    ``tbl_custom_event_test_runs``).
  * Step 6 — ``schemas.py``, ``router.py``, ``service.py``,
    ``data_access.py``, ``utils.py`` (definitions CRUD, Owner-only
    edits, ``add_prefix``/``strip_prefix`` helpers).
  * Step 8 — bridge into workflow trigger picker + variables
    registry.
  * Step 9 — workflow lifecycle cascade (soft-delete auto-disables
    dependent workflows, re-activation prompt, schema-key removal
    review flag).
  * Step 10 — Celery Beat tasks (occurrence archive, partition
    rotation, test-runs 7d cleanup).
"""
