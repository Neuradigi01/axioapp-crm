# Step 3: Mailgun events webhook + attribution via `v:` custom variables + dedup

**Status:** COMPLETED

## Goal

`POST /api/v1/webhooks/mailgun/events` — receives delivery-lifecycle events, verifies HMAC signature, dedups via Redis, attributes to the right reputation row using `v:` variables, updates counters.

## Files touched

- `api/src/app/core/email/mailgun/events_webhook.py` — new endpoint + handler
- `api/src/app/core/email/reputation/data_access.py` — row-lookup + upsert helpers
- `api/src/app/core/email/reputation/service.py` — event-handler service
- `api/src/app/main.py` — register events-webhook router
- `api/tests/test_mailgun_events_webhook.py`

## What this step does

- Endpoint `POST /api/v1/webhooks/mailgun/events`:
  - HMAC verify per shipped mailgun-inbound pattern (signing key from env — `MAILGUN_EVENTS_SIGNING_KEY`, fallback `MAILGUN_SIGNING_KEY` if same key).
  - Timestamp window ±5min.
  - Redis dedup cache: `mgw:events:seen:{event_id}` (10-min TTL, `nx=True` set).
  - Fail policies: sig+replay = closed; rate-limit on sig-fail 20/min per IP.
  - Persist-then-process: write raw payload to `./storage/pending-events/{uuid}/`, enqueue Celery, return 200.
- Celery task `process_mailgun_event(pending_path)`:
  - Read payload. Extract event-type, `v:org`, `v:envelope`, `v:endpoint`, `v:domain_id`.
  - Missing `v:org` → audit `mailgun.event.missing_v_org` + drop (don't miscount).
  - Load reputation row by `(org_id, envelope, domain_id)`. Create if absent (upsert).
  - Event kind mapping:
    - `delivered` → `incr_counter(..., "delivered")`
    - `failed` with severity `permanent` → `incr_counter(..., "bounce_permanent")`
    - `failed` with severity `temporary` → NO increment (temporary is transient — Mailgun retries)
    - `complained` → `incr_counter(..., "complaint")`
    - `unsubscribed` → `incr_counter(..., "unsubscribe")`
    - `rejected` (pre-send) → separate `rejected` counter for operational visibility
  - Delete pending-events dir on success. DLQ on retry exhaustion.

## Tests

- `test_events_webhook_hmac_verify_fail_401`
- `test_events_webhook_replay_token_rejected`
- `test_events_webhook_timestamp_stale_rejected`
- `test_events_webhook_redis_down_fails_closed_on_sig`
- `test_events_webhook_response_time_constant`
- `test_events_webhook_persists_payload_to_disk_before_enqueue`
- `test_process_event_delivered_bumps_delivered_counter`
- `test_process_event_bounced_permanent_bumps_bounce_counter`
- `test_process_event_bounced_temporary_does_not_bump`
- `test_process_event_complained_bumps_complaint_counter`
- `test_process_event_missing_v_org_audits_and_drops`
- `test_process_event_creates_reputation_row_on_first_event`
- `test_process_event_replay_second_delivery_no_double_count`

## Verification checklist

- [ ] All 13 tests pass
- [ ] Pin-tests pass
- [ ] Existing webhooks (`/webhooks/mailgun/inbound`) not affected
- [ ] Ruff clean

## Self-check

- Rule 2: pass — attribution scoped by `v:org` (server-set only).
- Rule 10: pass.
- DB efficiency: pass — one upsert + one INCR per event.
- Memory `feedback_celery_task_autodiscover_list.md`: pass.

## Stop-and-report

Report file count, test pass, sample event flow. **Awaiting your "proceed" for Step 4.**
