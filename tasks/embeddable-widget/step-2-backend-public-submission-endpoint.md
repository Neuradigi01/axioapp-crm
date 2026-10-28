# Step 2 — Backend: public `POST /api/v1/embed/leads` endpoint + rate limit

**Goal:** The public-facing endpoint the widget posts to. Authenticates via embed key, applies per-key + per-IP rate limits, validates the submission payload, creates a contact + lead with `source='widget'`, captures UTM + referrer + landing URL, and returns a clean success/error JSON. CORS open. No admin auth. Spam protection (honeypot, min-time) integrated in Step 8.
**Track:** Embeddable Widget
**Status:** Done — `leads.attribution` JSONB column shipped via migration `0045_lead_attribution`; `Lead.attribution`/`LeadCreate.attribution`/`LeadOut.attribution` widened + `create_lead` passes it through + audit snapshot includes it. `core/embed/rate_limit.py` reuses the project's existing `InMemoryRateLimiter` (per-key 100/h, per-IP 10/h, sliding window) — chose in-memory over Redis because Redis isn't installed in the API container, the project already uses InMemoryRateLimiter for auth login, and the swap path is a one-file change with the same `RateLimitResult` interface. `core/embed/submissions.py` ships `submit()` with the full pipeline (honeypot → key lookup → rate-limit → tenant-context-set → dedup-by-phone-or-email via existing `find_existing_contact` helper → create contact if new → create lead with `source='widget'` + attribution + actor=None → audit). `core/embed/router.py` adds `public_router` (separate from key-mgmt router) with `POST /embed/leads` + `OPTIONS /embed/leads` preflight, explicit per-response CORS headers (open `*` with POST+OPTIONS only). All 5 routes confirmed mounted: `POST/GET/DELETE /embed/keys/*` (admin, JWT-gated) + `POST/OPTIONS /embed/leads` (public, key-in-header). End-to-end smoke verified: submission accepted with attribution JSONB round-tripped intact + audit event written + dedup reuses contact across submissions + honeypot silent-drops (accepted=false, lead_id=null, no error) + invalid key → 401. Migration round-trips clean. Notable adaptations: (a) **in-memory rate limit instead of Redis** (matches project convention, no new dep, swap-interface ready); (b) for v1 the widget's `interest` + `notes` payload fold into the contact's `notes` field (since per-org widget config doesn't exist yet — Step 3 will let orgs route these to custom fields); (c) no `core/audit/events.py` (codebase convention; action: `embed.submission.accepted`).
**Depends on:** Step 1 (`embed_keys` table + `find_by_plain_key`), Manual Lead Entry Step 1 (`lead.source='widget'`), Phase 2.4 (Contacts backend), Phase 2.11 (Leads backend).

---

## Scope

In-scope:

- `POST /api/v1/embed/leads` — unauthenticated (no JWT middleware), takes header `X-FurniCRM-Key: pk_live_…` OR body field `embed_key`.
- Request body schema (`EmbedSubmission`):
  ```json
  {
    "embed_key": "pk_live_…",            // optional if header present
    "full_name": "Asha Reddy",
    "phone": "+91 98765 43210",
    "email": "asha@example.com",         // optional
    "interest": "Sofas",                 // optional, free text or one of the org's widget config choices
    "notes": "Looking for L-shape, 5 lakh budget",  // optional
    "honeypot": "",                      // must be empty/missing
    "rendered_at": "2026-05-22T11:23:45Z", // when widget rendered (used in Step 8 for min-time check)
    "attribution": {
      "referrer": "https://google.com/",
      "landing_url": "https://example.com/contact?utm_source=meta&utm_campaign=spring",
      "utm_source": "meta",
      "utm_medium": "paid_social",
      "utm_campaign": "spring",
      "utm_content": null,
      "utm_term": null
    }
  }
  ```
- Response on success: `{"ok": true, "lead_id": "…", "thank_you_url": "https://…"|null}`.
- Response on error: standard `{"detail": "…"}` with appropriate HTTP code.
- Auth/lookup: `find_by_plain_key(embed_key)`. If `None` → 401 with `{"detail": "Invalid or revoked embed key"}`. If valid, resolve `org_id` from the key row.
- Rate limit (token bucket, Redis-backed):
  - Per key: 100 req / hour, burst 20.
  - Per IP (across all keys): 10 req / hour, burst 5.
  - On overage: 429 with `Retry-After` header.
- Validation: Pydantic enforces shape; phone normalized; full_name required; honeypot must be empty (else silent 200 with no lead).
- Lead creation: reuse `ContactService.find_or_create()` (dedup on phone+email within the org) + `LeadService.create(source='widget', actor_user_id=None, attribution=…)`.
- Save attribution as a JSONB column on the lead: `attribution` column added in this step's migration (small).
- CORS: `Access-Control-Allow-Origin: *` on the endpoint. No credentials. Limited methods (POST + OPTIONS preflight).
- Audit events: `embed.submission.accepted` (with `lead_id`, `key_id`, `ip_hash`, `referrer`). On rate-limit hit, `embed.submission.rate_limited`. On spam silent-drop, `embed.submission.rejected_spam`. (Step 8 wires the spam event; this step ships the first two.)
- Tests: happy path, invalid key, revoked key, rate-limit hit, CORS preflight passes, dedup against existing contact, attribution persisted, honeypot silent-drop.

Out of scope:

- No widget config consultation yet — submission accepts any of the documented field set. Step 3 adds the per-org config that constrains which fields are exposed and how `interest` validates (free text vs. enum).
- No reCAPTCHA — Step 8.
- No frontend — Steps 4 / 5–7 ship the UI + widget bundle.

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/0XXX_add_lead_attribution.py` | created — JSONB column on `leads` |
| `api/src/app/core/leads/models.py` | modified — `attribution: Mapped[dict | None]` |
| `api/src/app/core/leads/schemas.py` | modified — `LeadCreate.attribution: dict \| None` |
| `api/src/app/core/embed/submissions.py` | created — public submission service |
| `api/src/app/core/embed/rate_limit.py` | created — Redis token bucket helper |
| `api/src/app/core/embed/router.py` | modified — add `POST /embed/leads` + `OPTIONS /embed/leads` preflight |
| `api/src/app/core/audit/events.py` | modified (small) — declare submission events |
| `api/tests/test_embed_submissions.py` | created |

**8 files, 1 migration.** Inside rule-8 budget.

## Plan

1. Migration: add `leads.attribution JSONB NULL` column. No backfill needed (nullable). Update down-migration to drop.
2. Build `rate_limit.py`:
   - Uses the existing Redis connection (per locked stack — Celery already needs it).
   - `consume(key: str, limit: int, window_seconds: int) -> bool` — returns `True` if allowed, `False` if rate-limited. Sliding-window token bucket via `INCR` + `EXPIRE`.
3. Build `submissions.py`:
   - `submit(payload, ip) -> SubmissionResult`:
     - Honeypot empty? else log + silent 200.
     - Look up key via `embed.service.find_by_plain_key`. None → 401.
     - Rate-limit per key + per IP. Block → 429.
     - Find-or-create contact in the key's org. Create lead with `source='widget'`, `actor_user_id=None`, `attribution=payload.attribution`.
     - Best-effort update `embed_keys.last_used_at` + `last_used_ip`.
     - Emit `embed.submission.accepted` audit.
     - Return `{lead_id, thank_you_url}` (thank_you_url comes from Step 3's widget config; for now, pass `None`).
4. Wire router:
   - `POST /api/v1/embed/leads` — calls `submissions.submit`. Sets CORS headers manually (FastAPI's middleware sees JWT-bound routes first; we want explicit control here).
   - `OPTIONS /api/v1/embed/leads` — returns 204 with the CORS headers.
5. Tests.

## Tests

`api/tests/test_embed_submissions.py`:

- **Happy path:** issue a key, POST a valid submission → 201 with `lead_id`. Lead exists with `source='widget'`, `attribution` populated.
- **Invalid key:** POST with `embed_key="pk_live_garbage…"` → 401.
- **Revoked key:** issue → revoke → POST → 401.
- **Honeypot filled:** POST with `honeypot: "spam"` → 200 with `{ok: true, lead_id: null}` and **no lead created**.
- **Rate limit per key:** burst 20 successes, then 429. `Retry-After` set.
- **Rate limit per IP:** 5 successes from same IP (across different keys would also count) → 429.
- **Contact dedup:** POST twice with same phone → second submission creates a new **lead** but reuses the existing **contact**.
- **CORS:** OPTIONS request → 204 with `Access-Control-Allow-Origin: *`.
- **Attribution persisted:** lead row's `attribution` JSONB matches the submitted payload.
- **No JWT required:** request without `Authorization` header succeeds with a valid embed key.
- **Audit:** one `embed.submission.accepted` per successful submission; one `embed.submission.rate_limited` per 429.

## Smoke

```powershell
# Issue a key (admin auth)
$token = "<owner JWT>"
$secret = (curl -X POST http://localhost:8000/api/v1/embed/keys `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{"name":"smoke"}' | ConvertFrom-Json).secret

# Submit (public — no Authorization header)
curl -X POST http://localhost:8000/api/v1/embed/leads `
  -H "X-FurniCRM-Key: $secret" `
  -H "Content-Type: application/json" `
  -d '{"full_name":"Smoke Asha","phone":"+919876543210","email":"smoke@example.com","interest":"Sofas","honeypot":"","rendered_at":"2026-05-22T11:00:00Z","attribution":{"referrer":"https://example.com/","landing_url":"https://example.com/contact","utm_source":"test"}}'
# Expect 201 with {ok:true, lead_id:"…", thank_you_url:null}

# Hammer to test rate limit (run 22 times)
1..22 | ForEach-Object {
  curl -X POST http://localhost:8000/api/v1/embed/leads `
    -H "X-FurniCRM-Key: $secret" `
    -H "Content-Type: application/json" `
    -d '{"full_name":"Burst","phone":"+919876543210","honeypot":"","rendered_at":"2026-05-22T11:00:00Z","attribution":{}}'
}
# Expect 20 successes then 429s.
```

## Risks

- **CORS misconfiguration leaks admin routes:** explicit per-route CORS (not a global middleware) keeps the open policy scoped to `/embed/leads` and OPTIONS only. Test confirms admin routes still require Origin matching whatever the global config is.
- **Redis dependency:** if Redis is down, rate-limit fails open or closed? Choose **fail open** (allow the submission) — losing submissions is worse than letting in a few extra during a Redis outage. Log a metric. Document in `rate_limit.py`.
- **Argon2 cost on hot path:** every submission verifies one Argon2 hash (~50ms). At 100 req/hr/key, this is comfortably within capacity. If we add many keys per org and traffic spikes, cache `prefix → row` in Redis with 60s TTL as a follow-on.
- **`last_used_at` write contention:** could be ignored on the hot path; do an async best-effort update via a fire-and-forget Celery task to keep submission latency low.
- **Attribution JSONB schema drift:** Pydantic enforces a known shape, but `attribution` is JSONB so future fields are additive. Document the v1 keys in `schemas.py` so they don't fork into multiple shapes across surfaces.

## Rollback

Revert migration (drops `leads.attribution`). Delete new files. Revert router additions. Keys from Step 1 remain valid but unused.
