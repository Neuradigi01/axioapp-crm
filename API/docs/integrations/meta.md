# Meta integration — operator reference

This file documents the Meta-specific HTTP surfaces that exist outside
the per-tenant Settings UX. They include:

* The OAuth callback used by Meta Ads lead-form ingestion.
* The Embedded Signup exchange + config endpoints used by the
  WhatsApp Business Cloud API setup flow.
* The Data Deletion Callback Meta requires every app to expose.

## Data Deletion Callback

* **URL:** `POST /api/v1/integrations/meta/data-deletion`
* **Status URL pattern:** `https://<FRONTEND_URL>/data-deletion-status?confirmation_code=<token>`
* **Spec:** https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback

### Contract

Meta posts a form-encoded body containing a single `signed_request`
field. The value is `<sig_b64>.<payload_b64>` where:

* `payload_b64` is url-safe-base64 of a JSON object with at least
  `{ "user_id": "<meta-user-id>", "algorithm": "HMAC-SHA256",
  "issued_at": <unix-epoch-seconds> }`.
* `sig_b64` is url-safe-base64 of HMAC-SHA256 over the
  `payload_b64` string (not the decoded JSON), keyed on
  `META_APP_SECRET`.

The endpoint:

1. Rejects with HTTP 400 and the generic message `invalid
   signed_request` when the signature mismatches, the algorithm is
   wrong, the payload is older than ten minutes (replay protection),
   or any field is malformed. The specific reason is logged
   server-side; the response stays generic so an attacker can't probe
   the validator.
2. Looks up every `tbl_integrations` row with a matching
   `meta_user_id`. ES-connected rows have this column populated;
   legacy manually-connected rows do not and so never match.
3. Inserts a `tbl_meta_data_deletion_requests` row with status
   `pending`, dispatches the Celery task `delete_meta_user_data`,
   and returns synchronously with the confirmation URL.
4. On duplicate `(meta_user_id, issued_at)` payloads — Meta retries
   on transient failures — returns the existing confirmation_code so
   any URL Meta has already shown the user stays valid.

### Anonymisation rule

The Celery task scrubs WhatsApp content for every affected org:

* `tbl_messages.text` → NULL
* `tbl_messages.payload` → `{}::jsonb`
* `tbl_messages.attachments` → `[]::jsonb`
* `tbl_conversations.external_id` → `<deleted-<uuid>>` sentinel so the
  natural-key index can't re-attach a future webhook to a deleted
  thread.
* `tbl_integrations.meta_user_id` → NULL so a future ES reconnect
  mints a fresh identity instead of inheriting the deletion result.

Contact records are NOT touched here. WhatsApp message content is the
PII Meta cares about; broader compliance work (DPDP / GDPR contact
deletion) lives in the Phase-8 track.

### Retention

`tbl_meta_data_deletion_requests` rows are kept forever. Meta
periodically re-fetches the status URL (sometimes months after the
original deletion) and a 404 there triggers an App Review warning.

### Demo path

For the App Review screencast, the status endpoint short-circuits the
confirmation code `demo-test-12345` and returns a synthetic
`completed` projection. No DB row is required.

### Audit log

* `compliance.meta_data_deletion.received` — once per callback, scoped
  to the first affected org (or no row when zero orgs match).
* `compliance.meta_data_deletion.executed` — once per affected org as
  the scrub progresses.
* `compliance.meta_data_deletion.completed` /
  `compliance.meta_data_deletion.failed` — terminal event.

The Meta user_id is never logged in plaintext; audit rows carry a
truncated SHA-256 instead.

### Configuration

Set in the Meta App Dashboard → App Settings → Advanced → Data Deletion:

* **Callback URL:** `https://<API_BASE_URL>/api/v1/integrations/meta/data-deletion`
* **Instructions URL:** `https://<FRONTEND_URL>/privacy#data-deletion`

Required env vars:

* `META_APP_SECRET` — the HMAC key for signed_request verification.
* `FRONTEND_URL` — used to mint the status URL returned to Meta.
