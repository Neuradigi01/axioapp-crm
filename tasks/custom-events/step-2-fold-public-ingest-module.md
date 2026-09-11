# Step 2 — Fold `core/embed/` + `ai_assistants/public_context.py` into `core/public_ingest/`

**Goal:** create `core/public_ingest/` as the single home for public-authenticated routers. Move `core/embed/` and `core/ai_assistants/public_context.py` in. Extract shared helpers to `api/src/app/shared/{rate_limit,idempotency,hmac_verify}.py`.
**Phase:** Custom Events track — step 2/17
**Depends on:** Step 1
**Status:** Pending

## Scope

**In-scope:**
- New folder tree:
  ```
  api/src/app/core/public_ingest/
    __init__.py
    api_keys/
      __init__.py, models.py, schemas.py, router.py, service.py, data_access.py
    embed/       (moved from core/embed/)
    ai_assistants/  (moved from core/ai_assistants/public_context.py + related)
  api/src/app/shared/
    rate_limit.py       (extended - move logic from core/embed/rate_limit.py)
    idempotency.py      (NEW - stub, real Redis backing in Step 3)
    hmac_verify.py      (NEW - stub, real logic in Step 3)
  ```
- Move `core/embed/models.py` (`ApiKey` class per Step 1) into `core/public_ingest/api_keys/models.py`.
- Split embed's other files: submission handling stays in `core/public_ingest/embed/`; key CRUD moves into `core/public_ingest/api_keys/`.
- Move `core/ai_assistants/public_context.py` into `core/public_ingest/ai_assistants/`.
- Existing `core/embed/rate_limit.py` moves to `api/src/app/shared/rate_limit.py` (extended in Step 3).
- Existing `core/embed/log_service.py` becomes `core/public_ingest/log_service.py` (shared across all public surfaces); table rename `tbl_embed_submissions_log` → `tbl_public_ingest_log` via migration (separate small migration in this step).
- Keep import shims at old paths (`core/embed/__init__.py` re-exports; `core/ai_assistants/public_context.py` re-exports) for one release; retired in Step 15's cleanup.
- Update `main.py` router includes (routes unchanged for embed + AI; new `/api/v1/api-keys` router registered).

**Out of scope:**
- Custom-events module (Step 5+).
- Redis backing (Step 3).
- HMAC prefilter logic (Step 4).

## Files to touch
- Bulk move: ~15 files under `core/embed/` + `core/ai_assistants/public_context.py`.
- New: `core/public_ingest/__init__.py`, `core/public_ingest/api_keys/*.py`.
- New: `api/src/app/shared/idempotency.py`, `api/src/app/shared/hmac_verify.py` (stubs).
- Modified: `api/src/app/shared/rate_limit.py` (extended).
- Migration: `NNNN_rename_ingest_log.py` (rename `tbl_embed_submissions_log` → `tbl_public_ingest_log`, add `source_type` column).
- Modified: `main.py`.
- Shim files at old paths.
- Tests.

## Plan
1. Migration for the log-table rename + `source_type` column (`'embed' | 'events' | 'ai_assistant'`).
2. Move files via git (preserves history).
3. Update import statements throughout `api/src/`.
4. Add shim re-exports at old paths.
5. Run all embed + ai_assistant tests to confirm zero regression.

## DB changes / migrations
Table rename + one new column.

## Tests to add
- `test_embed_endpoint_still_works_after_fold` (existing tests moved).
- `test_ai_assistants_public_still_works_after_fold`.
- `test_public_ingest_log_has_source_type_column`.
- `test_import_shims_at_old_paths_still_work`.

## Verification checklist
- Backend: all embed + ai_assistant tests pass.
- Backend: migration up/down clean.
- Code review: no accidental behavior change; commits are pure moves.

## Self-check
- [ ] Rule 1: pure core.
- [ ] Rule 2: log table has `org_id` + RLS (verified).
- [ ] Rule 8: bulk move but no logic change — reviewer walks diff.
- [ ] Rule 10: shims scheduled for retirement in Step 15.

## Stop & report
Await "proceed".
