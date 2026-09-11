# Step 7c — `POST /events/track` bus publish + occurrence persistence + response shaping

**Goal:** close the endpoint: publish accepted events onto the bus (single event name — no double-publish), persist occurrences (live → main table with denormalised schema snapshot; test → `tbl_custom_event_test_runs` via dry-run engine), shape response, cache for idempotency.
**Phase:** Custom Events track — step 7c/17
**Depends on:** Steps 0, 7a, 7b
**Status:** Pending

## Scope

**In-scope:**
- Persistence:
  - `mode='live'` → INSERT into `tbl_custom_event_occurrences` with `payload_schema_snapshot = event.payload_schema at ingest time` (denormalised — no version-table pointer).
  - `mode='test'` → run through `core/workflows/dry_run.dry_run_workflow()` for every workflow triggered by this event; insert into `tbl_custom_event_test_runs` with `rendered_actions_preview` from dry-run.
- Bus publish:
  - Single publish: `bus.publish(add_prefix(event.name), payload={...occurrence data..., "event": {...properties...}})`.
  - NO `custom_event.received` wrapper event (dropped per architect finding — double-publish creates ghost workflow fires).
  - Publish only for `mode='live'`; test keys never publish.
- `ip_hashed` computed with per-org rotated pepper (from `tbl_organizations.ip_hash_pepper`, generate on first use).
- Response shape (both live and test):
  ```json
  { "occurrence_id": "uuid",
    "contact_id": "uuid or null",
    "mode": "live|test",
    "workflows_triggered": [<uuid>, ...]   // count/IDs of workflows queued
  }
  ```
- Idempotency: on accept, cache the response body in Redis (24h TTL, scoped `(org_id, api_key_id, key)`); on replay, return cached response verbatim.
- Every publish emits audit event `custom_event.published` (redacted body).

**Out of scope:**
- Bridges to workflows trigger catalog (Step 8).
- Workflow lifecycle cascades (Step 9).
- Retention jobs (Step 10).

## Files to touch
- `core/public_ingest/ingest/service.py` (modified — persistence + publish + response).
- `core/public_ingest/custom_events/data_access.py` (modified — occurrence + test_run INSERTs).
- Tests.

## Plan
1. Persistence branch on `mode`.
2. Bus publish (live only).
3. Response shape + idempotency cache write.
4. Audit event.
5. Tests.

## Tests to add
- `test_events_track_live_persists_to_occurrences_with_schema_snapshot`.
- `test_events_track_live_publishes_to_bus_single_publish_no_wrapper`.
- `test_events_track_test_persists_to_test_runs_not_occurrences`.
- `test_events_track_test_never_publishes_to_bus`.
- `test_events_track_test_calls_dry_run_and_stores_rendered_preview`.
- `test_events_track_ip_hashed_uses_per_org_rotated_pepper`.
- `test_events_track_response_shape_includes_workflows_triggered`.
- `test_events_track_idempotency_replay_returns_cached_response_verbatim`.
- `test_events_track_audit_event_emitted_on_publish`.
- `test_events_track_end_to_end_shopify_order_paid_scenario` — full happy path.

## Verification checklist
- Backend: all tests pass.
- Backend: manual curl with real key produces occurrence + fires workflow subscribing to `custom.order.paid`.
- Backend: idempotency replay verified.

## Self-check
- [ ] Rules clean.
- [ ] Rule 8: 3 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
