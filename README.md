# FurnitureCRM

Multi-tenant SaaS CRM for Indian furniture retail stores. Built incrementally on top of an existing FastAPI + Angular template (auth preserved, everything else replaced).

The single source of truth for the build is the master prompt at [`furniture-crm-agent-prompt.md`](furniture-crm-agent-prompt.md). The 76-step build plan lives under [`tasks/`](tasks/README.md). Project rules and AI agent instructions live in [`CLAUDE.md`](CLAUDE.md).

## Architecture — two layers, one codebase

```
furniture-crm/
├── api/                                ← FastAPI backend (Python 3.13, SQLAlchemy 2 async, Postgres 17)
│   ├── app/                            ← NEW layered package
│   │   ├── core/                       ← Layer 1: universal CRM platform (never imports from packs/)
│   │   │   ├── auth/  tenants/  users/  permissions/  contacts/  activities/
│   │   │   ├── tasks/  pipelines/  appointments/  custom_fields/  walk_ins/
│   │   │   ├── catalog/  billing/  conversations/  calls/  reviews/  campaigns/
│   │   │   ├── notifications/  files/  integrations/  reporting/  settings/
│   │   │   └── module_registry.py
│   │   ├── packs/furniture/            ← Layer 2: vertical pack (may import from core/)
│   │   │   ├── pack.yaml               ← source of truth for furniture defaults
│   │   │   └── modules/{inventory, custom_orders, field_ops, marketplace,
│   │   │                virtual_staging, qr_marketing}/
│   │   ├── shared/                     ← db, config, logging, RLS, storage abstraction
│   │   └── main.py
│   ├── src/                            ← legacy template (auth code lives here until 1.5/1.6 ports it)
│   ├── alembic/                        ← migrations
│   └── pyproject.toml
├── app/                                ← Angular 21+ standalone, signals, TailwindCSS for new pages
│   └── src/app/
│       ├── features/
│       │   ├── accounts/               ← UNTOUCHED. Login/register/2FA pages (PrimeNG/Material visuals).
│       │   ├── admin/                  ← UNTOUCHED. Legacy template admin panel — NOT FurnitureCRM.
│       │   └── user/                   ← FurnitureCRM tenant app lives here.
│       │       ├── core/               ← Layer 1: universal CRM UI
│       │       ├── packs/furniture/    ← Layer 2: vertical pack UI
│       │       └── layout/             ← FurnitureCRM main shell + home stub
│       └── staff-portal/               ← Separate route tree (PIN tablet UI, Phase 3)
├── Flutter/                            ← UNTOUCHED (not part of FurnitureCRM)
├── tasks/                              ← 76-step build plan (one phase per folder, one file per step)
└── furniture-crm-agent-prompt.md       ← master agent prompt
```

### URL surfaces

| Path | What it is |
|------|-----------|
| `/accounts/login` | Login page (PrimeNG/Material visuals — untouched). |
| `/admin/...` | Legacy template admin panel — works as before, NOT part of FurnitureCRM. |
| `/user/...` | **FurnitureCRM main app** — all CRM users land here, sidebar adapts to permissions. |
| `/staff-portal/...` | PIN-login tablet UI for shop-floor staff (built in Phase 3). |

## The 10 non-negotiable rules

1. `app/core/` (frontend) and `api/src/app/core/` (backend) **never import** from `packs/`.
2. Every database table has `org_id`. Postgres Row-Level Security enabled from day one.
3. Custom fields use a layered model: `custom_data` JSONB on every entity + `custom_field_definitions` with a `source` column (`system`/`pack`/`user`).
4. Forms render dynamically from field definitions — never hardcoded.
5. Sidebar/menu is a registry — modules register themselves; core has no knowledge of pack-specific menu items.
6. Permissions are a registry — modules register their own permission keys; core RBAC composes them.
7. Pack manifest (`pack.yaml`) is the source of truth for furniture-specific defaults — pipeline stages, custom fields, roles, lead sources, call outcomes, GST 18%, INR.
8. Step size is small and human-verifiable. ≤ ~10 files / ≤ ~400 lines per step.
9. After each step: stop, summarise, give verification checklist, **wait for "proceed"**.
10. No "I'll fix it later" — no TODOs, no commented-out code. Every step leaves the codebase clean and runnable.

## First-time setup (your friend's machine)

Prerequisites (one-time per machine):
- **Node.js 20+** — https://nodejs.org
- **Python 3.13** — https://python.org
- **uv** — `pip install uv` (Python package manager)
- **Docker Desktop** — https://docker.com
- **Git** — https://git-scm.com

Then:

```bash
git clone <this repo>
cd furniture-crm

# Frontend
cd app
npm install            # installs Tailwind, Angular, etc.

# Backend (later, once api/ has pyproject.toml with new layout)
cd ../api
uv sync                # installs FastAPI, SQLAlchemy, etc.

# Services
docker compose -f api/docker-compose.yml up -d db redis

# Migrations + seed (later steps will populate these)
cd api
uv run alembic upgrade head
uv run python -m src.app.scripts.seed_demo_org

# Run
cd api && uv run uvicorn src.app.main:app --reload  # backend on :8000
cd app && npx ng serve                              # frontend on :4200
```

Open http://localhost:4200 in a browser.

## Stack (locked — do not substitute without asking)

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.x async, Alembic async, Pydantic v2, PostgreSQL 17, Celery + Redis. Package manager: **uv**.
- **Frontend:** Angular 20+ standalone (signals, new control flow, `inject()`, typed reactive forms — no NgModule). **TailwindCSS for all new pages**, PrimeNG/Material kept on existing auth pages.
- **Auth:** JWT HS256 admin (existing) + short-lived staff PIN token (Phase 3).
- **File storage:** Local filesystem under `./storage/{org_id}/{entity}/{file_id}` behind a `StorageBackend` interface. **No S3/boto3 in this build.**
- **API:** REST, JSON, versioned at `/api/v1`.

## Build progress

Track per-step status in [`tasks/README.md`](tasks/README.md). Each phase folder contains self-contained step files (goal · scope · files · plan · verification · 10-rule self-check).

| Phase | Title | Steps |
|-------|-------|-------|
| 1 | Foundation & Scaffolding | 10 |
| 2 | Core CRM Engine | 16 |
| 3 | Communication & Staff | 17 |
| 4 | Furniture Pack & First Modules | 12 |
| 5 | Commerce Integrations & AI | 12 |
| 6 | Polish, Performance, Beta-Ready | 9 |

**Total: 76 steps.**

## License

Proprietary. All rights reserved.
