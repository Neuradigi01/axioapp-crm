# Step 7: Quarantine payloads → storage

**Status:** COMPLETED (2026-09-29)
**Depends on:** Step 6

## Finding

Before this step, the ingest task deleted the pending folder right after writing a quarantine row (`_cleanup(pending_dir)` after `_apply_extended_gates`). So `tbl_email_quarantine.payload_path` always pointed at a deleted folder, and held mail was never actually kept. Release is a status flip only; nothing reads the payload yet.

## Scope

- **`quarantine/service.enqueue_quarantine`** now takes `pending_dir: Path` instead of `payload_path`.
  - It pre-assigns the row id and copies every file of the delivery (`payload.json` and attachments) to `{org}/quarantine/{row_id}/` in storage.
  - It stores that prefix in `payload_path`. Copying is best-effort per file, and a failed upload is logged.
- **`mailgun/tasks.py`:** the 4 gate call sites pass `pending_dir=`.
- **`_delete_payload`** replaces `_cleanup_payload_dir`. It deletes the storage prefix after the discard or auto-purge commit.
  - Legacy rows hold a local `pending-inbound` path that `validate_prefix` rejects, so they are a no-op. Their folder is already gone.
  - `shutil` is no longer used.

## Test

`tests/shared/test_storage_reads.py`:
- The payload and attachment are still readable from storage after the local pending folder is deleted.
- `payload_path` equals `{org}/quarantine/{id}`.
- Delete removes everything.
- A legacy local path is a no-op.
