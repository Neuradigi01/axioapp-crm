# Step 3.5.15 — Per-org rate limiting + Meta 429 backoff

**Goal:** Respect Meta's rate limits — free tier ~80 msg/sec, business-verified tiers up to 1000/sec. Per-org throttle so campaigns from different orgs don't starve each other. Auto-backoff on 429 with retry.

**Phase:** 3.5
**Depends on:** 3.5.14 (Celery dispatch)
**Status:** PROPOSED — awaiting "begin"

After this step a 5,000-contact campaign runs steadily at the configured rate without bursting and triggering Meta 429 rate-limit errors, even if 3 orgs send concurrently from the same Celery worker pool.

---

## Scope

### In-scope

- Per-org token bucket in Redis (already available in the stack):
  - Key: `wa_rate:{org_id}` — int counter
  - Refill rate: configurable per-org (default 50 msg/sec; Owner editable in Settings → Integrations → WhatsApp card → "Advanced")
  - Burst capacity: 2 × refill rate
- Helper `await acquire_rate_token(org_id, count=1)` in Celery task — blocks (`asyncio.sleep`) until a token is available.
- 429 backoff in adapter: on Meta `429` response, parse `Retry-After` header, sleep that long, retry once. If 429 repeats, raise `WhatsAppRateLimited` → Celery retries with backoff.
- Settings UI: small "Rate limit" section in the WhatsApp card under "Advanced" → number input (default 50). Saves to `WhatsAppAccountConfig.rate_limit_per_sec`.
- Migration `0067_whatsapp_account_rate_limit.py` — add column, default 50.

### Out-of-scope

- Cross-worker rate coordination → Redis-based bucket handles this (single source of truth).
- Per-template rate (some templates are throttled stricter) → P2.
- Quality rating monitoring (Meta lowers your tier if you spam) → P2 dashboard.

---

## Files to touch

### Created (1)
- `API/alembic/versions/0067_whatsapp_account_rate_limit.py`

### Modified (~5)
- `API/src/app/core/conversations/adapters/whatsapp.py` — 429 handling
- `API/src/app/core/campaigns/tasks.py` — rate token acquisition wrap
- `API/src/app/core/integrations/whatsapp/models.py` — new column
- `API/src/app/shared/rate_limit.py` — add Redis token-bucket primitive (reusable)
- `APP/.../whatsapp-card.component.{ts,html}` — rate limit input
- Tests covering 429 retry + token bucket

**File budget:** ~7 files.

---

## Plan

1. Token bucket implementation: standard "leaky bucket via lua script" in Redis to avoid race conditions across workers.
2. Adapter 429: identify by status code + `error.code=131056` (Meta's rate limit). Read `Retry-After`, sleep, single retry.
3. UI: integer input 10..1000, validated min/max.

---

## Pre-implementation question

**Q:** Rate limit ko **per-org configurable** rakhein ya hardcoded value (50/sec) jisse ops control kare?

- **(a) Per-org UI input** — operator sets based on their Meta tier (default 50, can bump to 1000 if verified)
- **(b) Hardcoded** — single value in env var, set conservatively (50). Operator can't configure.

**Recommendation: (a)** — different orgs are on different Meta tiers; hardcoding wastes capacity for big orgs and risks overload for small ones.

---

## Verification + Self-check + Stop & report — standard

---

# Phase 3.5 complete

After this step, the WhatsApp Campaigns vertical is **MVP-shipping ready**:
- Multi-tenant connect (3.5.1, 3.5.2)
- Per-org outbound (3.5.3)
- Templates (3.5.4, 3.5.5)
- Per-contact variable resolution + send (3.5.6)
- Audience: groups + import + builder (3.5.7-3.5.11)
- Delivery tracking + UI (3.5.12, 3.5.13)
- Async + rate-safe (3.5.14, 3.5.15)

Next phase: Step 3.5.16+ would be optional polish — analytics dashboard, A/B testing, template performance reports.
