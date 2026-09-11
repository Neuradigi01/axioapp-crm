# Step 11 — Frontend `/user/settings/api-keys` (Owner-only)

**Goal:** Owner-only Settings page: list keys, create modal (with `default_owner_user_id` picker, `auto_create_contacts` toggle, `hmac_required` toggle, `mode` selector), one-time reveal modal (copy-to-clipboard WITHOUT visible plaintext), rotate-with-grace with countdown, revoke.
**Phase:** Custom Events track — step 11/17
**Depends on:** Step 4
**Status:** Pending

## Scope

**In-scope:**
- Route `/user/settings/api-keys` (Owner-only, route guard).
- List page: table columns (Name, Prefix `pk_live_ab12...` last-4, Resource, Mode, `default_owner`, Created, Last used, Actions).
- Create modal:
  - Name.
  - Resource type dropdown (`events` / `lead_form` / `ai_assistant`).
  - Mode (`live` / `test`).
  - Owner picker for `default_owner_user_id` (users in org).
  - `auto_create_contacts` toggle (default true, disabled if mode=test with explanation).
  - `hmac_required` toggle (default true for events, false for embed/ai).
  - Rate limit input (default 100 for live, forced 20 for test).
- Reveal modal (post-create):
  - Shows secret `pk_live_...` ONCE.
  - **Copy-to-clipboard button — key never rendered as inline visible plaintext.** After copy, shows `pk_live_ab12...LAST4`. 5-minute in-memory countdown then clears from JS memory.
  - HMAC secret (if events key) — separate copy button, same one-time behavior. Non-revealable after modal close.
  - Big warning: "Save this now — it won't be shown again."
- Rotate action:
  - Confirm dialog "Old key will remain valid for 24h grace window."
  - Same reveal modal for new secret.
  - Grace-period countdown pill on the key row: "Old key expires in 23h 42m."
  - Force-purge-old button appears during grace with confirm dialog.
- Revoke action: confirm + hard delete + audit.
- Uses standard warning-banner pattern (amber, per project standard).

**Out of scope:**
- Custom-events list/detail (Step 12+).

## Files to touch
- `APP/src/app/features/user/core/settings/api-keys/list.page.ts/.html/.scss` (new).
- `APP/src/app/features/user/core/settings/api-keys/create-modal.component.ts/.html` (new).
- `APP/src/app/features/user/core/settings/api-keys/reveal-modal.component.ts/.html` (new — copy-only, no visible plaintext).
- `APP/src/app/features/user/core/settings/api-keys/api-keys.service.ts` (new).
- `APP/src/app/features/user/core/settings/settings.routes.ts` (modified — register route with Owner guard).

## Plan
1. List page + service.
2. Create modal.
3. Reveal modal with copy-only + countdown.
4. Rotate + grace pill + force-purge.
5. Revoke.
6. Playwright.

## Tests to add
- Component specs.
- Playwright: create key → reveal modal shows once; second visit shows only last-4.
- Playwright: HMAC secret revealed once; never re-revealable.
- Playwright: rotate → old-key countdown visible for 24h.
- Playwright: force-purge clears old_key.
- Playwright: non-Owner navigates → 403 route guard.

## Verification checklist
- Frontend: prettier + eslint clean per project convention (`npx --no-install prettier --write` before commit).
- Frontend: manual create + reveal + rotate flows.

## Self-check
- [ ] Rule N/A / clean.
- [ ] Rule 8: ~7 files.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
