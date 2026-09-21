# Track 1 — Manual smoke checklist

Run against Ajay's Workspace (`41f9ede9-41b3-44ce-b489-3004566d4068`,
Owner `ajaygogane224@gmail.com`) with the API + worker both up.
Per memory `feedback_smoke_test_target_org.md`.

## Prerequisites

- `run.cmd up` — API + worker + beat containers running.
- Migration `0232_channel_endpoints` applied (`run.cmd upgrade`).
- Logged in as Owner in the browser tab.

## Checks

### 1. Admin overview lists backfilled endpoints

**Endpoint:** `GET /api/v1/channel-endpoints`

**Expected:**
- HTTP 200
- `items` array contains one entry per shipped SMTP sender (`endpoint_type='smtp_reply_capture'`) + one per OAuth account (`endpoint_type='oauth_mailbox'`) for the caller's org.
- Every entry has `is_active: true`.
- Every entry has a `details` block populated with the correct FK
  (`smtp_sender_id` for reply-capture, `oauth_account_id` for oauth-mailbox).
- **Tokens NOT present** on any response object — `reply_token` and
  `forwarding_token` are excluded from the schema.

**How to run:**
```sh
curl -H "Authorization: Bearer <owner-jwt>" \
     https://<host>/api/v1/channel-endpoints
```

### 2. Deactivate as Owner returns 204

**Endpoint:** `POST /api/v1/channel-endpoints/{id}/deactivate`

**Expected:**
- HTTP 204
- Subsequent `GET /api/v1/channel-endpoints` no longer includes the deactivated row.
- DB row shows `is_active = false`, `deactivated_at` populated, `deactivation_reason = 'manual'` (or the supplied reason).
- Audit event `channel_endpoint.deactivated` written to `tbl_audit_log`
  with `user_id` = caller.
- Repeat call (same id) is idempotent — returns 204 without new audit row.

### 3. Non-Owner returns 403

**Setup:** Sign in as an Employee-role user in the same org.

**Endpoint:** `POST /api/v1/channel-endpoints/{id}/deactivate`

**Expected:**
- HTTP 403 (permission `email.accounts.manage` not granted to Employee role by default).

### 4. Cross-org isolation returns 404

**Setup:** Sign in as Owner of a DIFFERENT org (or use the Demo seed org).

**Endpoint:** `POST /api/v1/channel-endpoints/{id-from-ajay-workspace}/deactivate`

**Expected:**
- HTTP 404 (endpoint's `org_id` doesn't match caller's JWT `org_id`; no info leak about whether the id exists elsewhere).

## Nightly sweeper (Step 5)

Beat entry `channel-endpoints-sweep-orphans-nightly` runs at 03:15 UTC.
Verify manually:

```sh
docker exec crm-worker-1 celery -A src.celery.worker inspect scheduled
```
Look for `src.app.core.channel_endpoints.tasks.sweep_orphan_endpoints`.

**Manual fire:**
```sh
docker exec crm-worker-1 celery -A src.celery.worker call \
    src.app.core.channel_endpoints.tasks.sweep_orphan_endpoints
```

Task returns a summary dict:
```json
{
  "orphan_swept": 0,
  "oauth_swept": 0,
  "failed": 0,
  "swept_ids": [],
  "at": "2026-09-21T..."
}
```

## Cleanup

None required — no test artifacts written to production data.
Deactivated endpoints from step 2 stay `is_active=false` (soft-delete only);
re-activate manually via SQL if the test target's endpoint should still work:
```sql
UPDATE tbl_channel_endpoints
   SET is_active = true, deactivated_at = NULL, deactivation_reason = NULL
 WHERE id = '<endpoint-id>';
```
