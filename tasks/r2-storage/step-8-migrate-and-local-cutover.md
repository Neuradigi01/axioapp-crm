# Step 8: `run storage-migrate` + local cutover

**Status:** COMPLETED (2026-09-29). Local runs on R2 (`crm-local`).
**Depends on:** Steps 0, 2–7

## Scope

- **`shared/storage/migrate.py`**, run as `python -m src.app.shared.storage.migrate`, supports `--dry-run`, `--only-missing` and `--reverse`.
  - Forward (disk → R2) copies a file when it is absent or its MD5 differs. With `--only-missing` it never overwrites.
  - Reverse (R2 → disk) writes through `LocalStorage`, so the key guard and root check block hostile keys.
  - It skips `pending-inbound/`, `pending-events/`, `{org}/staging/`, dot-files and symlinks.
  - A lock file at `STORAGE_ROOT/.storage-migrate.lock` refuses concurrent runs.
  - The exit code is 1 if any file failed.
- **`R2Storage`** gains two helpers used only by the migration: `raw_etag` and `list_all_keys`.
- **`run.cmd` / `run.sh`** get `storage-migrate [--dry-run] [--only-missing] [--reverse]`, which runs `docker compose run --rm` on the api service with the environment's secrets.
- **`config.local.env`** sets `STORAGE_BACKEND=r2`, with a note that only one developer machine may point at `crm-local`.
- **Unrelated fix found during the rebuild:** `requirements.txt` does not pin SQLAlchemy, so the rebuild installed 2.1.1. In 2.1, a bare `postgresql://` resolves to psycopg v3, which is not installed, and Celery crash-looped. `src/celery/celery_config.py` now names `postgresql+psycopg2` in `result_backend`. **Every environment's next rebuild would have hit this.**

## Local cutover log (2026-09-29)

1. Ran `run up` (rebuild, with boto3 now in the image).
2. `storage-migrate --dry-run`: would copy 87 files (4,784,391 bytes), 0 failed.
3. `storage-migrate`: copied 87, 0 failed. A re-run skipped all 87 because the MD5s matched.
4. Set `STORAGE_BACKEND=r2` in `config.local.env`, then ran `run up`. api, celery and beat all have `STORAGE_BACKEND=r2`.
5. `storage-migrate --only-missing`: copied 0, skipped 87.
6. Smoke test against Ajay's Workspace `41f9ede9-…`:
   - The backend is `R2Storage crm-local`, and `head_bucket` succeeds.
   - A new catalog PNG put to R2 returns 200 from `/files`.
   - A migrated catalog JPG returns 200 with `image/jpeg`, an ETag, `no-cache` and the sandbox CSP. Sending the ETag back returns 304.
   - A call-recording key returns 404 at `/files` but can be streamed through storage.
   - The smoke objects were deleted afterwards.

## Test

`tests/shared/test_storage_migrate.py` (moto), 5 tests:
- The temp, hidden and unsafe key filter works.
- Forward copying sets the content type, skips symlinks and temp folders, is idempotent, and dry-run writes nothing.
- A changed file is recopied, but `--only-missing` never overwrites a newer R2 object.
- `--reverse` restores to disk and drops `../` keys.
- The lock refuses a second run.

Totals: 78 storage tests pass. The layered pin-test has 115 violations, down from 116, and none were added.
