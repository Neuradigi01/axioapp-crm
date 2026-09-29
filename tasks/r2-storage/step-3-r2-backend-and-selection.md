# Step 3: `R2Storage` + backend selection

**Status:** COMPLETED (2026-09-29)
**Depends on:** Step 1
**Blocks:** Steps 5–9

## Goal

Setting `STORAGE_BACKEND=r2` makes every storage call use the environment's private R2 bucket. `local` stays the default everywhere, so this step changes no running environment.

## Scope

- **`shared/storage/config.py` (new)** reads the storage settings:
  - `storage_root()` reads `STORAGE_ROOT` on every call.
  - `storage_backend_name()` accepts `local` or `r2`.
  - `r2_settings()` names each missing `R2_*` variable and never shows a value. `R2Settings` hides the secret in its repr.
- **`shared/storage/r2.py` (new)**, the `R2Storage` backend:
  - Uses boto3 with SigV4, `region_name="auto"`, connect timeout 5 s, read timeout 30 s, 3 standard retries, and checksums `when_required`.
  - Every boto3 call runs on its own 16-thread pool, never the default executor.
  - Supports `put` (content type stored), `get`, `open_stream`, and `stat` (opaque ETag).
  - `delete` checks the object exists first, so it can return a bool.
  - `delete_directory` lists up to the cap plus one, refuses anything over the cap, and deletes in batches of 1,000.
  - `list_keys` skips unsafe keys with a warning.
  - `check_reachable` calls `head_bucket`.
- **`StorageBackend.check_reachable()`** is a no-op on local disk.
- **`get_storage()`** picks the backend from `STORAGE_BACKEND`. `probe_storage()` logs whether storage is reachable and never raises.
- **Startup:**
  - `startup_checks.check_storage_config()` stops the boot on an invalid backend or a missing `R2_*` variable.
  - `main.lifespan` runs the reachability probe as a background task, so an R2 blip does not stop the API.
- **Mailgun and conversations:** the four copies of `_storage_root()` in `events_webhook.py`, `orphan_cleanup.py`, `pending_inbound_sweeper.py` and `service.py`, plus `conversations/router.py`, now use the shared `storage_root()`.
- **Config and dependencies:**
  - `boto3>=1.36,<2.0` added to `requirements.txt`.
  - `moto[s3]>=5.0,<6.0` added to `requirements.dev.txt`.
  - `R2_*` added to the `docker-compose.yml` secret passthrough.
  - `celery-beat` gets the `./storage` volume.
  - `config.env` documents the settings.
- **Tests:** `tests/conftest.py` forces `STORAGE_BACKEND=local` in `pytest_configure`.

## Test

`tests/shared/test_storage_r2.py`, run against a moto S3 stub:
- A full round trip works, including streaming 200 KB. The content type is inferred, or kept when given explicitly.
- A missing object raises `FileNotFoundError` from `get`, `stat` and `open_stream`.
- Unsafe keys and an empty prefix are rejected.
- `delete_directory` deletes 1,500 keys in batches and leaves `…_old/` alone. Over the cap, it refuses and deletes nothing.
- `list_keys` skips a planted `../` key.
- `check_reachable` works.
- A missing `R2_BUCKET` is named in the error, and the secret never appears.
- `get_storage` selects local, R2, or rejects `s3`.
- `probe_storage` does not raise when storage is down.

Also run: the Step 1 and Step 2 storage tests (41 passed in total), plus the Mailgun webhook and attachment tests. Those have 27 errors from the test DB missing the `email_opt_in_status` type and 2 failures. Both are pre-existing: the same 2 fail on `c58f6327` in a clean worktree.

## Deploy note

boto3 must be in the image. After pulling, rebuild the containers (`run up`). Every environment still runs `STORAGE_BACKEND=local` until Step 8 or 9 flips it.
