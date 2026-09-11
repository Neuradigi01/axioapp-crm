# Step 7a — `POST /events/track` auth pipeline (HMAC prefilter → Argon2id → HMAC verify → idempotency → rate limits)

**Goal:** wire the security perimeter of the public ingest endpoint. No payload processing yet — only the request-plumbing chain that gates every downstream step.
**Phase:** Custom Events track — step 7a/17
**Depends on:** Steps 3, 4
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/ingest/router.py`: `POST /api/v1/events/track` route stub. Sequence:
  1. Middleware ensures `request.state.raw_body` populated (from Step 3).
  2. Pre-auth per-IP rate limit (20/min per XFF-resolved IP; Redis-backed; fail-closed 503 on Redis outage).
  3. `Authorization: Bearer` header parse. Validate prefix (`pk_live_` or `pk_test_`). Reject at parse if malformed (400 with generic message — no info leak).
  4. HMAC-of-full-key prefilter lookup via `verify_api_key(bearer)` from Step 4. On miss → 401 (constant-time delay to avoid timing oracle).
  5. Argon2id verify (Step 4). On miss → 401.
  6. `resource_type` check: key must have `resource_type='events'`. Else 403.
  7. `mode` check: `pk_live_` → `mode='live'`, `pk_test_` → `mode='test'`. Mismatch → 401.
  8. Per-key rate limit (Redis, sliding window; `rate_limit_per_minute` from key row for live; hardcoded 20/min + 1000/day for test).
  9. If `key.hmac_required=true`: verify `X-CRM-Signature` + `X-CRM-Timestamp` against `raw_body` using `shared.hmac_verify.verify_signature()`. On failure → 401 before any side effect. Include nonce cache check (Redis, `SETNX`).
  10. Parse body as JSON (post-HMAC to avoid double-read). Validate `event` field regex (name-only sanity check; deeper validation Step 7b).
  11. Idempotency check: `Idempotency-Key` header OR body `messageId`. Scope `(org_id, api_key_id, key)`. If replay: return cached response 200.
- No payload validation yet (Step 7b).
- No contact resolution yet (Step 7b).
- No bus publish yet (Step 7c).
- Response for happy-path stub: 202 Accepted `{ "status": "queued", "occurrence_id": null }` (real response in 7c).
- Every rejection logs to `tbl_public_ingest_log` with `source_type='events'` and outcome (rate_limited / auth_failed / hmac_failed / etc.).
- Every accepted request emits `custom_event.ingested` audit (redacted body).

**Out of scope:**
- Payload/schema validation.
- Contact resolution.
- Occurrence persistence + bus publish.

## Files to touch
- `core/public_ingest/ingest/router.py` (new).
- `core/public_ingest/ingest/service.py` (new — orchestration stub).
- `main.py` (modified — router include).
- Tests.

## Plan
1. Router with sequence above.
2. Service orchestrator.
3. Extensive test coverage on every rejection path.

## Tests to add
- `test_events_track_401_missing_bearer`.
- `test_events_track_401_malformed_prefix`.
- `test_events_track_401_valid_prefix_no_matching_key` — constant-time (measure).
- `test_events_track_401_valid_prefilter_wrong_argon`.
- `test_events_track_403_wrong_resource_type` — key with `resource_type='lead_form'`.
- `test_events_track_401_mode_mismatch_pk_live_vs_test_key`.
- `test_events_track_401_hmac_required_missing_signature`.
- `test_events_track_401_hmac_invalid_signature_constant_time`.
- `test_events_track_401_hmac_timestamp_out_of_window`.
- `test_events_track_401_hmac_nonce_replay_within_window`.
- `test_events_track_429_pre_auth_ip_rate_limit`.
- `test_events_track_429_per_key_rate_limit`.
- `test_events_track_test_key_stricter_rate_limit`.
- `test_events_track_idempotency_key_header_replay_returns_cached_200`.
- `test_events_track_messageId_body_field_dedup`.
- `test_events_track_idempotency_scope_org_key_idem_no_cross_key_collision`.
- `test_events_track_503_when_redis_down_events_surface_fails_closed`.

## Verification checklist
- Backend: all tests pass.
- Backend: manual curl with malformed bearer → 401; correct bearer → 202.
- Backend: XFF chain parsing correct for trusted-proxy config.

## Self-check
- [ ] Rule 1-2 clean.
- [ ] Rule 8: 4 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
