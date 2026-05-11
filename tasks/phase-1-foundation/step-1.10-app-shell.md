# Step 1.10 — App shell (sidebar + header)

**Goal:** Build the layout shell matching the screenshots — dark collapsible sidebar driven by `GET /api/v1/modules`, top header with search input, notification bell (placeholder), user dropdown. Routing skeleton in place. Pure Tailwind.
**Phase:** 1
**Depends on:** 1.8, 1.9
**Status:** Pending

## Scope
**In-scope:**
- `app/src/app/features/user/core/layout/shell.component.ts` — top-level layout: sidebar + header + `<router-outlet>`.
- `app/src/app/features/user/core/layout/sidebar.component.ts` — fetches modules via `ModuleApiService`, renders icon + name list. Collapsible (signal-based open/closed state, persisted to localStorage).
- `app/src/app/features/user/core/layout/header.component.ts` — search input (placeholder), bell icon (badge="0"), user dropdown (logout link).
- `app/src/app/features/user/core/services/module-api.service.ts` — `list(): Observable<ModuleDescriptorOut[]>`.
- Icons via `lucide-angular` or inline SVG components (decision: lucide-angular; `npm i lucide-angular`).
- Routes: `/` shell wraps everything; child routes lazy-load module-specific pages (only `/settings` stub for now → `app/core/settings/settings-page.component.ts`).
- Dark theme by default for sidebar (Tailwind `bg-zinc-900 text-zinc-100`); main content light.
- Responsive: sidebar collapses to icon-only at < md breakpoint.

**Out of scope:**
- Real notifications — Phase 2.
- Search backend wire-up — Phase 6.
- User profile page — later.

## Files to touch
- `app/src/app/features/user/core/layout/shell.component.ts` (created)
- `app/src/app/features/user/core/layout/shell.component.html` (created)
- `app/src/app/features/user/core/layout/sidebar.component.ts` (created)
- `app/src/app/features/user/core/layout/sidebar.component.html` (created)
- `app/src/app/features/user/core/layout/header.component.ts` (created)
- `app/src/app/features/user/core/layout/header.component.html` (created)
- `app/src/app/features/user/core/services/module-api.service.ts` (created)
- `app/src/app/features/user/core/settings/settings-page.component.ts` (created — stub "Settings (coming soon)")
- `app/src/app/app.routes.ts` (modified — add shell wrapper, child routes)
- `app/package.json` (modified — `lucide-angular`)

## Plan
1. Install `lucide-angular`. Configure provider in `app.config.ts`.
2. Build the shell shell: signals for `sidebarOpen` + `currentUser`. Layout with `<aside>` + `<main>` flexbox.
3. Sidebar: on init, call `moduleApi.list()` → signal of modules. Render `@for (m of modules(); track m.id)` with icon + name; clicking navigates to `m.frontend_route`.
4. Header: search input (no submit handler yet), bell icon with `0` badge, user dropdown with username + logout button.
5. Settings stub page: just a heading "Settings".
6. Routes: parent route `''` → shell, children: `''` → home (Welcome), `'settings'` → settings stub.
7. Persist sidebar collapsed state to localStorage.
8. Tailwind: dark sidebar, light main area, sticky top header with subtle shadow. Match the screenshot styling on classes.
9. Verify mobile responsiveness at 375px wide (sidebar becomes icon-only or hidden behind hamburger).

## DB changes / migrations
None.

## Tests to add
- None (skipTests).
- Manual smoke test described in checklist.

## Verification checklist
**Frontend:**
- visit: `http://localhost:4200/` after login → shell renders with sidebar (Settings entry) and header.
- click Settings → routes to `/settings`, "Settings (coming soon)" heading.
- toggle sidebar → state persisted on reload.
- network: `GET /api/v1/modules` returns 200 with at least Settings.
- responsive: at 375px wide, sidebar is icon-only or hamburger-toggled.

**Code review:**
- open `sidebar.component.ts` — note modules come from API, not hardcoded.
- open `app.routes.ts` — note shell wraps `/`, accounts routes are siblings (NOT inside shell).

## Self-check (10 rules)
- [ ] Sidebar driven by registry endpoint (rule 5).
- [ ] No imports from `packs/`.
- [ ] No hardcoded module list.
- [ ] Step ≤ ~10 files.

## Stop & report
Use the master-prompt stop template; this concludes **Phase 1**. Await "proceed" before Step 2.1.
