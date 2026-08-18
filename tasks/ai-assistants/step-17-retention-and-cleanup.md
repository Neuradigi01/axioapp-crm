# Step 17 — Retention + reapers + janitor heartbeat

**Goal:** Close the loop — the janitor set that keeps the system tidy. Retention of AI conversations (configurable, default 90d, hard cap 400d). Reaper for stuck ingest tasks (no heartbeat > 15 min). Orphan chunk cleanup. Embed-key grace expiry. Cost outbox reconciliation. Janitor heartbeat table with monitoring alert. GDPR SAR deletion log. Also verify org-delete cascade end-to-end.
**Status:** Pending
**Depends on:** All prior steps (this is the closing janitor).

---

## Scope

In-scope:

- Celery beat schedule additions in `core/ai_assistants/tasks.py`:
  - `retention_cleanup` — every 6h. Deletes messages older than `assistant.retention_days` (default 90, capped 400); logs count + hashes to `tbl_gdpr_deletion_log`.
  - `reap_stuck_ingest` — every 5min. `UPDATE tbl_ai_assistant_knowledge SET status='failed_stuck', status_message='Worker did not complete ingest' WHERE status='processing' AND heartbeat_at < now() - '15 min'`. Cleans partial chunks.
  - `cleanup_orphan_chunks` — every 1h. Deletes chunks whose parent knowledge row is gone (belt+braces since FK CASCADE should prevent, but guards against manual DB edits).
  - `expire_embed_key_grace` — every 1h. Hard-deletes rows where `revoked_at + grace_days_interval < now()`. Skips rows whose parent assistant is already gone (assistant delete cascades).
  - `reconcile_cost_outbox` — every 5min. For `tbl_ai_assistant_message_meta` rows with `cost_status='pending_llm_confirm'` older than 5 min: query OpenAI's usage API (if available) or mark `failed` with `provider_error='cost_reconcile_timeout'`.
  - `janitor_heartbeat` — every 1min. Upserts `tbl_janitor_heartbeats(name, last_run_at, last_run_status)`.
- New table `tbl_janitor_heartbeats(name text PK, last_run_at timestamp, last_run_status text, last_error text nullable)` — no org_id (global janitor). Small migration.
- New table `tbl_gdpr_deletion_log(id, org_id, entity_type, entity_id, deleted_at, deletion_reason)` — audit for SAR compliance.
- **Org-delete cascade wiring** — extend existing org-delete hook (grep `def delete_organization` or similar):
  - Before FK cascade: cancel Celery tasks tagged with `org_id={org_id}` via `celery.control.revoke(...)` iterating over `AsyncResult` in `tbl_celery_taskmeta` (or a lighter tag-based mechanism if available).
  - Close SSE streams for the org via `SseStreamRegistry.cancel_by_org(org_id)`.
  - After DB cascade: delete `./storage/{org_id}/ai_assistants/` directory recursively.
  - Log to `tbl_gdpr_deletion_log`.
- **Monitoring alert** — a simple health endpoint `GET /health/janitor` returns the heartbeat table; monitoring (Prometheus / external) checks if any row's `last_run_at < now() - 48h` and alerts.
- Config: retention days per assistant (already added in Step 5? if not, add nullable `retention_days int default 90` on `tbl_ai_assistants` via small ALTER).
- Frontend surface: Settings → AI Providers section (Step 3) grows a small "Retention" card with per-org default (applies to assistants that don't override).

Out of scope:
- OpenAI Usage API integration for cost reconciliation — v1 uses timeout-to-`failed` fallback; real usage-API integration is a follow-up.
- Sophisticated monitoring — v1 exposes the heartbeat, monitoring integration is per-deployment.

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_janitor_and_gdpr_log.py` | **NEW** — 2 tables + optional ALTER for retention_days |
| `API/src/app/core/ai_assistants/tasks.py` | **EDIT** — 6 new Celery beat tasks |
| `API/src/app/core/ai_assistants/service.py` | **EDIT** — org-delete hook wiring |
| `API/src/app/core/ai_assistants/sse_registry.py` | **EDIT** — `cancel_by_org` method |
| `API/src/app/core/tenants/service.py` (or wherever `delete_organization` lives) | **EDIT** — hook |
| `API/src/app/shared/storage/local.py` | **EDIT** — verify `delete_directory` handles nested paths |
| `API/src/app/core/health/router.py` (or new health file) | **EDIT** — `/health/janitor` |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/retention-card.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/tabs/ai-providers/retention-card.component.html` | **NEW** |
| `API/celery_beat_schedule.py` (or equivalent) | **EDIT** — register beat schedules |
| `API/tests/ai_assistants/test_retention.py` | **NEW** |
| `API/tests/ai_assistants/test_reap_stuck_ingest.py` | **NEW** |
| `API/tests/ai_assistants/test_grace_expiry.py` | **NEW** |
| `API/tests/ai_assistants/test_cost_reconcile.py` | **NEW** |
| `API/tests/ai_assistants/test_org_delete_cascade.py` | **NEW** |

**~15 files. ~550 lines.**

## Plan

1. Migration first — 2 new tables + optional ALTER.
2. Celery beat: 6 tasks with clear responsibilities. Each idempotent + safe to run twice.
3. Org-delete hook: order matters — cancel Celery + close SSE **before** DB delete; delete storage dir **after** DB commits.
4. GDPR log: writes hash + count per deletion batch (not per row — hash the sorted list of ids for verifiability without storing PII).
5. Health endpoint public but rate-limited (grep for `/health` pattern).
6. Retention frontend card small — one form: "Default retention days (assistants override individually)".
7. Storage `delete_directory` must handle nested paths safely on Windows + Linux; add explicit test.

## DB changes / migrations

Two new tables + one small nullable ALTER (retention_days if not already there).

## Tests

- Retention: seed a message from 100 days ago + one from 30 days ago. Run task with default 90. Old one deleted. `tbl_gdpr_deletion_log` has one entry.
- Retention cap: assistant.retention_days=1000 → capped to 400 at write time (schema validator).
- Reap stuck: knowledge row with `status='processing'` + `heartbeat_at = now() - 20min` → task marks `failed_stuck`, cleans chunks.
- Orphan chunks: manual DB insert of chunk with fake knowledge_id → task deletes.
- Grace expiry: embed_key with `revoked_at = now() - 8d` + grace_days=7 → hard-deleted.
- Grace expiry idempotent under assistant cascade: assistant deleted (which cascades keys) then task runs → no error.
- Cost reconcile: meta row `pending_llm_confirm` older than 5 min → marked `failed` with reason.
- Org-delete: seed org with 2 assistants + 5 knowledge + 20 chunks + 3 conversations. Delete org. Verify all rows gone, storage dir gone, GDPR log written.
- Janitor heartbeat: after task runs, row present in `tbl_janitor_heartbeats`.
- `/health/janitor` returns the heartbeat table.

## Smoke

```
1. Trigger retention_cleanup manually via celery: celery -A app.tasks call retention_cleanup
   → check tbl_gdpr_deletion_log for a row.
2. Stop a Celery worker mid-ingest. Wait 16 min. reap_stuck_ingest runs.
   → knowledge row status='failed_stuck'.
3. Delete an org from admin UI. Verify tbl_ai_assistants / knowledge / chunks empty for that org,
   and ./storage/{org_id}/ai_assistants/ gone.
4. curl /health/janitor → JSON with all task last_run_at within a minute.
```

## Risks

- Celery task tagging by `org_id` for cancellation requires task metadata; if not supported, fall back to a per-task "check if org exists" guard at the top of each task.
- `storage.delete_directory` on Windows may fail if a file is locked by another process; retry with backoff.
- GDPR deletion log writes hashes not content — verified in tests.

## Self-check (10 rules)

`core/ai_assistants/tasks.py` + org-delete hook + small tables. ✓ Rule 2: janitor is global; GDPR log has org_id. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ Retention card guarded by `ai_providers.manage`. ✓ pack.yaml untouched. ✓ 15 files / ~550 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 17 — Retention + reapers + janitor heartbeat
Files: 15
Verify: all 6 beat tasks run + are idempotent; org-delete cascades cleanly incl. storage;
        GDPR log written; heartbeat endpoint healthy.
Tests: ~11 pytest cases.
Awaiting "proceed".

TRACK COMPLETE — AI Assistants v1 shipped end-to-end.
```
