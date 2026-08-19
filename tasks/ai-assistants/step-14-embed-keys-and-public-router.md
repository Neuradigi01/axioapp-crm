# Step 14 — Embed keys extension + public router + rate limit + CAPTCHA + immediate-revoke

**Goal:** Ship the public-facing surface. Extend existing `tbl_embed_keys` with `resource_type='ai_assistant'`. Mount `public_router.py` under a distinct URL prefix. Pin-test blocks stray JWT usage in public router. Redis-backed per-key + per-org rate limit (fail-closed). First-message Turnstile CAPTCHA. Immediate-revoke path alongside opt-in 7-day grace. Origin-header allow-list as advisory. No widget bundle yet (Step 15).
**Status:** COMPLETED
**Depends on:** Step 5 (`tbl_embed_keys` schema extension), Step 9 (chat runtime), existing `core/embed/rate_limit.py` infra.

---

## Scope

In-scope:

- `core/ai_assistants/public_router.py` — NEW, mounted under `/api/v1/public/ai-assistants/*`:
  - `POST /session/init` — issues a session cookie + Turnstile challenge on first hit. Body: `{embed_key}` (also in header). Returns `{session_token, requires_captcha: bool}`.
  - `POST /message` — send a user message + stream reply. Body: `{message, session_token, captcha_token?, conversation_id?}`. Headers: `Authorization: Bearer <embed_key>` (not URL query — per M4). Streams SSE per Step 9.
  - `GET /assistant` — returns public-safe assistant metadata for widget bootstrapping (name, interface_config, styling_config only — never instructions/key_id/audit).
  - Every handler takes `PublicContext(org_id, assistant_id, embed_key_id)` derived only from the embed key. **Body/query `org_id` / `assistant_id` / `conversation_id` are ignored** — conversation_id must belong to `(org_id, assistant_id, session_token)` or a fresh conversation is created.
- `core/embed/service.py` (extend) — `resolve_embed_key(raw_key) -> ResolvedEmbedKey | None` uses prefix-lookup + bcrypt-compare already in `core/embed/`. New method `assert_ai_assistant_key(resolved)` — 401 if `resource_type != 'ai_assistant'` or `resource_id` NULL.
- `core/embed/data_access.py` (extend) — `set_immediate_revoke(embed_key_id)` and `expire_grace(now)` (Step 17 uses the latter).
- `core/embed/router.py` (extend, existing operator-facing) — endpoints for the AI assistant:
  - `POST /ai-assistants/{id}/embed-keys` — issue new key; body: `{label, allowed_origins[], rate_limit_per_hour}`.
  - `GET /ai-assistants/{id}/embed-keys` — list (never returns raw key after issue).
  - `POST /embed-keys/{key_id}/rotate` — issues new key; default: **immediate revoke of old** (grace_days=0); accepts `?grace_days=<0..7>` to enable graceful rollover.
  - `POST /embed-keys/{key_id}/revoke-now` — hard-revoke; flushes Redis rate-limit + closes any open SSE streams for this key.
  - `DELETE /embed-keys/{key_id}` — soft-delete then hard-delete after grace.
- **Distinct URL prefix + ingress rule** — public router mounted at `/api/v1/public/ai-assistants/*`. Add a comment in the ingress config (or FastAPI middleware) that strips `Authorization: Bearer` values that look like JWTs on public prefix (embed keys have a distinct `emb_` prefix; JWTs start with `eyJ`).
- **Pin-test** — [API/tests/test_public_router_no_jwt.py](API/tests/test_public_router_no_jwt.py) — walks every function in `core/ai_assistants/public_router.py` via `ast`; fails CI if any reads `current_user`, `require_permission`, or calls JWT-dependent helpers. Every function must accept a `PublicContext` dep.
- **Rate-limit extension** — reuse `core/embed/rate_limit.py`. Add per-org bucket in addition to per-IP + per-key. **Fail-closed** on Redis outage (return 429 with `Retry-After: 30`). Config: default 60/hour/IP, 300/hour/key, 2000/hour/org (configurable).
- **Turnstile** — Cloudflare Turnstile integration (matches other public forms; grep `TURNSTILE_` for existing keys). First message per session requires token; subsequent messages within session don't. Verify server-side.
- **Origin allow-list check** — `Origin` header compared against `embed_key.allowed_origins`; on mismatch, log + return 403 (identical body). Documented in-code as advisory (non-browser clients spoof easily; real defence is rate limit + budget cap + Turnstile).
- **CORS** — public prefix has `Access-Control-Allow-Origin: <matching origin>`, `Vary: Origin`, `Access-Control-Allow-Credentials: false`. Never echoes unknown origin.
- **Budget-cap enforcement point** — already in Step 9's runtime; this step surfaces it to the public path: budget-cap-hit returns SSE `error` event with `reason='budget_cap_hit'` then closes stream.
- **In-flight SSE tracking** for immediate-revoke: `runtime.stream_reply` registers its cancel-token in `SseStreamRegistry` (in-memory per process); revoke-now walks the registry and cancels all streams matching the embed_key_id.

Out of scope:
- Widget bundle (Step 15).
- Analytics / audit reporting (Step 16).
- Retention / grace-window reaper (Step 17).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/ai_assistants/public_router.py` | **NEW** |
| `API/src/app/core/ai_assistants/public_context.py` | **NEW** — `PublicContext` dataclass + FastAPI dep |
| `API/src/app/core/ai_assistants/sse_registry.py` | **NEW** — in-memory SSE cancel-token map |
| `API/src/app/core/ai_assistants/runtime.py` | **EDIT** — register/deregister in SseStreamRegistry |
| `API/src/app/core/embed/service.py` | **EDIT** — `assert_ai_assistant_key`, `set_immediate_revoke` |
| `API/src/app/core/embed/data_access.py` | **EDIT** |
| `API/src/app/core/embed/router.py` | **EDIT** — new operator endpoints |
| `API/src/app/core/embed/rate_limit.py` | **EDIT** — per-org bucket, fail-closed |
| `API/src/app/main.py` | **EDIT** — mount public router with distinct prefix |
| `API/src/app/shared/turnstile.py` | **EDIT or NEW** — verify helper (if not existing) |
| `API/config.env.example` | **EDIT** — `TURNSTILE_SECRET_KEY` if new |
| `API/tests/test_public_router_no_jwt.py` | **NEW** — pin-test |
| `API/tests/ai_assistants/test_public_router.py` | **NEW** |
| `API/tests/ai_assistants/test_embed_key_revoke.py` | **NEW** |
| `API/tests/embed/test_rate_limit_fail_closed.py` | **NEW** |

**~15 files. ~700 lines.** Over — public surface + pin-test + rate-limit + revoke + Turnstile all interlock and must ship together for the widget in Step 15 to work.

## Plan

1. Public context first — small `dataclass(PublicContext)` + FastAPI `Depends()` that reads header + resolves + throws 401 on failure.
2. Public router: 3 endpoints (init, message, assistant). Message endpoint returns `StreamingResponse` via runtime.
3. Pin-test using `ast` module: walk imports + function bodies; fail on `current_user` / `require_permission` / `get_current_user_dependency`.
4. Rate limit: existing Redis client + new bucket key formulas `rl:org:{org_id}:h`, `rl:key:{key_id}:h`, `rl:ip:{ip}:h`. Fail-closed via `try/except redis.exceptions.RedisError → return 429`.
5. Turnstile: standard server-side verify against Cloudflare's siteverify endpoint. Cache result per session_token (5-min TTL) to avoid re-verifying every message.
6. Revoke-now: `SseStreamRegistry.cancel_by_embed_key(id)` iterates in-memory tokens; each cancel triggers the stream's cleanup path from Step 9.
7. CORS handled by a small middleware on the public prefix only — inserted after existing global CORS so this one wins for `/api/v1/public/*`.

## DB changes / migrations

None (schema from Step 5 covers).

## Tests

- Public endpoint with body `{"conversation_id":"<other org's uuid>"}` under embed key K → returns 404 same as `nonexistent-uuid`.
- Body `{"org_id":"<other>"}` silently ignored — response uses key's org.
- Unknown embed key → 401.
- Off-allow-list `Origin` → 403.
- No Turnstile token on first message → 400 with `captcha_required`.
- Valid Turnstile token → succeeds; subsequent messages in same session don't re-verify.
- Per-key rate-limit 429 with `Retry-After` on 61st req.
- Per-org rate-limit 429 across 2 keys once total > 2000/hr.
- Redis outage → 429 (fail-closed).
- Pin-test: manually write a public_router function calling `current_user`; assert the pin-test fails.
- Rotate with `grace_days=0` immediately revokes.
- Revoke-now closes SSE mid-stream: mock an active stream, revoke, assert `RuntimeError('embed_key_revoked')` propagated.

## Smoke

```
1. As operator, create embed key for assistant. Copy raw key (shown once).
2. curl POST /api/v1/public/ai-assistants/session/init with Authorization: Bearer <key>
   Origin: https://mysite.com → {session_token, requires_captcha:true}.
3. curl POST /message with Turnstile token → SSE stream of tokens.
4. curl POST /message from Origin: http://other.com → 403.
5. Revoke-now — subsequent /message → 401.
6. Kill Redis — /message → 429.
```

## Risks

- Pin-test using `ast` may miss dynamic imports; kept simple — direct import + call detection covers the common case.
- Turnstile requires production keys in prod; dev uses `1x0000000000000000000000000000000AA` bypass.
- SSE cancellation across processes not supported in v1 (single-process registry); documented — Step 17's janitor can force-close via a Redis pub/sub if multi-process needed later.

## Self-check (10 rules)

`core/ai_assistants/` + `core/embed/` extensions. ✓ Rule 2: all queries scoped by org_id derived from embed key. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. ✓ N/A permission (public router has embed-key auth). ✓ pack.yaml untouched. ✓ 15 files / ~700 lines — over but public surface must ship as one. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 14 — Embed keys extension + public router + rate limit + CAPTCHA + revoke
Files: 15
Verify: public endpoint isolates by embed-key; pin-test blocks JWT usage;
        rate limit fail-closed; Turnstile enforced on first message; revoke-now
        closes SSE.
Tests: ~11 pytest cases.
Awaiting "proceed".
```
