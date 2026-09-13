# Step 4 — API-keys hardening: HMAC-of-full-key prefilter, rotate-with-grace, live/test modes

**Goal:** implement the fast HMAC-of-full-key prefilter (defeat Argon2id DoS), rotate-with-grace flow, `pk_live_` / `pk_test_` prefix modes, separate rate-limit buckets. Enforce HMAC-secret non-revealability. Alert on lingering old_key usage.
**Phase:** Custom Events track — step 4/17
**Depends on:** Steps 1, 2, 3
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/api_keys/service.py`:
  - **Auth verify:** `verify_api_key(bearer_secret) -> ApiKey | None` — computes `key_lookup_hash = HMAC(pepper, secret)`, indexed lookup on `tbl_api_keys.key_lookup_hash`, Argon2id verify only on match. At most one Argon2id call per request.
  - **Rotate-with-grace:** `rotate_key(key_id)` — generates new secret; sets `key_hash = argon2(new)`, `old_key_hash = <previous_key_hash>`, `old_key_expires_at = now() + 24h`. Returns new secret to caller (one-time reveal). Verify accepts either hash within grace window.
  - **3rd-rotation guard:** if `old_key_hash IS NOT NULL AND old_key_expires_at > now()`, second rotate returns 409 "Grace window active — wait or force-purge." Force-purge endpoint `POST /api-keys/{id}/force-purge-old` clears old_key + expires.
  - **HMAC-secret non-revealability:** `hmac_secret_encrypted` never rendered in any response schema; `SecretStr` + `exclude=True` on Pydantic model.
  - **Live/test modes:** key prefix `pk_live_` or `pk_test_` set by `mode` at create. Verify enforces prefix matches `mode`.
- Separate rate-limit buckets (via `shared/rate_limit` per Step 3 with different limit configs):
  - live keys: `rate_limit_per_minute` from row (default 100).
  - test keys: hardcoded 20/min + 1000/day hard cap.
- Celery beat task `check_old_key_usage_alerts` — runs hourly; for any key with `old_key_hash NOT NULL AND now() - (old_key_expires_at - 24h) > 12h`, count requests using old hash in last hour (from ingest log); if > 0, send Owner an alert email.
- Auth endpoint `POST /api-keys` (Owner-only) creates with `mode`, `default_owner_user_id`, `auto_create_contacts`, `hmac_required`, `rate_limit_per_minute`, `hmac_secret` (generated). Response reveals full secret + HMAC-secret ONCE.

**Out of scope:**
- Frontend page (Step 11).
- Events-endpoint wiring (Step 7).

## Files to touch
- `core/public_ingest/api_keys/service.py` (populated).
- `core/public_ingest/api_keys/router.py` (populated — CRUD + rotate + force-purge).
- `core/public_ingest/api_keys/data_access.py` (populated).
- `core/public_ingest/api_keys/schemas.py` (populated — with `SecretStr` fields excluded from responses).
- `core/public_ingest/api_keys/tasks.py` (new — `check_old_key_usage_alerts`).
- `core/audit/` — 4 new event types: `api_key.created`, `.rotated`, `.revoked`, `.force_purged_old`.
- `core/permissions/registry.py` — `settings.integrations.api_keys.manage` (Owner-only).
- Tests.

## Plan
1. Verify path (HMAC prefilter + Argon).
2. Rotate flow + 3rd-rotation guard + force-purge.
3. Response-schema audit — assert `hmac_secret_encrypted` never leaks (test `test_api_key_response_never_leaks_hmac_secret_via_orm_repr_or_response_schema`).
4. Live/test prefix enforcement.
5. Separate rate limits wired through shared `rate_limit`.
6. Alert Celery task + wire to beat schedule.
7. Audit events on every mutation.

## DB changes / migrations
None new (columns added in Step 1).

## Tests to add
- `test_api_key_verify_uses_hmac_prefilter_o1` — 1000 random tokens → 0 Argon calls (measure via mock).
- `test_api_key_verify_argon_called_at_most_once_per_request`.
- `test_api_key_rotate_with_grace_both_hashes_valid_24h`.
- `test_api_key_rotate_optimistic_lock_second_writer_409` (using `updated_at`).
- `test_api_key_third_rotation_returns_409_when_grace_active`.
- `test_api_key_force_purge_clears_old_hash`.
- `test_api_key_hmac_secret_never_in_response_schema`.
- `test_api_key_hmac_secret_never_in_repr`.
- `test_api_key_live_prefix_rejected_when_mode_test`.
- `test_api_key_test_prefix_routes_to_lower_rate_limit`.
- `test_api_key_test_key_cannot_auto_create_contacts` (validated in service).
- `test_check_old_key_usage_alerts_emails_owner_when_still_in_use_at_12h`.
- Audit events verified.

## Verification checklist
- Backend: all tests pass.
- Backend: Celery beat schedule updated.
- Backend: manual create key → response contains secret once; second GET does not.

## Self-check
- [ ] Rule 1: core.
- [ ] Rule 2: RLS on tbl_api_keys.
- [ ] Rule 6: new permission key registered.
- [ ] Rule 8: ~10 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
