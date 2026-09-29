# Step 6: Mailgun committed attachments → storage

**Status:** COMPLETED (2026-09-29)
**Depends on:** Steps 1, 3

## Scope

- **`email/mailgun/service.commit_attachments`** is now async. It uploads each staged file to `{org}/messages/{message_id}/{name}` and deletes the staged copy.
  - A failed upload is logged and that file is left in staging, which is swept after 1 hour. The message's other attachments still land.
  - `storage_backend` in the attachments JSONB records the active backend. It is informational only; reads always use `get_storage()`.
- **Callers:** `mailgun/tasks.py` and `ingest_forwarded.py` now `await` the commit.
- **`conversations/service.open_message_attachment`** streams the attachment from storage (404 when missing). The router's `download_message_attachment` returns a `StreamingResponse` with `Content-Disposition: attachment`, `nosniff`, a sandbox CSP and `Content-Length`. The org and JSONB-listing checks are unchanged.
- **`email/mailgun/orphan_cleanup` messages sweep:**
  - For each org it lists `{org}/messages/` in storage and runs one batched `existing_message_ids` query. It deletes the folders whose Message row is gone.
  - The 24-hour age threshold is dropped: uploads only happen after the row commits, so a missing row always means the message was deleted.
  - The direct SQL moved into two new `mailgun/data_access.py` functions (`list_org_ids`, `existing_message_ids`). This removed one pin-test violation.
- **Staging sweep:** unchanged; it stays on local disk.

## Test

- `tests/shared/test_storage_reads.py`:
  - An attachment is committed, then streamed back; a missing one returns 404.
  - A DB-free sweep test deletes only the folder that has no row.
- `tests/test_mailgun_step5_attachments_and_dlq.py`: the commit tests are now async, and the sweep test is rewritten to check that the orphan is removed and a live message is kept. That test needs the test DB, which currently errors on the missing `email_opt_in_status` type, as before this track.
