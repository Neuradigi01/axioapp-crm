# Promote Integrations to Sidebar

A tiny one-step track that promotes the **Integrations** module from a tab inside Settings to a **top-level sidebar entry**, matching the convention used by every other major module (Contacts, Leads, Campaigns, Billing, etc.).

## Why this exists

Today, the Integrations surface lives at `/user/settings/integrations` — a tab inside the Settings page. The actual content (Google Ads card, Meta Ads card, WhatsApp card, DLQ list, field-mapping editor, integration status, delivery counters) is a full multi-card dashboard that doesn't really belong as a "settings tab" — it's a daily-use surface for any org running ad campaigns:

- The delivery-status row (success / failed counters, last delivery time) is what an owner checks every morning.
- The DLQ list ("3 deliveries need attention") needs to be one click away, not buried under Settings.
- The Reconnect button (Google Ads expired) is a *recovery action*, not a settings tweak.

Burying this under Settings makes it feel like "configure once, ignore", when in reality it's a live operations surface.

The architectural fix is trivial because the sidebar is **registry-driven** (rule 5): backend [`ModuleDescriptor`](API/src/app/core/module_registry.py#L42) controls whether a module shows in the sidebar via the `menu_position` field. [`core/integrations/module.py:22`](API/src/app/core/integrations/module.py#L22) currently sets `menu_position=None` with the explicit comment "keeps this module out of the main sidebar — it lives as a tab inside Settings → Integrations". This track flips that single decision.

## What this does NOT do

- **Does not move the component physically.** The integrations UI stays at `APP/src/app/features/user/core/settings/integrations/*` for this track — moving the ~15 files + updating ~20 cross-imports is a separate cleanup track. Frontend routing just points at the existing path.
- **Does not change permissions.** Continues to gate on `settings.integrations.manage` (Owner + Admin role templates already have it). Doesn't add a new permission key.
- **Does not change API contracts.** No backend routes added or removed.
- **Does not change the integrations dashboard content.** Cards, DLQ, status — all unchanged. Pure relocation + page-header chrome.
- **Does not touch the Billing tab.** A similar Billing promotion is already specced in [`feedback_billing_promote_to_sidebar`](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\project_billing_promote_to_sidebar.md) memory and would be its own track if/when prioritised.

## Acceptance criteria

After the one step lands:

1. The left sidebar shows a new entry **"Integrations"** with the `plug` icon, positioned just before **Settings**.
2. Clicking it navigates to `/user/integrations` and renders the existing integrations dashboard (Delivery status + Google Ads + Meta Ads + WhatsApp + DLQ + field-mapping editor — everything that was previously in the tab).
3. The page has its own header chrome ("Integrations" title + subtitle) matching the styling of other sidebar pages — not the settings-page chrome.
4. Settings → Integrations tab is **removed** (no longer in the Settings tabs row).
5. Old URLs `/user/settings/integrations` and `/user/settings?tab=integrations` **redirect** to `/user/integrations` (so any deep-links or bookmarks keep working).
6. Permission gating unchanged: roles without `settings.integrations.manage` (currently Employee templates) do NOT see the sidebar entry and get redirected from `/user/integrations` if they hit the URL directly.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Promote Integrations module — backend descriptor + frontend route + tab cleanup + redirect](step-1-promote-and-cleanup.md) | **COMPLETED** — 5 files, menu_position=900, live verify deferred to stack restart | ~2 hrs |

**Total: ~2 hours.** Single-step track because the surface is so small.

## File budget

| File | Why |
|---|---|
| `API/src/app/core/integrations/module.py` | Flip `menu_position=None` → a real number (e.g. 95, just before Settings's position); update `frontend_route` from `/user/settings/integrations` → `/user/integrations`. |
| `APP/src/app/features/user/user.routes.ts` | Add top-level route `/user/integrations` with the existing `IntegrationsPageComponent` + permission guard. Add the redirect alias from `/user/settings/integrations` → `/user/integrations`. |
| `APP/src/app/features/user/core/settings/settings-page.component.ts` | Remove the `'integrations'` entry from the `TABS` array. Drop the `IntegrationsPageComponent` import. |
| `APP/src/app/features/user/core/settings/settings-page.component.html` | Remove the `@case ('integrations')` branch from the tab switch. |
| `APP/.../integrations/integrations-page.component.html` | Add a `<header>` block at the top with the "Integrations" title + subtitle (currently it renders without one because the settings page provided the chrome). |

**5 files modified. 0 created. 0 deleted.** Within rule-8 budget.

## Dependencies

- Backend module registry — already in place ([`core/module_registry.py`](API/src/app/core/module_registry.py)).
- Frontend sidebar — already registry-driven ([`core/layout/sidebar.component.ts`](APP/src/app/features/user/core/layout/sidebar.component.ts)).
- Integrations page — already a complete dashboard component, just lacks its own page chrome.

## Self-check against the 10 rules

- ✅ Rule 1: All changes in `core/integrations` (backend) + frontend layout / settings. No `core/` → `packs/` imports added.
- ✅ Rule 2: No DB changes; no schema touched.
- ✅ Rule 3: Custom fields engine unaffected.
- ✅ Rule 4: No new form fields.
- ✅ Rule 5: **Sidebar registry is the mechanism** — flipping `menu_position` is exactly how the rule is designed to be exercised. No hardcoded sidebar additions.
- ✅ Rule 6: Permissions registry untouched. Continues to use `settings.integrations.manage`.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 5 files modified, ~80 lines net.
- ✅ Rule 9: Single step; stop and report.
- ✅ Rule 10: No TODOs. Redirect handles old URLs cleanly; no half-implemented half-broken state.

## What this enables (after it lands)

- Integrations becomes a first-class daily-use surface, not a buried config tab.
- The pattern is now proven for the parallel Billing promotion (the [billing-to-sidebar memory](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\project_billing_promote_to_sidebar.md) would follow the exact same recipe: flip `menu_position`, add top-level route, remove Settings tab).
- Settings page sheds one tab → less cluttered → easier to find the actually-settings-y things (Profile, Appearance, Two-factor, etc.).

## What's still NOT on the sidebar (intentionally)

These stay as Settings tabs because they ARE actual settings (configure-once, rarely revisit):

- Profile, Appearance, Notifications, Two-factor, Login history
- Store Profile, Team, Roles
- Email Accounts, Email Templates, Email Sequences
- AI Settings, Custom Fields, Standard Fields
- Embed Widget

Integrations and (future) Billing are the only two surfaces that look like settings but behave like operations — that's why they earn sidebar entries.
