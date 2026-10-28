# Step 1.1 — Repository skeleton

**Goal:** Reorganise the repo into the FurnitureCRM layered layout — lowercase `api/`+`app/`, two-layer `core/`+`packs/furniture/` skeletons hosted **inside `app/src/app/features/user/`**, install TailwindCSS scoped to FurnitureCRM areas, fresh root files, **`features/admin/` left completely untouched**, no app logic yet.
**Phase:** 1 — Foundation & Scaffolding
**Depends on:** none
**Status:** Completed

## Decision recap (locked)
- **`features/admin/` is untouched** — not deleted, not modified, not even renamed. It remains as the legacy template's admin panel and is not part of FurnitureCRM. Login form's "Admin login" button + `/admin/...` redirect target keep working as today.
- **`features/user/` is the host** for FurnitureCRM. Old user-side scaffolding (dashboard, profile, security, support, change-password) is removed. New layered structure (`core/`, `packs/furniture/`, `layout/`) lives under it.
- **Frontend layered code lives under `app/src/app/features/user/core/...` and `app/src/app/features/user/packs/furniture/...`.** All seven FurnitureCRM roles (Owner, Store Manager, Senior/Sales/Junior Sales Executive, Design Consultant, Warehouse Manager) log in via the existing User-login button and land here.
- **Staff Portal** (Phase 3, Step 3.7) lives at top-level `app/src/app/staff-portal/...` — separate route tree, PIN auth, NOT under `features/user/`.
- **Backend** layered code stays per master doc: `api/src/app/core/...`, `api/src/app/packs/furniture/...`, `api/src/app/shared/...`. No "user side" / "admin side" distinction on backend.

## Scope
**In-scope:**
- Rename `API/` → `api/` and `APP/` → `app/` (Windows two-step rename via temp dirs).
- Inside `api/src/app/` create empty `core/`, `packs/furniture/`, `shared/` trees with `__init__.py` placeholders (alongside existing `api/src/`).
- Inside `app/src/app/features/user/` create empty `core/{layout, contacts, leads, ...}` and `packs/furniture/{...}` trees.
- Inside `app/src/app/staff-portal/` create empty subfolders (login, dashboard, etc.) — placeholder only; built in Phase 3.
- Delete non-auth backend scaffolding: `api/src/routers/{admin, user, common, dev, routes, misc, app_config}` and matching `services/`, `models/`, `schemas/`, `data_access/`, `seeds/`.
- Delete old user-side frontend folders: `app/src/app/features/user/{dashboard, profile, security, support, change-password, layout}` (the OLD user.routes.ts is rewritten in scope, not deleted).
- **Install TailwindCSS** inside `app/`: dev deps (`tailwindcss`, `postcss`, `autoprefixer`), `tailwind.config.js`, `postcss.config.js`, new `src/tailwind.scss` with `@tailwind` directives, `angular.json` styles array updated to include both existing global SCSS and `tailwind.scss`. Tailwind's `content` paths cover ONLY `src/app/features/user/**/*.{html,ts}` and `src/app/staff-portal/**/*.{html,ts}` — explicitly **excludes** `features/accounts/**` and `features/admin/**` so existing PrimeNG/Material visuals are untouched.
- Patch `app/src/app/features/user/user.routes.ts` to a placeholder route that loads a temporary `home-stub.component.ts` (single Tailwind page with "Welcome — full UI coming soon"), so login redirect doesn't 404.
- Patch `app/src/app/features/accounts/login/login.component.ts` redirect: when `role !== ROLE_ADMIN`, navigate to `/user` (which now hits the home stub) instead of the old `/user/dashboard`. Admin-role redirect to `/admin/dashboard` is left untouched.
- Create root `README.md` (project overview), `.gitignore`, `.editorconfig`, `.env.example`.
- (`CLAUDE.md` was already updated to FurnitureCRM rules before Phase 1 began — no action needed here.)

**Out of scope:**
- Any code logic beyond the home stub + redirect patch (FastAPI app, Angular bootstrap, DB connection) — those land in 1.2 and 1.9.
- Touching `Flutter/` (untouched per agreement).
- **Touching anything inside `features/admin/`** (untouched per locked decision).
- Touching auth files (`api/src/routers/auth/`, `app/src/app/features/accounts/`, `app/src/app/core/guards/`, `app/src/app/core/interceptors/`, `app/src/app/core/services/auth.service.ts`) — they stay; relocation into `app/core/auth/` happens in 1.5/1.6.

## Files to touch
- `api/` (renamed from `API/`)
- `app/` (renamed from `APP/`)
- `api/src/app/__init__.py` (created)
- `api/src/app/core/__init__.py` + 22 module subdirs each with `__init__.py` (created)
- `api/src/app/packs/furniture/{pack.yaml.placeholder, __init__.py}` and module subdirs (created — empty)
- `api/src/app/shared/__init__.py` (created)
- `app/src/app/features/user/core/{layout, contacts, activities, pipelines, appointments, custom-fields, walk-ins, catalog, billing, conversations, calls, reviews, campaigns, settings, shared, leads, tasks, notifications, dashboard, staff, ai, reporting}/.gitkeep` (created)
- `app/src/app/features/user/packs/furniture/{inventory, custom-orders, field-ops, marketplace, virtual-staging, qr-marketing, billing}/.gitkeep` (created)
- `app/src/app/features/user/layout/home-stub.component.ts` (created — placeholder)
- `app/src/app/features/user/layout/home-stub.component.html` (created)
- `app/src/app/features/user/user.routes.ts` (rewritten — single placeholder route to home stub)
- `app/src/app/features/accounts/login/login.component.ts` (modified — redirect target patch only)
- `app/src/app/staff-portal/.gitkeep` (created — placeholder)
- `app/package.json` (modified — adds `tailwindcss`, `postcss`, `autoprefixer` to devDependencies)
- `app/package-lock.json` (modified by `npm install`)
- `app/tailwind.config.js` (created)
- `app/postcss.config.js` (created)
- `app/src/tailwind.scss` (created)
- `app/angular.json` (modified — styles array)
- `README.md` (replaced)
- `.gitignore` (replaced/extended)
- `.editorconfig` (created)
- `.env.example` (created)
- Deleted: backend non-auth paths and frontend `features/user/{dashboard, profile, security, support, change-password, layout}` (the old layout dir).

## Plan
1. Move `API/` → `_API_tmp/` → `api/` (Windows case-only rename workaround). Confirm `git status` shows the rename.
2. Move `APP/` → `_APP_tmp/` → `app/`. Same.
3. Inside `api/src/app/` (a brand-new package alongside the existing `src/`) create the empty layered tree. Existing `api/src/` stays for now; auth migration into `api/src/app/core/auth/` happens in 1.5/1.6.
4. Delete the non-auth backend trees per the agreed list. Run `python -c "import src.routers.auth"` from `api/` (or equivalent) to confirm imports still resolve in auth code.
5. Create the empty Angular layered folders under `app/src/app/features/user/core/` and `app/src/app/features/user/packs/furniture/`. Create the empty `app/src/app/staff-portal/` folder.
6. Delete the old user-side frontend subfolders (dashboard, profile, security, support, change-password, layout).
7. **Install Tailwind in `app/`:** `npm install --save-dev tailwindcss postcss autoprefixer`, then `npx tailwindcss init -p` to generate config files.
8. **Configure Tailwind** — edit `tailwind.config.js`:
   ```js
   module.exports = {
     content: [
       './src/app/features/user/**/*.{html,ts}',
       './src/app/staff-portal/**/*.{html,ts}',
     ],
     theme: { extend: {} },
     plugins: [],
   };
   ```
   Note: `features/accounts` and `features/admin` are **not** in `content` — Tailwind doesn't scan them, doesn't generate utility classes for them, doesn't conflict with PrimeNG/Material there.
9. Create `app/src/tailwind.scss` with the three directives:
   ```scss
   @tailwind base;
   @tailwind components;
   @tailwind utilities;
   ```
10. Update `angular.json` `projects.<name>.architect.build.options.styles` to include `"src/tailwind.scss"` alongside the existing `"src/styles.scss"`.
11. Write the placeholder `home-stub.component.ts` + `.html` (standalone, signals-first, Tailwind classes — `class="flex flex-col items-center justify-center min-h-screen bg-zinc-50"`, fetches user name from existing auth service).
12. Rewrite `features/user/user.routes.ts`: single route `''` that renders `HomeStubComponent`. Wrap in the existing `authGuard`.
13. Patch `login.component.ts:107-109` so non-admin role redirects to `getRoute('user').url` (i.e. `/user`) which now hits the stub. Admin role redirect stays as `getRoute('admin_dashboard').url` (untouched).
14. Write top-level `README.md` describing the layered architecture + features/admin-untouched policy + Tailwind scoping.
15. Write `.gitignore` (Python, Node, IDE, storage/, .env*).
16. Write `.editorconfig` (UTF-8, LF, trim trailing whitespace, 2-space indent for TS/YAML/JSON, 4-space for Python).
17. Write `.env.example` with placeholder env vars (DB URL, JWT_SECRET, REDIS_URL).
18. Build `app/` to confirm it still compiles (`cd app && npx ng build`).
19. Manual smoke: `npx ng serve` → log in with seeded admin → lands on `/admin/dashboard` (legacy PrimeNG/Material visuals intact). Log in with non-admin → lands on `/user` → home stub renders with Tailwind styling.
20. Visual regression check: open the existing login page → it must look identical to before (no Tailwind utility class accidentally affecting it). Open `/admin/dashboard` → identical to before.

## DB changes / migrations
None.

## Tests to add
None (no business logic). Manual smoke per Plan step 15.

## Verification checklist
**Code review:**
- run: `git status` → expect renames `API/` → `api/`, `APP/` → `app/`, deletions of non-auth files, `features/admin/` **unchanged**.
- run: `Get-ChildItem api/src/app/core | Select Name` → expect 22 module directories.
- run: `Get-ChildItem app/src/app/features/user/core | Select Name` → expect new layered folders.
- run: `Get-ChildItem app/src/app/features/admin | Select Name` → expect **identical to before** (dashboard, news, popups, ... all present).
- run: `git diff app/src/app/features/admin/` → expect **empty**.
- open `app/tailwind.config.js` → confirm `content` array contains only `features/user/**` + `staff-portal/**`, NOT `features/accounts` or `features/admin`.
- open `app/angular.json` → confirm both `styles.scss` and `tailwind.scss` listed under build styles.
- open `README.md` — note the layered architecture explanation + features/user vs features/admin policy + Tailwind scoping.
- open `.gitignore` — note `storage/`, `.venv`, `node_modules`, `.env*` entries.
- confirm `Flutter/` dir unchanged in `git status`.

**Backend:**
- run: `cd api && python -c "from src.routers.auth import login"` → no ImportError (auth still intact).

**Frontend:**
- run: `cd app && npm install` (re-run if needed) → no errors; node_modules contains `tailwindcss`.
- run: `cd app && npx ng build` → builds clean. CSS bundle size grows by Tailwind's purged output.
- run: `cd app && npx ng serve` → app boots on http://localhost:4200.
- visit: `/accounts/login` → identical to before (PrimeNG/Material styling intact, no Tailwind utility classes leaking in).
- log in with seeded **admin** user → lands on `/admin/dashboard` → identical to before (legacy panel, untouched).
- log in with seeded **non-admin** user → lands on `/user` → Tailwind-styled welcome stub renders ("Welcome, <name>").
- DevTools → Elements: confirm Tailwind classes (e.g. `flex`, `min-h-screen`) only appear on the stub page, NOT on the login or admin pages.

## Self-check (10 rules)
- [ ] No `from src.app.packs` import in `app/core/` (no code yet, so trivially holds — CI guard added in Phase 6).
- [ ] No tables created yet (rule 2 N/A).
- [ ] No TODOs, no commented-out code in any new file.
- [ ] Folder names lowercase; existing `Flutter/` and `features/admin/` untouched.
- [ ] Step ≤ ~10 files of meaningful logic (the home stub + login redirect patch are tiny; everything else is folder scaffolding).

## Stop & report
Use the master-prompt stop template; await "proceed" before Step 1.2.
