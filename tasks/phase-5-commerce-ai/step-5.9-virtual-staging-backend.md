# Step 5.9 — AI Virtual Staging — backend

**Goal:** `fp_virtual_staging_jobs` table. Integrate a generative-AI image API. Job queue, status updates, output URL.
**Phase:** 5
**Depends on:** 4.7 (storage), 3.4
**Status:** Pending

## Scope
**In-scope:**
- Model `VirtualStagingJob` (`fp_virtual_staging_jobs`, TenantScoped): id, org_id, user_id, base_image_url, furniture_image_urls (text[]), prompt, status (queued/running/done/failed), provider (replicate/stability), provider_job_id, output_url, error, started_at, finished_at, created_at.
- Migration `0031_fp_virtual_staging.py` + RLS.
- Provider adapter interface + Replicate impl (default).
- Celery task `process_staging_job(job_id)` — calls provider, polls until done, persists output via StorageBackend.
- Endpoints: `POST /virtual-staging` (multipart: base + furniture[] + prompt) → returns job; `GET /virtual-staging/{id}`; `GET /virtual-staging` list.
- Settings: `STAGING_PROVIDER=replicate`, `REPLICATE_API_TOKEN`.
- Permission: `staging.use`.

## Files to touch
- `api/src/app/packs/furniture/modules/virtual_staging/{__init__,models,schemas,service,router,adapters,tasks,module}.py` (created)
- `api/alembic/versions/0031_fp_virtual_staging.py` (created)
- `api/src/app/shared/config.py` (modified)

## Plan
1. Models + migration.
2. Replicate adapter: POST prediction, poll, fetch output URL, download image, store via StorageBackend.
3. Celery task lifecycle: queued → running → done|failed.
4. Endpoint streams progress via WS (reuse notifications WS for "staging_update" events).

## Tests to add
- `tests/test_virtual_staging.py` — mocks Replicate; happy path.

## Verification checklist
**Backend:**
- `POST /virtual-staging` → 202 with job id.
- after Celery + provider → `GET /virtual-staging/{id}` shows `output_url`.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Storage abstraction reused.

## Stop & report
Await "proceed" before Step 5.10.
