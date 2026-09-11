# Step 3 — Redis-backed rate-limit + idempotency + HMAC nonce cache

**Goal:** replace in-process rate-limit / idempotency / nonce-cache with Redis. Configure trusted-proxy list. Startup fail-loud in prod on missing config. Explicit fail-mode per surface (events = fail-closed 503; embed/ai keep fail-open).
**Phase:** Custom Events track — step 3/17
**Depends on:** Step 2
**Status:** COMPLETED

## Scope

**In-scope:**
- `api/src/app/shared/rate_limit.py`: sliding-window Redis-backed counters (Lua-scripted atomic ZREMRANGEBYSCORE → ZCARD → ZADD). Three bucket types per request: pre-auth IP, post-auth per-key, per-identifier (email/phone lookups). Namespaced by `org_id` at key prefix (`ratelimit:org:<uuid>:key:<hash>:...`).
- `api/src/app/shared/idempotency.py`: `store_and_return(scope_key, ttl=24h) -> IdempotencyResult`. Scope = `(org_id, api_key_id, key)`. Redis DB dedicated (or `noeviction` policy per key). Regex-validate incoming key: `^[A-Za-z0-9_.:\-]{1,128}$` before Redis put.
- `api/src/app/shared/hmac_verify.py`: `verify_signature(raw_body: bytes, signature_header: str, secret: str, timestamp_header: str, window_seconds: int = 300, clock_skew_seconds: int = 150)`. Constant-time `hmac.compare_digest`. Nonce cache in Redis with `SETNX` + TTL=window+skew.
- `TRUSTED_PROXIES` config validation on startup — fail-loud in `ENV=prod` if empty.
- XFF chain parsing helper: `parse_client_ip(request, trusted_proxies) -> str` — walks XFF from right, stops at first non-trusted.
- **Fail modes:** events surface fails CLOSED (503 + retry-after header) on Redis outage; embed keeps fail-open (documented). AI-assistant keeps its existing (fail-closed per OpenAI cost concern).
- Middleware: read raw body BEFORE Pydantic parse (via ASGI middleware saving to `request.state.raw_body`) so HMAC verify can compare.
- Wire embed router to use the shared Redis rate-limit (migration from in-process module singleton).

**Out of scope:**
- Events-endpoint wiring (Step 7).

## Files to touch
- `api/src/app/shared/rate_limit.py` (modified — Redis backend, sliding window, 3 bucket types).
- `api/src/app/shared/idempotency.py` (populated).
- `api/src/app/shared/hmac_verify.py` (populated).
- `api/src/app/shared/middleware.py` (modified — raw-body capture middleware).
- `api/src/app/main.py` (modified — startup checks; register middleware).
- `api/src/app/shared/config.py` or equivalent (modified — `TRUSTED_PROXIES` + `REDIS_URL_PUBLIC_INGEST` if separate DB).
- `core/public_ingest/embed/router.py` (modified — use shared rate-limit).
- Tests.

## Plan
1. Redis rate-limit with Lua script (atomic).
2. Idempotency store.
3. HMAC verify with nonce cache.
4. Raw-body middleware.
5. Startup checks (TRUSTED_PROXIES nonempty in prod).
6. Wire embed + ai_assistant to new shared helpers.
7. Test multi-worker simulation.

## DB changes / migrations
None (Redis only).

## Tests to add
- `test_rate_limit_shared_across_workers_via_redis` (simulate two connections; cumulative count enforced).
- `test_rate_limit_events_surface_fails_closed_503_on_redis_outage`.
- `test_idempotency_scope_org_key_idem_no_cross_key_collision`.
- `test_idempotency_survives_process_restart` (Redis backing).
- `test_idempotency_key_regex_rejects_bad_chars`.
- `test_hmac_verify_constant_time`.
- `test_hmac_verify_timestamp_clock_skew_window`.
- `test_hmac_verify_nonce_cache_rejects_replay_within_window`.
- `test_startup_fails_loud_on_missing_trusted_proxies_in_prod`.
- `test_xff_chain_picks_rightmost_untrusted_hop`.

## Verification checklist
- Backend: tests pass.
- Backend: Redis connectivity confirmed via `redis-cli`.
- Backend: embed endpoint still passes rate-limit tests.

## Self-check
- [ ] Rules 1-2 clean.
- [ ] Rule 8: ~8 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
