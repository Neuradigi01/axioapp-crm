# Step 12 — Frontend sidebar entry + chatbots list page + folders + duplicate/clone

**Goal:** Wire the sidebar entry and ship the list page at `/user/chatbots` with folders, filters, and the standard CRUD actions.
**Depends on:** Step 3 (backend router)
**Status:** Pending

## Scope

**In-scope**
- Angular route `/user/chatbots` (list) — permission-guarded by `chatbots.view`.
- Sidebar entry wired via existing module-registry consumer.
- `chatbots-list.component.*` — list with folders sidebar, category filter, status filter, search, sort.
- Row actions: Edit, Duplicate, Rename, Move to folder, Export JSON, Archive, Delete.
- Empty state with "Create your first bot" + "Clone from a template" CTAs.
- `chatbots-api.service.ts` — HTTP client for the Step 3 endpoints.
- Standard TailwindCSS + signals + typed reactive forms (per repo stack).

**Out of scope**
- Builder page — Step 13.
- Node components — Step 14.
- Import JSON dialog — Step 15.

## Files to touch

- `APP/src/app/features/user/core/chatbots/chatbots.routes.ts` (created)
- `APP/src/app/features/user/core/chatbots/chatbots-api.service.ts` (created)
- `APP/src/app/features/user/core/chatbots/list/chatbots-list.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/list/chatbots-list.component.html` (created)
- `APP/src/app/features/user/core/chatbots/list/folder-tree.component.ts` (created)
- `APP/src/app/features/user/core/chatbots/list/row-actions-menu.component.ts` (created)
- `APP/src/app/features/user/user.routes.ts` (modified — lazy-load chatbots.routes)
- `APP/src/app/features/user/layout/sidebar/sidebar.component.ts` (modified — consumes module-registry, already done — verify chatbots entry renders)

## Plan

1. Sidebar wiring — verify the module-registry consumer picks up the new chatbots entry from Step 3. If not, add the manual entry (icon: `bot`, label: `Chat Bots`, route: `/user/chatbots`, badge: `NEW` for 30 days).
2. `chatbots-api.service.ts` — `list`, `get`, `create`, `update`, `publish`, `pause`, `archive`, `delete`, `duplicate`, `versions`, `rollback`, `save-targets` — all typed against the backend schemas.
3. `chatbots-list.component`:
   - Header: page title + Create button + Import button.
   - Left rail: folders tree + "New folder" + "All bots" + "Templates" + "Archived" filters.
   - Filter bar: category chip filter (Marketing / Sales / Support / Custom), status filter (Draft / Live / Paused).
   - Table columns: name (clickable → builder), trigger summary (keyword count / regex indicator), status pill, category, updated_at, actions menu.
   - Sort by name, status, updated_at.
   - Empty state: illustration + "Create your first bot" + "Clone from a template" (opens template picker — templates are the 3 default seeded bots from Step 15).
4. Row actions:
   - Edit → `/user/chatbots/:id/edit` (Step 13 builder).
   - Duplicate → server-side duplicate endpoint (already in Step 3 router if included; else add here).
   - Rename inline.
   - Move to folder (drag-drop or picker).
   - Export JSON → downloads `.chatbot.json`.
   - Archive / Restore.
   - Delete (confirmation dialog — hard delete only if archived first).
5. HTTP retry interceptor already applies per memory `feedback_http_retry_interceptor.md` — no extra work.
6. Prettier + eslint clean per memory `feedback_prettier_on_write.md`.

## DB changes / migrations

None.

## Tests to add

Frontend unit tests (Angular Karma):
- `chatbots-list.component.spec.ts` — renders empty state; renders rows; row actions dispatch to service methods.
- `chatbots-api.service.spec.ts` — HTTP calls to correct URLs with correct params.

Manual verification:
- Sidebar entry visible only for users with `chatbots.view` permission.
- Owner can create, duplicate, archive, and delete a bot.
- Employee without `chatbots.edit` sees list but action buttons are disabled with a tooltip.

## Verification checklist

**Backend** — N/A this step (endpoint tests were in Step 3).

**Frontend**
- [ ] `ng serve` (from `APP/`, per memory `feedback_frontend_folder_is_app_not_aixoapp.md`) — `/user/chatbots` renders.
- [ ] Row actions all work end-to-end against a live backend.
- [ ] Sidebar entry visible for allowed roles, hidden for others.
- [ ] Lucide icons rendered — check `app.config.ts` icon registry per memory `feedback_lucide_icon_registry.md`.

**Code review**
- [ ] Standalone components, signals, new control flow (`@if / @for / @switch`).
- [ ] Tailwind only — no PrimeNG/Material additions in new files.
- [ ] Typed reactive forms; no `FormBuilder` untyped shapes.
- [ ] User-facing copy uses "CRM" not "FurniCRM" per memory `feedback_branding_crm_not_furnicrm.md`.

## Self-check (10 rules)

- [ ] Frontend `core/` didn't import `packs/`
- [ ] Sidebar registry consumed (rule #5)
- [ ] Permission-guarded route (rule #6)
- [ ] TailwindCSS only for new pages (locked stack)
- [ ] Under 10 files, under 400 lines
- [ ] Zero TODOs

## Stop & report

Report screenshots of the list page (empty state + populated + row actions), and a browser test transcript for create + duplicate + archive. Run `npx --no-install prettier --write` on the changed files first per memory. Await "proceed".
