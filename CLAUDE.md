# CRM — AI Agent Instructions

This is **Core CRM**, a multi-tenant SaaS CRM platform. It is being built incrementally on top of an existing FastAPI + Angular template (auth preserved, everything else replaced).

> **Current focus: Layer 1 — Core CRM only.** All active work is on the universal CRM platform (`core/` modules: auth, tenants, users, contacts, leads, pipelines, activities, tasks, campaigns, templates, automation, billing, etc.). The furniture vertical pack (`packs/furniture/`) is Layer 2 — a future workstream. Do **not** add furniture-pack code, seed furniture-specific defaults, or design "for the pack" in the current phase unless the step file explicitly says so. Treat any furniture-specific references in this file or in `tasks/` as background context for the eventual Layer 2 build, not as current scope.

In conversation, refer to the project as **"Core CRM"** (or plain "CRM"). Code, paths, and identifiers (e.g. `packs/furniture/`, `furnicrm` DOM classes, the master-prompt filename) stay as-is — renaming them is a breaking change.

The master prompt that originally defined the build is [`furniture-crm-agent-prompt.md`](furniture-crm-agent-prompt.md); its 76-step tree has shipped and been removed. Active work now lives in the tracks under [`tasks/`](tasks/) — always start at [`tasks/README.md`](tasks/README.md), which also explains how to read a deleted track out of git history.

## Project status snapshot

The repo is in the middle of a structural migration. As of this writing:

- **Active workstream: Core CRM (Layer 1).** Backend modules under `api/src/app/core/` are being filled in one at a time following the layered Router → Service → DAL convention.
- **Old template still in place** (`API/`, `APP/`) — the existing app this build is reusing auth from. Step 1.1 renames `API/` → `api/`, `APP/` → `app/`, deletes the non-auth scaffolding, and drops the new layered `core/`+`packs/furniture/` skeleton in place.
- **`packs/furniture/` is scaffolded but parked.** Layer 2 work is deferred until Layer 1 stabilises.
- **`tasks/` holds only in-flight tracks.** The original 76-step plan (Phase 1 → Phase 6) and ~44 completed side tracks were deleted on 2026-09-13 once their work shipped; the code and `git log` are the record. See [`tasks/README.md`](tasks/README.md).
- **Three-track plan COMPLETE (2026-06-30).** The manager-locked Templates → Automation → Workflows pipeline shipped end-to-end: `core/templates/` (central library) + `core/automation/` (single-step triggers) + `core/workflows/` (multi-step visual flowcharts) are all live. The workflows track closed with Step 20 — 15 default core workflows seed into every org as drafts, and `core/email_sequences/` is absorbed (Settings tab gone, `/user/settings/email-sequences/*` redirects to `/user/workflows?category=Marketing`, scheduler tick is a no-op, enrollments shim through `workflows.engine.start_run`). Vertical-pack workflows (Furniture) remain a future workstream.

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
│       │   ├── accounts/               ← Login/register/2FA. Migrated to Tailwind
│       │   │                             to match the user app (logic unchanged).
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
├── tasks/                              ← in-flight build tracks
├── furniture-crm-agent-prompt.md       ← master prompt (filename retained — do not rename)
└── CLAUDE.md                           ← this file
```

### URL surfaces

- `/accounts/login` — login page (existing, migrated to Tailwind).
- `/admin/...` — legacy template admin panel (untouched, idle — not part of Core CRM).
- `/user/...` — **Core CRM main app**. All roles (Owner, Admin, Employee, plus custom roles) log in and land here; sidebar contents are permission-gated by RBAC.
- `/staff-portal/...` — PIN-login tablet UI for shop-floor staff (future, Phase 3).

## Locked stack — DO NOT substitute without asking

- **Backend:** Python **3.13**, FastAPI, **SQLAlchemy 2.x async** (`Mapped`, `async_sessionmaker`, `AsyncSession` — no v1 patterns), Alembic async, **Pydantic v2** + `pydantic-settings`, **PostgreSQL 17** (JSONB, GIN, RLS), Celery + Redis, package manager **uv**.
- **Frontend:** **Angular 20+** standalone (signals, new control flow `@if/@for/@switch`, `inject()`, typed reactive forms — no NgModule), **TailwindCSS for all new pages**.
- **Auth:** JWT HS256 admin (existing) + short-lived staff PIN token (Phase 3).
- **File storage:** **Local filesystem only** under `./storage/{org_id}/{entity}/{file_id}` behind a `StorageBackend` interface. **No S3/boto3 in this build.**
- **API:** REST, JSON, versioned at `/api/v1`.

## The 10 non-negotiable rules

1. **`/core` never imports from `/packs`.** If something needs to, it belongs in `/core`. Stop and reorganize.
2. **Every database table has `org_id`** (UUID FK to organizations) **and is named `tbl_<snake_name>`** (per [`API/docs/DATABASE_RULES.md`](API/docs/DATABASE_RULES.md) and [`API/docs/TABLE_NAMING_MAP.md`](API/docs/TABLE_NAMING_MAP.md); furniture-pack tables use `tbl_fp_<name>`). Every query filters by `org_id`. **Postgres Row-Level Security from day one.** New tables follow the `tbl_` convention from the first commit; no plain-named tables ever land again. The pin-test [`API/tests/test_table_name_convention.py`](API/tests/test_table_name_convention.py) fails CI on drift.
3. **Custom fields use the layered model:** every entity that supports them has a `custom_data` JSONB column; `custom_field_definitions` has a `source` column (`system` | `pack` | `user`).
4. **Forms render dynamically from field definitions.** Frontend asks `GET /api/{entity}/fields` and renders. Never hardcode form fields.
5. **The sidebar/menu is a registry.** Modules register themselves; core does not know about furniture-specific menu items at compile time.
6. **Permissions are a registry.** Each module registers its permission keys; core RBAC composes them.
7. **Pack manifest (`pack.yaml`) is the source of truth** for any future vertical-pack defaults (pipeline stages, custom fields, roles, lead sources, call outcomes, currency/tax, AI defaults). Seed/install logic reads from it — no hardcoded vertical values in core. *(Not in scope for the current Core CRM phase; rule recorded so core stays vertical-agnostic.)*
8. **Step size is small and human-verifiable.** Every step runnable, visually inspectable, reviewable in under 30 minutes. > ~10 files or > ~400 lines → split it.
9. **No skipping verification.** After each step: stop, summary, checklist, **wait for the user to say "proceed"** before the next step. Never batch.
10. **No "I'll fix it later."** No TODOs, no hardcoded shortcuts, no commented-out code. Every step leaves the codebase clean and runnable.

## Backend module layout (Router → Service → DAL)

**Manager spec 2026-06-25 — locked.** Every backend module under `api/src/app/core/<module>/` and `api/src/app/packs/<pack>/modules/<module>/` follows the same five-file domain-driven layout. One responsibility per file. Optional helper files only when needed.

```
<module>/
├── __init__.py
├── models.py          ← SQLAlchemy ORM only (tables, columns, relationships, indexes)
├── schemas.py         ← Pydantic request/response models
├── router.py          ← HTTP endpoints only — receives request, calls service, returns response
├── service.py         ← Business logic + the ONLY layer that touches transactions
└── data_access.py     ← Pure CRUD (SELECT/INSERT/UPDATE/DELETE) — no transactions, no business logic
```

Optional (add only when needed): `utils.py` (pure helpers, no DB), `constants.py` (module enums/constants), `exceptions.py` (custom exception classes), `dependencies.py` (reusable FastAPI `Depends`).

**Layer responsibilities:**

- **`router.py`** — receptionist. Defines endpoints, resolves auth dependency, calls a service, returns response. NEVER executes SQL, calls `db.query / select() / insert() / update() / delete() / db.add / db.commit / db.rollback / db.flush / db.refresh`. NEVER calls another router. NEVER imports another module's DAL — go through that module's service.
- **`service.py`** — brain. Owns business logic, validations, permission + ownership checks, transaction control, response shaping. May call other services (avoid cycles — extract shared logic into utils). Calls own DAL for queries. **ONLY layer that calls `db.commit() / db.rollback() / db.flush() / db.refresh()`.**
- **`data_access.py`** — database assistant. Pure CRUD. One function per DB operation. Allowed: `db.add`, `db.delete`, `db.query`, `db.execute`, returning ORM objects or Core statements. NEVER commits, flushes, refreshes, or rolls back. NEVER contains business logic or permission checks. NEVER imports from `service.py` or `router.py`.

**Allowed communication edges:**

```
HTTP Request → router.py → service.py → data_access.py → Database
                              ↕
                       other module services
```

Forbidden: Router→Router, Router→DB, Router→DAL, DAL→Service, DAL→Router.

**Transaction discipline (zero exceptions):**

```python
# service.py
def create_template_service(db, payload):
    template = data_access.insert_template(db, payload)
    db.flush()
    db.commit()
    db.refresh(template)
    return template
```

**Convention enforced by CI pin-test:** [`API/tests/test_layered_architecture_convention.py`](API/tests/test_layered_architecture_convention.py) walks every file under `src/app/core/` and `src/app/packs/` and fails CI if any of the following drift in:

1. `db.commit / rollback / refresh / flush` appears outside `service.py` / `*_service.py`.
2. `db.execute / add / add_all / delete / query / merge` or a sqlalchemy CRUD constructor import (`select`, `insert`, `update`, `delete`) appears in `router.py`.
3. `data_access.py` calls `db.commit / rollback / refresh / flush`.
4. `service.py` / `*_service.py` runs SQL directly (`db.execute / add / ...`). Statement *composition* (building a `select(...)` and passing it to a DAL paginate helper) stays allowed; only execution is banned.
5. `router.py` imports another module's `data_access` (Router → Service only).
6. `data_access.py` imports any `service` or `router` (DAL never depends upward).
7. **CRUD lives in DAL.** Any helper file under `core/` or `packs/` that calls `db.execute / add / ...` must be `data_access.py`. Helper modules (Celery workers, schedulers, webhook handlers, integration sub-modules) inherited from before the layered layout are in a documented exception list — new helpers must route their SQL through a DAL function.

New backend code should never need to add to any exception list.

**Cross-module data access from `service.py` (preference, not mechanical):** A service may:
- ✓ Call its own `data_access`.
- ✓ Call another module's `service.py`.
- ✓ Call another module's `data_access.py` — *but only when it's a plain read/write with no business rules / permissions / validation at stake.*

When the other module's `service.py` enforces a permission, ownership rule, or validation, go through the service so the rule fires. When it's a pure lookup or stage-an-INSERT helper, calling the other module's DAL directly is acceptable. Code review catches the judgment call; the pin-test deliberately does not enforce this.

## Reuse-vs-restructure exceptions (agreed with user)

These are project-specific deviations from a clean-slate build:

- **Auth logic is preserved**, not rebuilt — JWT bearer with `token_id` session invalidation, password hashing, login history, refresh, forgot/reset password, all three 2FA methods (Google Authenticator + Email OTP + SMS OTP). It is **re-housed** under `api/src/app/core/auth/` (backend) in Steps 1.5/1.6, but the working logic comes from `api/src/...` legacy modules.
- **`org_id` is added** to existing user/role/session tables as part of the migration (existing tables are single-tenant today).
- **`features/admin/` is left UNTOUCHED indefinitely.** It is the legacy template's admin panel and is not part of Core CRM. Do not modify, delete, or repurpose any file inside it. The login form's "Admin login" button continues to work and redirects to `/admin/dashboard` (legacy). Core CRM does not use this path.
- **`features/user/` hosts the Core CRM frontend.** All Layer 1 (`core/`) module code lives at `app/src/app/features/user/core/...`. Layer 2 pack code (`app/src/app/features/user/packs/furniture/...`) is scaffolded but not the current focus. Core CRM roles log in via the user-login button and land at `/user/...`.
- **`staff-portal/` is a separate top-level route tree** at `app/src/app/staff-portal/` for PIN tablet login. NOT under `features/user/`.
- **Auth pages were migrated to Tailwind** to match the Core CRM user app. The accounts pages (login, register, forgot/reset password, two-factor, verify-email, email-verification-notice), the shared accounts layout, and the shared captcha component were rebuilt in Tailwind (zinc palette, white `rounded-xl border border-zinc-200 shadow-sm` cards, `bg-zinc-900` primary button) so login no longer reads as a different product from the dashboard. **All auth/registration logic is unchanged** — only markup + styling. Notes: the accounts-layout theme toggle was removed (the user app is light-only with no toggle); register's country/state `mat-select` (with in-panel search) became a Tailwind-styled native `<select>` (native type-ahead, no search box); error toasts still use `MatSnackBar`. `features/admin/` is untouched and keeps its Material visuals. **All pages now use Tailwind only.**
- **Folders renamed lowercase:** `API/` → `api/`, `APP/` → `app/`.
- **Old template docs** under `api/docs/` and `app/docs/` remain as **reference** for the existing auth code's patterns. They describe the legacy template, not Core CRM, and should not drive new code.

## Gate 0 — Discovery before building something new

When the user describes a product idea, or a feature in an area this project has never built before, **do not start planning or writing code.** Run discovery first per [`DISCOVERY_RULES.md`](DISCOVERY_RULES.md), and create or extend `PRODUCT_BRIEF.md`.

Run discovery when: no `PRODUCT_BRIEF.md` exists · the request touches a surface the brief does not cover · a decision is expensive to reverse and the brief does not answer it.

Do **NOT** run discovery for: a field, page, filter, report or setting, or any ordinary feature work. Those benchmark against the existing brief.

If unsure which it is, say so and ask — do not default to building.

The brief is the reference every later plan is checked against. When discovery surfaces a platform constraint (something a provider or regulation makes impossible, capped, approval-gated or time-windowed), promote it into this file as a hard architecture rule so it is enforced rather than remembered.

## Step execution discipline

**Before writing a track plan (`tasks/<track>/README.md`) or any step files, read [`PLANNING_RULES.md`](PLANNING_RULES.md)** — the design-time gate that must clear before step files are written.

For every step (defined in `tasks/<track>/step-*.md`):

1. **Announce:** "Starting Step X.Y: <Title>. Goal: <one sentence>."
2. **Plan briefly** (5–10 bullets, files you'll touch).
3. **Implement** strictly within scope.
4. **Migrations:** if a DB change is involved, write Alembic migration + verify up + down.
5. **Tests:** add minimal tests proportional to the step.
6. **Self-check — re-read, don't recall.** Before reporting done, RE-OPEN the rule sources (the 10 rules and Backend module layout above, plus the step file's own checklist) and read each one against the code you just wrote. Marking an item done means you re-read that rule and confirmed the new code satisfies it — not that you remember the rule. Emit a short self-audit block: one line per area, each `pass` / `fixed` / `N/A` (10 rules · layering · reuse · DB efficiency · tooling-clean).
7. **Stop and report** with the template the master prompt specifies (Files changed · What you can verify · Tests added · Self-check · "Awaiting your 'proceed'").

When adding seed routes, **output raw INSERT SQL** in the report so the user can paste it into the DB directly.

If anything is ambiguous, **stop and ask one concrete question** with 2–3 options and a recommendation. Do not guess.

## Scope and code quality

- Implement **ONLY** what the current step file says. No bonus features, no refactors, no abstractions for "future flexibility."
- Every change must be **production-ready** — no placeholders, no TODOs, no commented-out code.
- Match existing code patterns where they're already correct; introduce new patterns only when the step requires it.
- Remove unused imports/variables/functions in files you touch.
- **Reuse before create.** Before adding a function/method/component, search for an existing one and extend it (add a parameter, broaden a filter) when the change is clean. Create new only when sharing would twist the abstraction — no near-duplicate methods.
- **Query efficiency.** No N+1: never query the database inside a loop. Fold related data into one statement with joins / subqueries / batched (`IN`) reads, and eager-load relationships (`selectinload` / `joinedload`). Aim for ≈2–3 DB round-trips per request — a soft target to catch the accidental many-queries path, not a hard cap; more is fine when the logic genuinely needs it.
- **Organization.** Keep code well-organized and in the layer it belongs to — backend follows Router → Service → DAL (above); frontend follows the `core/` / `packs/` feature layout. Don't bypass layering for convenience.
- After completing a step, report what was done and **STOP**. Do not start the next step.

## Code-quality tooling (background context)

Linters and formatters run on this repo, so generated code should already match their style — but they are **not** the gate. The authoritative check is the self-recheck above (re-read the rules against your code); the tools only catch mechanical drift.

- **Python (`API/`):** `ruff format` + `ruff check` (E/F/I/B/UP, line-length 100) block on the pre-commit hook and CI; `bandit` and `pyright` run advisory (CI report-only).
- **Frontend (`APP/`):** `prettier` and `eslint` errors block (warnings advisory); `tsc --noEmit` and `jscpd` duplication run advisory.
- `run lint` checks, `run lint-fix` auto-formats/fixes. The pre-commit hook (auto-wired by `run up`) runs the blocking subset on staged files; full enforcement is [`.github/workflows/quality.yml`](.github/workflows/quality.yml) on PRs to `dev`/`main`. Config lives in [`API/pyproject.toml`](API/pyproject.toml), [`APP/eslint.config.js`](APP/eslint.config.js), and [`APP/.prettierrc`](APP/.prettierrc). Two CI pin-tests also enforce the `tbl_` table naming and Router → Service → DAL conventions.

## Terminal (Windows)

- The shell is **PowerShell**. Use PowerShell syntax (`$env:VAR`, `$null`, backtick continuation). Bash is also available via the Bash tool for POSIX scripts.
- For Python work in `api/`, prefer `uv run <cmd>` (e.g., `uv run uvicorn src.app.main:app`, `uv run alembic upgrade head`, `uv run pytest`).
- For Angular work in `app/`, use `npm` / `ng` as usual.
- Secrets (DB password, JWT/Fernet keys, API keys) live in `API/secrets.enc.env`, **SOPS + age encrypted** and committed; they are decrypted in-memory at runtime by `sops exec-env` (via `run.cmd` / `run.sh`) and read through `os.getenv`. Non-secret config lives in `API/config.env` (committed plaintext). There is no `.env` / `.env.example`. See [`API/SOPS_INTEGRATION_GUIDE.md`](API/SOPS_INTEGRATION_GUIDE.md). Edit secrets with `run secrets-edit`; never hand-edit `secrets.enc.env`.

## Where to find what

| Need | Look here |
|------|-----------|
| Master build plan | [`furniture-crm-agent-prompt.md`](furniture-crm-agent-prompt.md) |
| Per-step tasks | [`tasks/README.md`](tasks/README.md) → track folder → step file |
| The 10 rules | this file (above) and `tasks/README.md` |
| Existing auth code (reference) | [`API/src/routers/auth/`](API/src/routers/auth/), [`API/src/services/auth/`](API/src/services/auth/), [`APP/src/app/features/accounts/`](APP/src/app/features/accounts/) |
| Existing template docs (reference only) | [`API/docs/`](API/docs/), [`APP/docs/`](APP/docs/) — describe the legacy template, not Core CRM |
| Pack manifest (after Phase 4.2) | `api/src/app/packs/furniture/pack.yaml` |

## What this file is NOT

- It is **not** a substitute for reading `tasks/README.md` and the relevant step file before working a step.
- It does **not** describe the existing template's API endpoints or component conventions — those live under `API/docs/` and `APP/docs/` and apply only to the auth code being preserved.
- It does **not** define vertical-pack scope. Anything under `packs/furniture/` is Layer 2 and out of scope for the current Core CRM phase.
