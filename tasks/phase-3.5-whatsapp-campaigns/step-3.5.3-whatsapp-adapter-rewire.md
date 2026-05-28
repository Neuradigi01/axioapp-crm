# Step 3.5.3 — Adapter rewire: outbound WhatsApp loads per-org config from DB

**Goal:** Outbound WhatsApp `send` uses each org's encrypted token from the `integrations` table (Step 3.5.1), not the shared `.env` value. Inbound webhook stays on env-var fallback until Step 3.5.12 (separate scope — webhook routing by `phone_id` lookup).

**Phase:** 3.5 (WhatsApp Campaigns)
**Depends on:** 3.5.1 (DB schema + connect service), 3.8 (channel registry)
**Status:** ✅ COMPLETED — commit `d332113`

After this step:
- Owner clicks Connect → DB row + sidecar saved with encrypted token
- Operator triggers a campaign or replies in inbox → backend reads THAT org's row, decrypts the token, sends via Meta with the org's own number
- Different orgs use different WhatsApp numbers in the same deployment (true multi-tenant SaaS behavior)

What stays unchanged (intentionally):
- Inbound webhook (`POST /webhooks/whatsapp`) — still uses env-var fallback for signature verification. Migrating it requires looking up the org by `phone_id` from Meta's payload, which is the body of work in Step 3.5.12. Keeping it on env-var for now is documented design, not a TODO.

---

## Scope

### In-scope

- New `WhatsAppNotConnected` exception in `conversations/adapters/whatsapp.py`.
- New async helper `resolve_whatsapp_adapter_for_org(session, org_id)` in the same module:
  - Calls `integrations.whatsapp.connect.get_active_config(session)` (relies on the active tenant filter — the helper inherits org isolation from RLS / ORM filter).
  - Returns a fully-configured `WhatsAppAdapter` if the org has a `connected` Integration row with sidecar populated.
  - Raises `WhatsAppNotConnected` with a clear message if the org isn't connected (caller surfaces as 409 to the API).
  - Decrypts `access_token_enc` + `app_secret_enc` via the existing `integrations.crypto` helpers. Plaintext lives only inside the returned adapter instance — never logged, never returned to the API surface.
- Modify outbound call sites:
  - `conversations/service.py:145` (send_outbound path) — for `ConversationChannel.whatsapp` use the per-org resolver; other channels keep using the registry's `resolve(channel)`.
  - `campaigns/service.py:420` (`dispatch_chunk` path) — same channel-conditional dispatch.
- Clarify docstring on `register_default_whatsapp_adapter` to document its restricted role (inbound webhook fallback, not outbound). NOT removing the function — webhook still needs it until Step 3.5.12.
- Tests:
  - `tests/test_whatsapp_account_connect.py::TestResolveAdapter::test_returns_configured_adapter_when_connected`
  - `tests/test_whatsapp_account_connect.py::TestResolveAdapter::test_raises_when_disconnected`
  - `tests/test_whatsapp_account_connect.py::TestResolveAdapter::test_raises_when_never_connected`
  - `tests/test_whatsapp_account_connect.py::TestResolveAdapter::test_adapter_uses_decrypted_token`

### Out-of-scope (deferred)

- **Webhook signature verification per-org** → Step 3.5.12 (`whatsapp_account_configs` lookup by `phone_id` from Meta payload).
- **Template send (`send_template`)** → Step 3.5.4 (after template sync is wired).
- **Rate limit per-org** → Step 3.5.15.
- Dropping env-var WhatsApp config entirely — happens organically when Step 3.5.12 lands (the webhook is the last consumer); not done in this step to keep the scope tight and reviewable.
- Tests for the modified outbound call sites in conversations/campaigns services — those already have existing tests; new behavior is exercised via the resolver tests + the adapter tests. Adding more coverage there is overkill for this step.

---

## Files to touch

### Modified (3 files)

- `API/src/app/core/conversations/adapters/whatsapp.py` — add exception + resolver (~50 lines), tighten docstring on `register_default_whatsapp_adapter`.
- `API/src/app/core/conversations/service.py` — add channel-conditional resolver lookup before line 145's `resolve(conv.channel)` (~8 lines).
- `API/src/app/core/campaigns/service.py` — same conditional before line 420's adapter usage (~8 lines).
- `API/tests/test_whatsapp_account_connect.py` — add `TestResolveAdapter` class (~80 lines).

**File budget:** 4 files. Well within ≤10.

---

## Plan

1. **`adapters/whatsapp.py`:**
   - Add `class WhatsAppNotConnected(Exception)`.
   - Add `async def resolve_whatsapp_adapter_for_org(session, org_id)`:
     - Calls `get_active_config(session)` from `integrations.whatsapp.connect`.
     - On `None` → raises `WhatsAppNotConnected`.
     - On hit → `crypto.decrypt(integration.access_token_enc)`, `crypto.decrypt(config.app_secret_enc)`, constructs `WhatsAppAdapter(phone_id=…, token=…, app_secret=…, verify_token=…, api_version=…)` with the org's values, returns it.
   - Update `register_default_whatsapp_adapter`'s docstring to make clear it's now an inbound-only fallback until Step 3.5.12.
2. **`conversations/service.py`:**
   - In the send path (around line 145), before `resolve(conv.channel)`, add:
     ```python
     if conv.channel == ConversationChannel.whatsapp:
         adapter = await resolve_whatsapp_adapter_for_org(session, conv.org_id)
     else:
         adapter = resolve(conv.channel)
     ```
3. **`campaigns/service.py`:**
   - In `dispatch_chunk` (around line 420), same conditional. Use `campaign.org_id`.
4. **Tests:**
   - Reuse the `_CapturingSession` + `_existing_connected_pair` fixtures from Step 3.5.1's test file.
   - Test that the returned adapter has the decrypted plaintext token in `_token`.
   - Test that calling `resolve_whatsapp_adapter_for_org` on a disconnected org raises `WhatsAppNotConnected`.

---

## Verification checklist

**Build + tests:**
1. `docker exec template_api-api-1 pytest tests/test_whatsapp_account_connect.py -v` → all tests pass (4 new + 10 existing = 14 total).
2. `docker exec template_api-api-1 pytest tests/ -k whatsapp -v` → no regressions in any whatsapp-touching tests.

**Smoke (when you have real Meta test creds):**
3. Connect WhatsApp via UI from Step 3.5.2 (Owner → /user/settings/integrations).
4. Open a conversation with a test contact → send a text message via the inbox.
5. Confirm Meta delivers the message FROM your connected number (not the dev fallback).
6. Disconnect via UI.
7. Try sending again → 409 "WhatsApp is not connected for this org. Connect it in Settings → Integrations."
8. Reconnect → outbound resumes.

**No regression:**
9. Existing conversations endpoints unaffected.
10. Campaigns dispatch still works (per existing tests in `tests/test_campaigns_*`).

---

## Self-check against 10 rules

- [x] **Rule 1:** `core/conversations` imports `core/integrations.whatsapp.connect` — both in core/, no pack crossing.
- [x] **Rule 2:** N/A (no new tables).
- [x] **Rule 3:** Custom fields untouched.
- [x] **Rule 4:** N/A.
- [x] **Rule 5:** Sidebar untouched.
- [x] **Rule 6:** No new permission keys.
- [x] **Rule 7:** N/A (core).
- [x] **Rule 8:** 4 files, ~140 lines total changes.
- [x] **Rule 9:** Stop & report after implementation.
- [x] **Rule 10:** Env-var path retained for inbound webhook is documented design (with reason: webhook arrives without org context until phone_id lookup in 3.5.12), NOT a TODO. Outbound is fully clean — no fallback, no env-var.

---

## Stop & report

After completing this step I will:
- List exact files changed with one-line each.
- Show 4 new resolver tests + all 10 existing WA tests passing.
- Show the conditional dispatch diff in conversations + campaigns services.
- **Await your "proceed" before Step 3.5.4 (Template sync — `whatsapp_templates` table + Meta `/message_templates` fetch).**

---

## Pre-implementation question (one only)

**Q: Per-org adapter ko cache karein ya har send pe DB lookup karein?**

- **(a) No cache — DB lookup every send.** Simple, safe, ~10ms latency hit per send (DB index hit on `Integration` table). Recommended for v1 — token rotation kicks in immediately, no cache invalidation needed.
- **(b) In-memory LRU cache.** Per `(org_id, integration_updated_at)` key, ~100-entry cache. Faster but requires invalidation when operator reconnects.

**Recommendation: (a)** — premature optimization warning. Outbound send already has ~150ms latency to Meta; an extra ~10ms DB lookup is noise. Caching adds complexity (when to invalidate, what about expired tokens, what about multi-worker setup) without measurable benefit at this scale.

Aap **(a) ya (b)** batao, fir **"begin"** bolo → mai implement karta hoon.
