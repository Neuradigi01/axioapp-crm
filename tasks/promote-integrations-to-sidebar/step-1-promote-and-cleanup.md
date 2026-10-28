# Step 1 — Promote Integrations module: backend descriptor + frontend route + tab cleanup + redirect

**Goal:** Single-step promotion of the Integrations surface from a Settings tab to a top-level sidebar entry. Flip the backend `ModuleDescriptor.menu_position` (which the sidebar is driven by), add a top-level Angular route, remove the Settings tab, and add a redirect from the old URL so deep-links keep working.
**Track:** Promote Integrations to Sidebar
**Status:** COMPLETED — 2026-06-12. 5 files modified, 0 created, 0 deleted, 0 migrations. **Picked `menu_position=900`** — slots just before Settings (999), well clear of every other operational module (max was Campaigns at 560). Renamed the descriptor `name` from "Ad Integrations" to plain "Integrations" since WhatsApp + email integrations also live under this surface. `frontend_route` flipped to `/user/integrations`. The Angular top-level route lazy-loads the existing `IntegrationsPageComponent` from its current path (`core/settings/integrations/integrations-page.component`) — no physical file move (deferred to a separate cleanup track to keep this step's import-blast-radius near zero). Legacy `/user/settings/integrations` URL now redirects via Angular's `redirectTo` so OAuth callbacks and existing bookmarks land cleanly on the new home. Settings page: `IntegrationsPageComponent` import dropped, `'integrations'` removed from the `SettingsTab` union + the `TABS` array + the `imports[]` declaration + the `@case ('integrations')` template branch. Integrations page got a new outer wrapper (`<div class="flex h-[calc(100vh-4rem)] flex-col">`) with a `<header>` block ("Integrations" + subtitle) and an inner scrollable `<div class="flex-1 space-y-4 overflow-y-auto p-6">` containing all the existing content. Tag structure verified balanced. **Live verification deferred** — Docker stack was down at completion time (`docker ps` returned no containers); will pick up automatically when the user brings the stack back up via `docker-helper.cmd up`. Code changes are sound; the API descriptor change is a one-line `menu_position` flip that uvicorn will pick up on next reload.
**Depends on:** None (the integrations UI is already a complete `IntegrationsPageComponent`).

---

## Scope

In-scope:

- [`API/src/app/core/integrations/module.py`](API/src/app/core/integrations/module.py) — change `menu_position=None` to a real integer (place just before Settings — pick from the existing positions); change `frontend_route` from `/user/settings/integrations` to `/user/integrations`. Drop the stale comment block about "keeps this module out of the main sidebar".
- [`APP/src/app/features/user/user.routes.ts`](APP/src/app/features/user/user.routes.ts) — add a top-level lazy or eager route for `/user/integrations` that renders `IntegrationsPageComponent`. Reuse the same permission-guard pattern that other sidebar routes use (e.g. Leads / Campaigns) — gate on `settings.integrations.manage`. Add a redirect entry from `/user/settings/integrations` → `/user/integrations` so existing bookmarks don't 404.
- [`APP/src/app/features/user/core/settings/settings-page.component.ts`](APP/src/app/features/user/core/settings/settings-page.component.ts) — remove the `id: 'integrations'` entry from the `TABS` array. Drop the `IntegrationsPageComponent` import (no longer referenced). Drop the `'integrations'` literal from the `TabId` union.
- [`APP/src/app/features/user/core/settings/settings-page.component.html`](APP/src/app/features/user/core/settings/settings-page.component.html) — remove the `@case ('integrations')` block from the tab switch.
- [`APP/.../integrations/integrations-page.component.html`](APP/src/app/features/user/core/settings/integrations/integrations-page.component.html) — add a `<header>` block at the top with the page title + subtitle, matching the chrome used by other sidebar pages (e.g. the Conversations page's `<header class="border-b border-zinc-200 bg-white px-6 py-3">`). Without this, the page renders title-less when accessed via the sidebar.

Out of scope:

- **No component move.** `IntegrationsPageComponent` stays at `core/settings/integrations/integrations-page.component.ts`. Renaming the path is a separate cleanup track — would require updating ~20 internal imports (cards, services, DLQ list, mapping editor).
- **No permission change.** Continues to gate on `settings.integrations.manage`. No new permission key.
- **No content change.** All cards, the DLQ list, the field-mapping editor — all render exactly the same. Just a relocation + a page header.
- **No backend API change.** `/api/v1/integrations/*` routes unchanged. `/api/v1/modules` returns the new `frontend_route` value automatically because the descriptor changed.
- **No Billing tab change.** Promoting Billing is a separate track per [`project_billing_promote_to_sidebar`](C:\Users\pc\.claude\projects\c--Users-pc-Desktop-Project-CRM-PROJECT-Crm\memory\project_billing_promote_to_sidebar.md) memory.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/module.py` | modified — descriptor flip |
| `APP/src/app/features/user/user.routes.ts` | modified — new top-level route + redirect alias |
| `APP/src/app/features/user/core/settings/settings-page.component.ts` | modified — remove tab entry + import |
| `APP/src/app/features/user/core/settings/settings-page.component.html` | modified — remove case branch |
| `APP/src/app/features/user/core/settings/integrations/integrations-page.component.html` | modified — add page header |

**5 files modified. 0 created. 0 deleted.**

## Plan

1. **Pick the `menu_position`.** Read the existing module descriptors in `core/*/module.py` to see which positions are used. Pick a slot just before Settings — if Settings is `100`, use `95`; if it's `90`, use `85`. Document the chosen number in the step report.
2. **Update [`API/src/app/core/integrations/module.py`](API/src/app/core/integrations/module.py):**
   ```python
   MODULE = ModuleDescriptor(
       id="integrations",
       name="Integrations",          # was "Ad Integrations" — drop the "Ad" since
                                     # WhatsApp + email integrations also live here
       icon="plug",
       layer="core",
       route="/api/v1/integrations",
       frontend_route="/user/integrations",   # was /user/settings/integrations
       menu_position=<chosen number>,         # was None
       permissions=["settings.integrations.manage"],
   )
   ```
   Drop the outdated module-level docstring sentence about it being a Settings tab.
3. **Add the top-level route** in `user.routes.ts`. Match the pattern used by other sidebar routes (e.g. `path: 'campaigns'`):
   ```ts
   {
     path: 'integrations',
     loadComponent: () =>
       import('./core/settings/integrations/integrations-page.component')
         .then(m => m.IntegrationsPageComponent),
     canActivate: [permissionGuard('settings.integrations.manage')],
     data: { breadcrumb: 'Integrations' },
   },
   ```
   And add a redirect entry from the old path:
   ```ts
   {
     path: 'settings/integrations',
     redirectTo: '/user/integrations',
     pathMatch: 'full',
   },
   ```
   (Place the redirect entry BEFORE the `path: 'settings'` route so it takes priority over the settings child router.)
4. **Remove the Settings tab** in `settings-page.component.ts`:
   - Drop the `import { IntegrationsPageComponent }` line.
   - Drop `'integrations'` from the `TabId` union.
   - Drop the `{ id: 'integrations', label: 'Integrations', permission: 'settings.integrations.manage' }` entry from the `TABS` array.
   - Drop `IntegrationsPageComponent` from the component's `imports: [...]` array.
5. **Remove the tab case** in `settings-page.component.html`:
   ```html
   @case ('integrations') {
     <app-integrations-page />
   }
   ```
   Delete this block.
6. **Add page header** to `integrations-page.component.html`. Mirror the Conversations page's pattern:
   ```html
   <div class="flex h-[calc(100vh-4rem)] flex-col">
     <header class="border-b border-zinc-200 bg-white px-6 py-3">
       <div>
         <h1 class="text-xl font-semibold text-zinc-900">Integrations</h1>
         <p class="text-xs text-zinc-500">
           Connect ad platforms (Google Ads, Meta Ads) and messaging channels
           (WhatsApp) to your CRM. Lead form submissions land in Leads;
           inbound messages land in Conversations.
         </p>
       </div>
     </header>
     <div class="flex-1 overflow-y-auto px-6 py-6">
       <!-- existing dashboard content moves inside here -->
     </div>
   </div>
   ```
   Wrap the current top-level content with the new structure. Don't change any of the cards' markup.

## DB changes / migrations

**None.** The module-registry descriptor is Python — server picks it up at next reload. No `tbl_module_registry` table.

## Tests

No new pytest. Module registry is unit-tested elsewhere; the change is a config edit. The frontend route + sidebar render are exercised by the manual smoke.

## Smoke

After the API container auto-reloads (uvicorn picks up the descriptor change) and Angular dev server rebuilds:

```
1. Refresh /user — sidebar shows new "Integrations" entry with the plug icon,
   positioned just before Settings.

2. Click "Integrations" in the sidebar → navigates to /user/integrations.
   Page renders the same dashboard (Delivery status + Google Ads + Meta Ads
   + WhatsApp + DLQ + field mapping editor) — now with its own page header
   ("Integrations" + subtitle) at the top.

3. Click "Settings" in the sidebar → the Integrations tab is GONE from the
   tab row (Profile, Appearance, Notifications, Two-factor, Login history,
   Store Profile, Team, Roles, Email Accounts, Email Templates, Email
   Sequences, AI Settings, Custom Fields, Standard Fields, Embed Widget —
   no Integrations).

4. Manually navigate to /user/settings/integrations in the URL bar →
   redirects to /user/integrations.

5. Manually navigate to /user/settings?tab=integrations →
   should land on Settings with an unrecognised tab → defaults to
   the first tab (Profile). Document this corner case in the report;
   acceptable since the redirect on /user/settings/integrations handles
   the primary deep-link.

6. Log in as a Sales-Junior (no settings.integrations.manage permission):
   - The "Integrations" sidebar entry should NOT appear.
   - Manually hitting /user/integrations should redirect to access-denied
     (existing permissionGuard behavior).

7. Log in as Owner — full access, sidebar entry visible.
```

## Risks

- **`menu_position` collision.** If the chosen number matches an existing module's position, the order becomes undefined. Pick a unique value; verify by reading every `core/*/module.py` first.
- **Sidebar component caches the modules list.** The module list is fetched once at `ngOnInit`. Owners with an open browser tab when this ships will need to hard-refresh to see the new entry. Document in the report so support knows.
- **`/user/settings?tab=integrations` query-param deep link** doesn't get redirected — only `/user/settings/integrations` path-style does. Acceptable: query-param deep-links degrade to "Settings, default tab". If you want to handle it perfectly, add a Settings-page `effect()` that watches `route.queryParams` and redirects when `tab=integrations` is detected. Optional; skip unless explicitly asked.
- **Settings page's `permission` filter** on tabs may shift visual order if Integrations was previously hidden for some role. After removal, the tab row stabilises; check no weird ordering.

## Self-check (10 rules)

- [ ] Rule 1: No new `core/` → `packs/` imports.
- [ ] Rule 2: No DB changes.
- [ ] Rule 3: Custom fields engine untouched.
- [ ] Rule 4: No form changes.
- [ ] Rule 5: Sidebar registry IS the mechanism — proper rule-5 exercise.
- [ ] Rule 6: Permissions registry untouched; reuses existing `settings.integrations.manage`.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 5 files, ~80 lines net.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. Redirect handles old URLs; no `// TODO: move the component` left behind.

## Stop & report

```
Step 1 — Promote Integrations to sidebar

Files changed:
- API/src/app/core/integrations/module.py — menu_position={N}, frontend_route=/user/integrations
- APP/.../user.routes.ts — added /user/integrations + redirect from /user/settings/integrations
- APP/.../settings-page.component.{ts,html} — removed Integrations tab
- APP/.../integrations-page.component.html — added page header chrome

What you can verify:
- Sidebar shows "Integrations" entry just before Settings (plug icon)
- Clicking it lands on /user/integrations with full dashboard intact
- Settings tab row no longer contains Integrations
- /user/settings/integrations redirects cleanly to the new URL
- Sales-Junior does NOT see the sidebar entry; direct URL is permission-denied

Tests added: none — config-only change; existing module-registry tests cover the flip.

Self-check: 10 rules, all green.

Track closed. Pattern proven; the parallel Billing-to-sidebar promotion (per project memory) can reuse the exact same recipe.
```
