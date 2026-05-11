# FurnitureCRM — AI Agent Instructions

This is **FurnitureCRM**, a multi-tenant SaaS CRM for Indian furniture retail stores. It is being built incrementally on top of an existing FastAPI + Angular template (auth preserved, everything else replaced).

The single source of truth for the build is the master prompt at [`furniture-crm-agent-prompt.md`](furniture-crm-agent-prompt.md). The 76-step task tree under [`tasks/`](tasks/) breaks that prompt into self-contained, individually verifiable steps. Always start at [`tasks/README.md`](tasks/README.md).

## Project status snapshot

The repo is in the middle of a structural migration. As of this writing:

- **Old template still in place** (`API/`, `APP/`, `Flutter/`) — the existing app that this build is reusing auth from. Step 1.1 renames `API/` → `api/`, `APP/` → `app/`, deletes the non-auth scaffolding, and drops the new layered `core/`+`packs/furniture/` skeleton in place. **`Flutter/` is left untouched** (no Flutter component in FurnitureCRM).
- **`tasks/` already populated** with the full 76-step plan (Phase 1 → Phase 6).
- **No code changes yet** — waiting for the user to say "begin" before Step 1.1.

## Target repository structure (after Step 1.1)

```
furniture-crm/
├── api/                                ← FastAPI backend (renamed from API/)
│   ├── src/                            ← legacy package (hosts auth code) + NEW layered app/
│   │   ├── app/                        ← NEW layered package
│   │   │   ├── core/                   ← Layer 1: universal CRM platform
│   │   │   │   ├── auth/  tenants/  users/  permissions/  contacts/  activities/
│   │   │   │   ├── tasks/  pipelines/  appointments/  custom_fields/  walk_ins/
│   │   │   │   ├── catalog/  billing/  conversations/  calls/  reviews/  campaigns/
│   │   │   │   ├── notifications/  files/  integrations/  reporting/  settings/
│   │   │   │   └── module_registry.py
│   │   │   ├── packs/
│   │   │   │   └── furniture/          ← Layer 2: vertical pack
│   │   │   │       ├── pack.yaml       ← source of truth for furniture defaults
│   │   │   │       ├── installer.py
│   │   │   │       └── modules/{inventory, custom_orders, field_ops, marketplace,
│   │   │   │                    virtual_staging, qr_marketing, billing}/
│   │   │   ├── shared/                 ← db, config, logging, exceptions, RLS, storage
│   │   │   └── main.py
│   │   └── (legacy routers/services/models/... — auth code until 1.5/1.6 ports it)
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml                  ← uv-managed
├── app/                                ← Angular frontend (renamed from APP/)
│   └── src/app/
│       ├── features/
│       │   ├── accounts/               ← UNTOUCHED. Login/register/2FA.
│       │   ├── admin/                  ← UNTOUCHED. Legacy template admin panel — NOT
│       │   │                             part of FurnitureCRM. Don't modify, don't delete.
│       │   └── user/                   ← FurnitureCRM lives here.
│       │       ├── core/               ← Layer 1: universal CRM UI (per master doc)
│       │       │   ├── layout/  dashboard/  contacts/  leads/  walk-ins/
│       │       │   ├── activities/  pipelines/  appointments/  custom-fields/
│       │       │   ├── tasks/  catalog/  billing/  conversations/  calls/
│       │       │   ├── reviews/  campaigns/  notifications/  settings/
│       │       │   ├── staff/  reporting/  ai/  shared/
│       │       │   └── ...
│       │       ├── packs/furniture/    ← Layer 2: vertical pack UI
│       │       │   ├── inventory/  custom-orders/  field-ops/
│       │       │   ├── marketplace/  virtual-staging/  qr-marketing/  billing/
│       │       │   └── ...
│       │       ├── layout/             ← FurnitureCRM main app shell (sidebar+header)
│       │       └── user.routes.ts      ← thin route tree wiring core/ + packs/
│       └── staff-portal/               ← Separate route tree (PIN tablet login, Phase 3)
├── Flutter/                            ← UNTOUCHED (not part of FurnitureCRM)
├── tasks/                              ← 76-step build plan
├── furniture-crm-agent-prompt.md       ← master prompt
└── CLAUDE.md                           ← this file
```

### URL surfaces

- `/accounts/login` — login page (existing, PrimeNG/Material visuals, untouched).
- `/admin/...` — legacy template admin panel (untouched, idle for FurnitureCRM).
- `/user/...` — **FurnitureCRM main app** for all seven roles (Owner, Store Manager, Senior/Sales/Junior Sales Executive, Design Consultant, Warehouse Manager). What each role sees in the sidebar is permission-gated.
- `/staff-portal/...` — PIN-login tablet UI for shop-floor staff (built in Phase 3).

## Locked stack — DO NOT substitute without asking

- **Backend:** Python **3.13**, FastAPI, **SQLAlchemy 2.x async** (`Mapped`, `async_sessionmaker`, `AsyncSession` — no v1 patterns), Alembic async, **Pydantic v2** + `pydantic-settings`, **PostgreSQL 17** (JSONB, GIN, RLS), Celery + Redis, package manager **uv**.
- **Frontend:** **Angular 20+** standalone (signals, new control flow `@if/@for/@switch`, `inject()`, typed reactive forms — no NgModule), **TailwindCSS for all new pages**.
- **Auth:** JWT HS256 admin (existing) + short-lived staff PIN token (Phase 3).
- **File storage:** **Local filesystem only** under `./storage/{org_id}/{entity}/{file_id}` behind a `StorageBackend` interface. **No S3/boto3 in this build.**
- **API:** REST, JSON, versioned at `/api/v1`.

## The 10 non-negotiable rules

1. **`/core` never imports from `/packs`.** If something needs to, it belongs in `/core`. Stop and reorganize.
2. **Every database table has `org_id`** (UUID FK to organizations). Every query filters by `org_id`. **Postgres Row-Level Security from day one.**
3. **Custom fields use the layered model:** every entity that supports them has a `custom_data` JSONB column; `custom_field_definitions` has a `source` column (`system` | `pack` | `user`).
4. **Forms render dynamically from field definitions.** Frontend asks `GET /api/{entity}/fields` and renders. Never hardcode form fields.
5. **The sidebar/menu is a registry.** Modules register themselves; core does not know about furniture-specific menu items at compile time.
6. **Permissions are a registry.** Each module registers its permission keys; core RBAC composes them.
7. **Pack manifest (`pack.yaml`) is the source of truth** for furniture-specific defaults (pipeline stages, custom fields, roles, lead sources, call outcomes, INR/GST 18%, AI defaults). Seed/install logic reads from it — no hardcoded furniture values in core.
8. **Step size is small and human-verifiable.** Every step runnable, visually inspectable, reviewable in under 30 minutes. > ~10 files or > ~400 lines → split it.
9. **No skipping verification.** After each step: stop, summary, checklist, **wait for the user to say "proceed"** before the next step. Never batch.
10. **No "I'll fix it later."** No TODOs, no hardcoded shortcuts, no commented-out code. Every step leaves the codebase clean and runnable.

## Reuse-vs-restructure exceptions (agreed with user)

These are project-specific deviations from a clean-slate build:

- **Auth logic is preserved**, not rebuilt — JWT bearer with `token_id` session invalidation, password hashing, login history, refresh, forgot/reset password, all three 2FA methods (Google Authenticator + Email OTP + SMS OTP). It is **re-housed** under `api/src/app/core/auth/` (backend) in Steps 1.5/1.6, but the working logic comes from `api/src/...` legacy modules.
- **`org_id` is added** to existing user/role/session tables as part of the migration (existing tables are single-tenant today).
- **`features/admin/` is left UNTOUCHED indefinitely.** It is the legacy template's admin panel and is not part of FurnitureCRM. Do not modify, delete, or repurpose any file inside it. The login form's "Admin login" button continues to work and redirects to `/admin/dashboard` (legacy). FurnitureCRM does not use this path.
- **`features/user/` hosts the FurnitureCRM frontend.** All Layer 1 (`core/`) and Layer 2 (`packs/furniture/`) module code lives at `app/src/app/features/user/core/...` and `app/src/app/features/user/packs/furniture/...`. The seven FurnitureCRM roles all log in via the user-login button and land at `/user/...`.
- **`staff-portal/` is a separate top-level route tree** at `app/src/app/staff-portal/` for PIN tablet login. NOT under `features/user/`.
- **Existing auth pages** (login/register/forgot/reset/2FA) **keep their PrimeNG + Angular Material visuals** — option (a) chosen by user. **All new pages use Tailwind only.** Two styling systems coexist by design.
- **Folders renamed lowercase:** `API/` → `api/`, `APP/` → `app/`. **`Flutter/` untouched** (not part of this product).
- **Old template docs** under `api/docs/` and `app/docs/` remain as **reference** for the existing auth code's patterns. They do **not** describe FurnitureCRM and should not drive new code.

## Step execution discipline

For every step (defined in `tasks/phase-X/step-X.Y-*.md`):

1. **Announce:** "Starting Step X.Y: <Title>. Goal: <one sentence>."
2. **Plan briefly** (5–10 bullets, files you'll touch).
3. **Implement** strictly within scope.
4. **Migrations:** if a DB change is involved, write Alembic migration + verify up + down.
5. **Tests:** add minimal tests proportional to the step.
6. **Self-check** against the 10 rules.
7. **Stop and report** with the template the master prompt specifies (Files changed · What you can verify · Tests added · Self-check · "Awaiting your 'proceed'").

When adding seed routes, **output raw INSERT SQL** in the report so the user can paste it into the DB directly.

If anything is ambiguous, **stop and ask one concrete question** with 2–3 options and a recommendation. Do not guess.

## Scope and code quality

- Implement **ONLY** what the current step file says. No bonus features, no refactors, no abstractions for "future flexibility."
- Every change must be **production-ready** — no placeholders, no TODOs, no commented-out code.
- Match existing code patterns where they're already correct; introduce new patterns only when the step requires it.
- Remove unused imports/variables/functions in files you touch.
- After completing a step, report what was done and **STOP**. Do not start the next step.

## Terminal (Windows)

- The shell is **PowerShell**. Use PowerShell syntax (`$env:VAR`, `$null`, backtick continuation). Bash is also available via the Bash tool for POSIX scripts.
- For Python work in `api/`, prefer `uv run <cmd>` (e.g., `uv run uvicorn src.app.main:app`, `uv run alembic upgrade head`, `uv run pytest`).
- For Angular work in `app/`, use `npm` / `ng` as usual.
- Database password and other secrets live in `.env` (never commit). `.env.example` is the canonical list.

## Where to find what

| Need | Look here |
|------|-----------|
| Master build plan | [`furniture-crm-agent-prompt.md`](furniture-crm-agent-prompt.md) |
| Per-step tasks | [`tasks/README.md`](tasks/README.md) → phase folder → step file |
| The 10 rules | this file (above) and `tasks/README.md` |
| Existing auth code (reference) | [`API/src/routers/auth/`](API/src/routers/auth/), [`API/src/services/auth/`](API/src/services/auth/), [`APP/src/app/features/accounts/`](APP/src/app/features/accounts/) |
| Existing template docs (reference only) | [`API/docs/`](API/docs/), [`APP/docs/`](APP/docs/) — describe the old template, not FurnitureCRM |
| Pack manifest (after Phase 4.2) | `api/src/app/packs/furniture/pack.yaml` |

## What this file is NOT

- It is **not** a substitute for reading `tasks/README.md` and the relevant step file before working a step.
- It does **not** describe the existing template's API endpoints or component conventions — those live under `API/docs/` and `APP/docs/` and apply only to the auth code being preserved.
- It does **not** authorise starting Step 1.1. The user must say "begin."
