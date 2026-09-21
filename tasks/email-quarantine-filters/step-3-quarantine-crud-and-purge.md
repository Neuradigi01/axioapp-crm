# Step 3: Quarantine DAL + service (release, discard, bulk) + auto-purge beat

**Status:** COMPLETED (2026-09-21) — quarantine DAL (list, find-by-id, find-by-delivery-id, list-held-older-than, mark_released/discarded/auto_purged) + service (release, discard, bulk-release with `rate_capped`-only safety, auto-purge, enqueue_quarantine helper used by gate chain) + router (4 endpoints: `GET /email-quarantine`, `POST /{id}/release`, `POST /{id}/discard`, `POST /bulk-release`); weekly auto-purge Celery beat at Mon 04:00 UTC (`email-quarantine-auto-purge-weekly`) with `EMAIL_QUARANTINE_AUTO_PURGE_DAYS=30`; on-disk MIME dir cleanup on discard/purge; virus_verdict rows enqueue with `blocked_release=True` and cannot be released.

## Goal

Quarantine row lifecycle. Release goes through shared `_persist_inbound_email`. Discard cleans disk. Bulk-release capped to `rate_capped` reason. Weekly auto-purge.

## Files touched

- `api/src/app/core/email/quarantine/data_access.py` — quarantine DAL
- `api/src/app/core/email/quarantine/service.py` — release/discard/bulk/auto-purge
- `api/src/app/core/email/quarantine/router.py` — quarantine endpoints
- `api/src/app/core/email/quarantine/tasks.py` — auto-purge beat
- `api/src/app/celery/worker.py` — autodiscover
- `api/src/app/shared/celery_config.py` — weekly beat entry
- `api/tests/test_quarantine_service.py`

## What this step does

- DAL:
  - `insert_quarantine(session, *, org_id, endpoint_id, reason_code, reason_detail, payload_path, from_address, to_recipient, subject, body_snippet, attachment_summary, mailgun_delivery_id, blocked_release=False)`
  - `list_quarantine(session, *, org_id, status='held', reason_code=None, limit, offset)`
  - `find_quarantine_by_id(session, *, id, org_id)`
  - `mark_released(session, *, id, resolved_by_user_id)`
  - `mark_discarded(session, *, id, resolved_by_user_id)`
  - `mark_auto_purged(session, *, id)`
  - `list_held_older_than(session, *, cutoff_days)`
- Service:
  - `release_quarantine(db, *, org_id, id, actor_user_id) -> Message`:
    - Load row (org-scoped).
    - `status='held'` required (else 409).
    - `blocked_release=True` → 403.
    - Read on-disk MIME from `payload_path`. Parse via stdlib.
    - Call shared `_persist_inbound_email(...)` with same params original ingest would have used. Thread by RFC In-Reply-To if present.
    - `mark_released(...)`. Delete payload dir.
    - Audit `quarantine.released` with `resolved_by_user_id`.
  - `discard_quarantine(db, *, org_id, id, actor_user_id)`:
    - Load row. Delete payload dir. `mark_discarded(...)`. Audit.
  - `bulk_release(db, *, org_id, ids, actor_user_id)`:
    - Loop ids. For each: reject if `reason_code != 'rate_capped'` (safety per README). Individual release.
    - Return per-id result.
  - `auto_purge_held_older_than_30d()`:
    - `EMAIL_QUARANTINE_AUTO_PURGE_DAYS (default 30)`.
    - Loop `list_held_older_than(cutoff=30)`. For each: delete payload dir, `mark_auto_purged(...)`.
    - Aggregate summary; if any purged, notify org owners weekly digest.
- Router (Owner/Admin only):
  - `GET /api/v1/email-quarantine` — paginated list with filters
  - `POST /api/v1/email-quarantine/{id}/release` — release
  - `POST /api/v1/email-quarantine/{id}/discard` — discard
  - `POST /api/v1/email-quarantine/bulk-release` — body `{ids: [...]}`
- Beat: `auto-purge-quarantine-weekly` at Monday 04:00 UTC.

## Tests

- `test_release_quarantine_persists_via_shared_helper`
- `test_release_quarantine_threads_by_in_reply_to`
- `test_release_quarantine_blocked_release_returns_403`
- `test_release_quarantine_status_not_held_returns_409`
- `test_release_quarantine_deletes_payload_dir`
- `test_release_quarantine_writes_audit_with_resolved_by`
- `test_discard_quarantine_deletes_payload_dir`
- `test_bulk_release_only_allows_rate_capped_reason`
- `test_bulk_release_returns_per_id_result`
- `test_auto_purge_only_affects_held_older_than_30d`
- `test_auto_purge_deletes_disk_payload`
- `test_auto_purge_weekly_owner_notification_if_any`
- `test_bulk_release_owner_or_admin_only`
- `test_quarantine_cross_org_returns_404`

## Verification checklist

- [ ] All 14 tests pass
- [ ] Beat entry registered
- [ ] Task in autodiscover
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 4: pass.
- Rule 2: pass.
- Rule 10: pass.
- Reuse: pass — release goes through shared `_persist_inbound_email`.
- Memory `feedback_celery_task_autodiscover_list.md`: pass.

## Stop-and-report

Report test pass, beat entry visible. **Awaiting your "proceed" for Step 4.**
