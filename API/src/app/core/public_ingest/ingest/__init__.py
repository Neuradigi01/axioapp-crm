"""Public ingest endpoint sub-package.

Filled in by:

  * Step 7a — ``router.py`` (``POST /api/v1/events/track`` route) +
    auth pipeline orchestration (HMAC prefilter → Argon2id verify →
    HMAC signature verify → idempotency check → rate limits).
  * Step 7b — ``payload_validator.py`` (types, size caps,
    URL/email/enum guards) + ``contact_resolution.py`` (routes
    auto-create through ``core.contacts.service`` to fire
    ``contact.created`` on the bus; per-identifier throttle for
    enumeration defense).
  * Step 7c — ``service.py`` orchestrator: persistence to
    ``tbl_custom_event_occurrences`` (live) or
    ``tbl_custom_event_test_runs`` (test via workflow dry-run),
    single-publish onto the bus, response shaping, idempotency cache
    write.
"""
