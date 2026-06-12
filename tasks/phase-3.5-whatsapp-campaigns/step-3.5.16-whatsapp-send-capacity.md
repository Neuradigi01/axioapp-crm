# Step 3.5.16 — WhatsApp send capacity (tier + remaining today)

**Goal:** Surface the connected WhatsApp number's **current Meta messaging tier** and **today's remaining unique-recipient quota** on the campaign create page so the agent always sees how many more sends are safe before tripping Meta's daily cap.

**Phase:** 3.5
**Depends on:** 3.5.1 (account config), 3.5.3 (per-org outbound), 3.5.4 (templates sync — same Meta auth path), 3.5.14 (Celery dispatch — populates the `messages` table the counter reads)
**Status:** TODO

After this step, an agent opening "New Campaign" sees a coloured banner:

```
WhatsApp quota: 10,000 per day
2,847 used · 7,153 remaining today
████████░░░░░░░░░░░░░░░░░░  28%
```

When the campaign's audience size approaches or exceeds remaining quota, the form warns inline; when remaining is zero the Send button is gated.

---

## Scope

### In-scope

- **Backend service** `core/integrations/whatsapp/status.py::get_send_capacity(session)` returning:
  - `tier` (Meta value: `TIER_50`, `TIER_250`, `TIER_1K`, `TIER_10K`, `TIER_100K`, `TIER_UNLIMITED`)
  - `tier_label` (human: "10,000 per day")
  - `daily_limit` (int; `-1` for unlimited)
  - `used_today` (DISTINCT recipient count in last 24h rolling window)
  - `remaining` (`daily_limit - used_today`, floored at 0)
  - `usage_percent` (0–100; 0 for unlimited)
  - `is_unlimited` (bool)
- **Tier fetch from Meta:** `GET /{phone_id}?fields=messaging_limit_tier` — single field, single call. Uses the same encrypted-token decrypt path as `templates.sync_templates`.
- **Tier cache column** on `WhatsAppAccountConfig`: `messaging_limit_tier TEXT NULL`, `tier_synced_at TIMESTAMPTZ NULL`. Reused for 1 hour before re-pulling.
- **Used-today query:** count `DISTINCT conversation_id` from `messages` JOIN `conversations` where `conversations.channel = 'whatsapp'`, `messages.direction = 'out'` (note: the enum value is the short form `'in'`/`'out'`, not `'inbound'`/`'outbound'` — the doc's earlier draft was wrong), `messages.sent_at >= now() - interval '24 hours'`. Matches Meta's "unique customers per 24h rolling window" accounting — not total message count.
- **REST endpoint** `GET /api/v1/integrations/whatsapp/capacity` returning the dict above.
  - Permission: `campaigns.read` (same as templates list — every campaign-author needs this, not just integration admins).
  - Returns `409 WhatsAppNotConnected` if no active integration.
- **Frontend banner** at the top of the campaign create page that:
  - Loads capacity on mount via `whatsappCapacityService.load()`.
  - Colours by `usage_percent` thresholds: green `<70`, amber `70..89`, red `>=90`.
  - Hides progress bar + shows "Unlimited messages today" when `is_unlimited`.
  - Refresh button calls the endpoint again (no debounce — owner-triggered).
- **Audience-size warning** below the recipient picker:
  - `selected > remaining` (and not unlimited) → red error: "X selected, only Y remaining today. Z contacts will be skipped or queue for tomorrow."
  - `selected > remaining * 0.5` → amber warning: "This campaign will use N% of today's remaining quota."
- **Send button gate:** disabled when `remaining === 0 && !is_unlimited`. Tooltip explains reset time.
- **Frontend state** added directly on `CreateCampaignModalComponent` — `capacity = signal<WhatsAppCapacity | null>(null)`, `capacityBand`, `audienceQuotaWarning`, `quotaBlocksSubmit` computed signals. A separate `WhatsappCapacityService` was not created — the only consumer of this state today is the modal itself; a service would have been premature abstraction. Promoted to a shared service when a second component (e.g. a Settings dashboard widget in 3.5.17) needs the same fetch.

### Out-of-scope

- Quality rating (GREEN/YELLOW/RED) surfacing → separate future step (3.5.17).
- Auto-pause campaigns on quality drop → future step.
- Sent / Delivered / Read live ticker → already in 3.5.13.
- Multi-number per org capacity rollup → P2 (today: one WABA per org).
- Background Celery hourly refresh of `messaging_limit_tier` → out of scope; on-demand cache (1h TTL) is enough for the picker. A scheduled refresh can come with quality monitoring in 3.5.17.
- Storing `used_today` in a denormalised column → unnecessary; the DISTINCT count on indexed `messages.sent_at` is fast at our scale, and a stored counter would drift.

---

## Files to touch

### Created (3)

- `API/alembic/versions/0084_whatsapp_account_tier_cache.py` — add `messaging_limit_tier`, `tier_synced_at` to `whatsapp_account_configs`. (Migration number corrected from the doc's original `0068` placeholder — the actual next slot was `0084`.)
- `API/src/app/core/integrations/whatsapp/status.py` — `get_send_capacity()` + tier cache helpers + `TIER_LIMITS` / `TIER_LABELS` constants.
- `API/tests/test_whatsapp_capacity.py` — service + tier-cache + tier-constants tests.

### Modified (~5)

- `API/src/app/core/integrations/whatsapp/models.py` — add the two new columns to `WhatsAppAccountConfig`.
- `API/src/app/core/integrations/whatsapp/router.py` — add `GET /capacity` endpoint.
- `API/src/app/core/integrations/whatsapp/schemas.py` — add `WhatsAppCapacityOut` response model.
- `APP/src/app/features/user/core/settings/integrations/integrations-api.service.ts` — add `WhatsAppCapacity` shape + `getWhatsAppCapacity()` HTTP method. (Reused the existing `IntegrationsApiService` instead of creating a new `whatsapp-capacity.service.ts` — there was no shared-state need across multiple components, only the modal consumes it, so a dedicated service would be premature abstraction.)
- `APP/src/app/features/user/core/campaigns/create-campaign-modal.component.{ts,html}` — banner above audience fieldset, quota-vs-audience warning under audience-count line, send-button gate.

**File budget:** 8 files. Well under the 10-file / 400-line limit.

---

## Plan

1. **Migration `0068`** — add `messaging_limit_tier TEXT NULL` and `tier_synced_at TIMESTAMPTZ NULL` to `whatsapp_account_configs`. Both nullable so existing rows stay valid. Up + down verified.

2. **`status.py`** with:
   - Constants `TIER_LIMITS` (dict[str, int]) and `TIER_LABELS` (dict[str, str]). Sentinel `-1` for unlimited.
   - `_fetch_tier_from_meta(*, phone_id, access_token, api_version) -> str` — `httpx.AsyncClient(timeout=10.0)`, single GET, parses `messaging_limit_tier`, raises `WhatsAppNotConnected` on 4xx/5xx (re-uses the existing exception class — router already maps it to 409).
   - `_get_tier_cached(session, config) -> str` — returns `config.messaging_limit_tier` if `tier_synced_at` is within 1 hour, else refreshes from Meta and persists. `_TIER_CACHE_TTL = timedelta(hours=1)`.
   - `_count_unique_recipients_today(session) -> int` — SQLAlchemy `select(func.count(func.distinct(Message.conversation_id)))` JOIN to `Conversation` filtered by `channel == 'whatsapp'`, `direction == outbound`, `sent_at >= now() - 24h`. RLS handles org scoping (every TenantScoped query already does).
   - `get_send_capacity(session) -> dict` — orchestrates the three primitives, computes derived fields (`remaining`, `usage_percent`, `is_unlimited`), returns the dict.

3. **Router** — add:
   ```python
   @router.get("/capacity", response_model=WhatsAppCapacityOut)
   async def whatsapp_capacity(
       db: AsyncSession = Depends(get_db),
       user: User = Depends(require_permissions("campaigns.read")),
   ) -> WhatsAppCapacityOut:
       try:
           return await get_send_capacity(db)
       except WhatsAppNotConnected as e:
           raise HTTPException(status_code=409, detail=str(e))
   ```

4. **Schema** `WhatsAppCapacityOut` (Pydantic v2 `BaseModel`) — mirrors the dict shape with explicit types.

5. **Angular service** — `WhatsappCapacityService`:
   - `capacity = signal<Capacity | null>(null)`
   - `loading = signal(false)`
   - `error = signal<string | null>(null)`
   - `load()` — GET `/api/v1/integrations/whatsapp/capacity`, sets signals.
   - Single instance via `providedIn: 'root'` so banner + picker + send button share the same fetch.

6. **Campaign create component** — inject the service, call `load()` in `ngOnInit`, render banner conditionally on `capacity()`, compute `selectionWarning` as a `computed()` derived from `capacity()` + selected count signal, gate the Send button via a `canSend = computed()`.

7. **Tier reset clock** — the banner's "resets at" tooltip uses local IST (Meta resets at 00:00 UTC = 05:30 IST). Hard-coded in the component because Indian-only product (CLAUDE.md confirms).

---

## Database changes

```sql
-- 0084_whatsapp_account_tier_cache.py — up
ALTER TABLE whatsapp_account_configs
  ADD COLUMN messaging_limit_tier TEXT NULL,
  ADD COLUMN tier_synced_at TIMESTAMPTZ NULL;

-- down
ALTER TABLE whatsapp_account_configs
  DROP COLUMN tier_synced_at,
  DROP COLUMN messaging_limit_tier;
```

No backfill — `NULL` is the "not yet fetched" state, and `get_send_capacity` will populate on first call.

No new index needed: `messages.sent_at` is already indexed via `ix_messages_conversation_created` for the join predicate, and the query is org-scoped by RLS before the date filter runs.

---

## Tests to add

`API/tests/test_whatsapp_capacity.py`:

1. **`test_tier_constants_complete`** — every Meta tier value has a matching entry in both `TIER_LIMITS` and `TIER_LABELS`. Guards against silent drift if Meta adds a new tier.
2. **`test_count_unique_recipients_24h_window`** — seed 3 conversations, send messages at `now`, `now - 23h`, `now - 25h`. Assert count is 2 (the 25h-old one drops out).
3. **`test_count_distinct_per_conversation`** — same conversation gets 5 outbound messages in last hour → counted once.
4. **`test_inbound_messages_excluded`** — inbound messages in same window don't bump the counter.
5. **`test_email_messages_excluded`** — only `channel='whatsapp'` conversations contribute.
6. **`test_tier_cache_hit`** — `tier_synced_at = now - 30min`, `_get_tier_cached` returns cached value without HTTP call (mock httpx, assert not called).
7. **`test_tier_cache_miss_refreshes`** — `tier_synced_at = now - 2h`, mock httpx returns `TIER_10K`, assert column updated and value returned.
8. **`test_tier_cache_first_fetch`** — both columns NULL, mock httpx, assert populated.
9. **`test_get_capacity_unlimited_branch`** — Meta returns `TIER_UNLIMITED`, assert `is_unlimited=True`, `remaining=-1`, `usage_percent=0`.
10. **`test_get_capacity_full_quota`** — `TIER_1K`, seed 1000 unique recipients, assert `remaining=0`, `usage_percent=100`.
11. **`test_get_capacity_not_connected`** — no integration row → `WhatsAppNotConnected` raised.
12. **`test_endpoint_permission_gate`** — user without `campaigns.read` → 403.
13. **`test_endpoint_returns_409_when_not_connected`** — service raises, router maps to 409.
14. **`test_endpoint_response_shape`** — all 7 fields present, types correct.

Angular: smoke test on the service (load → state populated) and on the warning thresholds (one each for safe / warning / error band) — Karma / Jasmine.

---

## Verification checklist

**Backend:**
- `uv run alembic upgrade head` → `0068` applies cleanly.
- `uv run alembic downgrade -1` → columns dropped, no errors.
- `uv run pytest tests/test_whatsapp_capacity.py -v` → all green.
- `uv run pytest` → no regressions in adjacent suites (templates, dispatch, rate-limit).
- Manual via Swagger: `GET /api/v1/integrations/whatsapp/capacity` with a connected org returns the seven fields; with a disconnected org returns 409 with the operator-friendly message.
- DB after one call: `SELECT messaging_limit_tier, tier_synced_at FROM whatsapp_account_configs WHERE org_id = '<demo>'` → populated.
- Re-call within 1 hour: `tier_synced_at` does not change (cache hit).

**Frontend:**
- Open `/user/campaigns/new` as Sales Executive → banner appears within 500 ms.
- Banner shows correct colour band as you mock different `usage_percent` values (DevTools override).
- Pick 10 contacts, banner unchanged; pick 100, warning appears if `remaining < 200`; pick more than `remaining`, red error appears.
- Send button is enabled in green/amber bands, disabled when `remaining === 0`.
- Tier `UNLIMITED`: banner hides the progress bar, shows "Unlimited messages today", warnings never fire.
- Disconnect WhatsApp in Settings → reload campaign page → banner shows a "Not connected" empty state (not a crash). (Already covered by the 409 handler in the service.)
- Refresh button re-fetches; spinner shows for the duration.

**End-to-end:**
- Run a 5-contact test campaign → `used_today` increments by 5 after delivery webhooks land. Refresh banner → reflects the new count.

---

## Self-check (10 rules)

- [ ] **Rule 1 (core ↛ packs):** All new code in `core/integrations/whatsapp/` + `features/user/core/campaigns/`. No furniture-pack imports.
- [ ] **Rule 2 (org_id + RLS):** New columns on existing TenantScoped table inherit `org_id`; the DISTINCT query goes through `Message` (TenantScoped) joined to `Conversation` (TenantScoped), so RLS scopes both sides automatically.
- [ ] **Rule 3 (custom fields):** N/A — no entity custom fields.
- [ ] **Rule 4 (dynamic forms):** N/A — fixed system data, not a user entity.
- [ ] **Rule 5 (sidebar registry):** N/A — no new menu.
- [ ] **Rule 6 (permission registry):** Endpoint uses existing `campaigns.read` permission; no new keys added.
- [ ] **Rule 7 (pack manifest):** N/A — core-only feature.
- [ ] **Rule 8 (step size):** ~8 files, well under budget. One concern (capacity), one screen.
- [ ] **Rule 9 (no skipped verification):** Stop and report after this step; await "proceed" before 3.5.17.
- [ ] **Rule 10 (no shortcuts):** No TODOs, no commented-out code, no hardcoded `daily_limit` magic numbers — everything flows from `TIER_LIMITS`. Plaintext token never leaves the decrypt call frame (matches `templates.sync_templates`'s contract).

---

## Stop & report

Report shape (matches the standard template):

- **Files changed:** list of created + modified paths.
- **What you can verify:** Swagger call, DB row, frontend banner screenshot (3 states), recipient picker warning screenshot.
- **Raw SQL** for the migration (`ALTER TABLE` up + down), so the user can apply it manually if they prefer.
- **Tests added:** 14 backend + 4 frontend.
- **Self-check:** the 10 boxes above.
- **Awaiting:** "proceed" before Step 3.5.17 (quality rating surfacing).

---

## Notes for future steps (not this one)

This step gives the agent **volume awareness**. The next natural step (3.5.17 — quality monitoring) would:

- Pull `quality_rating` from the same Meta endpoint (`fields=messaging_limit_tier,quality_rating`).
- Cache it in a new column `quality_rating` on `whatsapp_account_configs`.
- Surface a GREEN / YELLOW / RED dot in the same banner.
- Subscribe to Meta's `phone_number_quality_update` webhook for real-time changes.
- Auto-pause MARKETING campaigns when YELLOW/RED (per-org configurable).

Deliberately deferred — keeps this step shippable in under 30 minutes of review and doesn't pull in webhook subscription work that needs its own verification surface.
