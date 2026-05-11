# Step 3.17 — Settings module: backend + frontend

**Goal:** Settings page with Store Profile, Team, Integrations, Notifications preferences, AI Settings tabs. Build them small, one at a time.
**Phase:** 3
**Depends on:** 2.2 (custom-fields tab already there), 1.6
**Status:** Pending

## Scope
**In-scope:**
- Backend:
  - Model `OrgSettings` (TenantScoped, single row per org): currency, tax_rate, timezone, locale, gst_number, address fields, logo_url, ai_enabled, ai_personality, ai_welcome_message, reviews_auto_request_enabled, reviews_auto_request_delay_hours.
  - Migration + RLS.
  - Endpoints: `GET /api/v1/settings`, `PATCH /api/v1/settings` (gated by `settings.write`).
- Frontend tabs (split into sub-tabs in the existing Settings page from 2.2):
  - Store Profile (logo, name, GST, address, timezone, currency, tax_rate).
  - Team (list users, invite — invite endpoint stub here, full flow later).
  - Integrations (placeholder list — WhatsApp connection status, Marketplace connections come in Phase 5).
  - Notifications (per-user notification preferences from 2.15).
  - AI Settings (personality + welcome message + auto follow-up toggles — Phase 5 reads these).
  - Custom Fields (already added in 2.2).
- Tailwind for the new tabs; existing Custom Fields tab stays as-is.

## Files to touch
- `api/src/app/core/settings/{models,schemas,service,router}.py` (created)
- `api/alembic/versions/0022_org_settings.py` (created)
- `app/src/app/features/user/core/settings/settings-page.component.ts/.html` (modified — add 5 sub-tabs)
- `app/src/app/features/user/core/settings/tabs/*` (created — 5 tab components)
- `app/src/app/features/user/core/settings/settings-api.service.ts` (created)

## Plan
1. Create model + migration; on org install, ensure single row inserted (handled in pack installer 4.1/4.2 too).
2. Endpoints with strict allowed-keys patch.
3. Each frontend tab: small reactive form, save patches `/settings`.

## Tests to add
- `tests/test_settings_patch.py` — only allowed keys mutate; non-admin → 403.

## Verification checklist
**Backend:**
- `GET /settings` → JSON.
- `PATCH /settings` body=`{tax_rate:18}` → 200.
**Frontend:**
- visit `/settings` → 6 tabs (Custom Fields + 5 new).
- update store profile → reflects.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] No furniture-specific defaults hardcoded; pack installer (4.2) seeds them via manifest.

## Stop & report
This concludes **Phase 3**. Await "proceed" before Step 4.1.
