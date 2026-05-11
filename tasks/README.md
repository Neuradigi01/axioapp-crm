# FurnitureCRM — Task Plan

This folder is the **single source of truth for every step** of the FurnitureCRM build. The master agent prompt that defined the project lives at the repo root: [`furniture-crm-agent-prompt.md`](../furniture-crm-agent-prompt.md). This `tasks/` tree breaks that prompt into 76 individually verifiable step files across 6 phases.

## How to use this folder

1. **Always work the next pending step in order.** Never skip ahead, never batch.
2. Open the step file. It is self-contained — goal, scope, files to touch, DB changes, tests, verification checklist, 10-rule self-check.
3. Implement only what the step file says. Stop when done.
4. Update the step's status in this README (Pending → In Progress → Done).
5. Wait for the human to say "proceed" before opening the next step file.

## The 10 non-negotiable rules (from the master prompt)

1. `app/core/` never imports from `app/packs/`.
2. Every DB table has `org_id` (UUID FK to organizations). Every query filters by `org_id`. Postgres RLS from day one.
3. Custom fields use the layered model — every entity that supports them has a `custom_data` JSONB column; `custom_field_definitions` has a `source` column (`system` | `pack` | `user`).
4. Forms render dynamically from field definitions. Frontend asks `GET /api/{entity}/fields` and renders.
5. Sidebar/menu is a registry — modules register themselves; core does not know about furniture-specific menu items at compile time.
6. Permissions are a registry — each module registers its permissions; core RBAC composes them.
7. Pack manifest (`pack.yaml`) is the source of truth for furniture defaults. Seed/install logic reads from it.
8. Step size is small and human-verifiable — every step runnable, visually inspectable, reviewable in under 30 minutes. > ~10 files or > ~400 lines → split it.
9. No skipping verification. After each step: stop, summary, checklist, wait for "proceed."
10. No "I'll fix it later" — no TODOs, hardcoded shortcuts, or commented-out code.

## Locked stack

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.x async, Alembic async, Pydantic v2 + pydantic-settings, PostgreSQL 17 (JSONB, GIN, RLS), Celery + Redis, package manager `uv`.
- **Frontend:** Angular 20+ standalone (signals, new control flow, `inject()`, typed reactive forms), TailwindCSS for new pages. Existing auth pages keep PrimeNG/Material per agreed exception.
- **Auth:** JWT HS256 admin (existing) + short-lived staff PIN token (Phase 3).
- **File storage:** Local filesystem under `./storage/{org_id}/{entity}/{file_id}` behind a `StorageBackend` interface. No S3/boto3 in this build.
- **API:** REST, JSON, versioned at `/api/v1`.

## Reuse-vs-restructure (agreed exceptions)

- **Auth logic preserved:** existing JWT, password hashing, login history, refresh, forgot/reset password, and all three 2FA methods (Google Authenticator + Email OTP + SMS OTP) are kept and re-housed under `api/src/app/core/auth/` (backend). The Step 1.5 / 1.6 files describe the migration.
- **`features/admin/` is UNTOUCHED indefinitely.** Legacy template admin panel; not part of FurnitureCRM. No step modifies, deletes, or repurposes anything inside `app/src/app/features/admin/`.
- **`features/user/` hosts the FurnitureCRM frontend.** All Layer 1 (`core/`) and Layer 2 (`packs/furniture/`) frontend module code lives under `app/src/app/features/user/core/...` and `app/src/app/features/user/packs/furniture/...`. All seven FurnitureCRM roles (Owner, Store Manager, Senior/Sales/Junior Sales Executive, Design Consultant, Warehouse Manager) log in via the user-login button and land at `/user/...`.
- **Staff Portal at `/staff-portal`** is a separate top-level route tree, not under `features/user/`. Built in Phase 3, Step 3.7.
- **Backend layout** stays as the master doc specifies: `api/src/app/core/...` and `api/src/app/packs/furniture/...`. No "user side" / "admin side" distinction on backend.
- **Existing auth pages keep PrimeNG/Material visuals.** All new pages use Tailwind only.
- **Folders renamed lowercase:** `API/` → `api/`, `APP/` → `app/`. `Flutter/` untouched.
- **CLAUDE.md** already updated to FurnitureCRM-specific rules.

---

## Phase index

| Phase | Title | Steps | Status |
|-------|-------|-------|--------|
| 1 | [Foundation & Scaffolding](phase-1-foundation/README.md) | 10 | Pending |
| 2 | [Core CRM Engine](phase-2-core-crm/README.md) | 16 | Pending |
| 3 | [Communication & Staff](phase-3-communication-staff/README.md) | 17 | Pending |
| 4 | [Furniture Pack & First Modules](phase-4-furniture-pack/README.md) | 12 | Pending |
| 5 | [Commerce Integrations & AI](phase-5-commerce-ai/README.md) | 12 | Pending |
| 6 | [Polish, Performance, Beta-Ready](phase-6-polish-launch/README.md) | 9 | Pending |

**Total: 76 steps.**

## All-steps quick index

### Phase 1 — Foundation
- [1.1 Repository skeleton](phase-1-foundation/step-1.1-repo-skeleton.md) — Pending
- [1.2 Backend bootstrap](phase-1-foundation/step-1.2-backend-bootstrap.md) — Pending
- [1.3 Database connection & Alembic](phase-1-foundation/step-1.3-db-alembic.md) — Pending
- [1.4 Multi-tenancy primitives](phase-1-foundation/step-1.4-multi-tenancy.md) — Pending
- [1.5 Users, Roles, Permissions](phase-1-foundation/step-1.5-users-roles-permissions.md) — Pending
- [1.6 Auth (JWT) for admin login](phase-1-foundation/step-1.6-auth-jwt.md) — Pending
- [1.7 Audit logs](phase-1-foundation/step-1.7-audit-logs.md) — Pending
- [1.8 Module registry (backend)](phase-1-foundation/step-1.8-module-registry.md) — Pending
- [1.9 Frontend bootstrap (Angular)](phase-1-foundation/step-1.9-frontend-bootstrap.md) — Pending
- [1.10 App shell (sidebar + header)](phase-1-foundation/step-1.10-app-shell.md) — Pending

### Phase 2 — Core CRM Engine
- [2.1 Custom Fields engine: backend](phase-2-core-crm/step-2.1-custom-fields-backend.md) — Pending
- [2.2 Custom Fields engine: frontend](phase-2-core-crm/step-2.2-custom-fields-frontend.md) — Pending
- [2.3 Dynamic Form component](phase-2-core-crm/step-2.3-dynamic-form.md) — Pending
- [2.4 Contacts: backend](phase-2-core-crm/step-2.4-contacts-backend.md) — Pending
- [2.5 Contacts: frontend](phase-2-core-crm/step-2.5-contacts-frontend.md) — Pending
- [2.6 Activities timeline: backend](phase-2-core-crm/step-2.6-activities-backend.md) — Pending
- [2.7 Activities timeline: frontend](phase-2-core-crm/step-2.7-activities-frontend.md) — Pending
- [2.8 Tasks: backend + frontend](phase-2-core-crm/step-2.8-tasks.md) — Pending
- [2.9 Pipelines engine: backend](phase-2-core-crm/step-2.9-pipelines-backend.md) — Pending
- [2.10 Pipelines engine: frontend](phase-2-core-crm/step-2.10-pipelines-frontend.md) — Pending
- [2.11 Leads: backend](phase-2-core-crm/step-2.11-leads-backend.md) — Pending
- [2.12 Leads: frontend](phase-2-core-crm/step-2.12-leads-frontend.md) — Pending
- [2.13 Appointments: backend](phase-2-core-crm/step-2.13-appointments-backend.md) — Pending
- [2.14 Appointments: frontend](phase-2-core-crm/step-2.14-appointments-frontend.md) — Pending
- [2.15 Notifications: backend](phase-2-core-crm/step-2.15-notifications-backend.md) — Pending
- [2.16 Notifications: frontend](phase-2-core-crm/step-2.16-notifications-frontend.md) — Pending

### Phase 3 — Communication & Staff
- [3.1 Walk-ins: backend](phase-3-communication-staff/step-3.1-walkins-backend.md) — Pending
- [3.2 Walk-ins: frontend](phase-3-communication-staff/step-3.2-walkins-frontend.md) — Pending
- [3.3 Catalog (basic)](phase-3-communication-staff/step-3.3-catalog.md) — Pending
- [3.4 Staff module: backend](phase-3-communication-staff/step-3.4-staff-backend.md) — Pending
- [3.5 Staff module: frontend](phase-3-communication-staff/step-3.5-staff-frontend.md) — Pending
- [3.6 Staff Portal auth (PIN)](phase-3-communication-staff/step-3.6-staff-portal-auth.md) — Pending
- [3.7 Staff Portal: frontend](phase-3-communication-staff/step-3.7-staff-portal-frontend.md) — Pending
- [3.8 Conversations: backend (architecture)](phase-3-communication-staff/step-3.8-conversations-architecture.md) — Pending
- [3.9 Conversations: WhatsApp adapter](phase-3-communication-staff/step-3.9-conversations-whatsapp.md) — Pending
- [3.10 Conversations: frontend](phase-3-communication-staff/step-3.10-conversations-frontend.md) — Pending
- [3.11 Call Center: backend](phase-3-communication-staff/step-3.11-call-center-backend.md) — Pending
- [3.12 Call Center: frontend](phase-3-communication-staff/step-3.12-call-center-frontend.md) — Pending
- [3.13 Reviews: backend](phase-3-communication-staff/step-3.13-reviews-backend.md) — Pending
- [3.14 Reviews: frontend](phase-3-communication-staff/step-3.14-reviews-frontend.md) — Pending
- [3.15 Campaigns: backend](phase-3-communication-staff/step-3.15-campaigns-backend.md) — Pending
- [3.16 Campaigns: frontend](phase-3-communication-staff/step-3.16-campaigns-frontend.md) — Pending
- [3.17 Settings module](phase-3-communication-staff/step-3.17-settings.md) — Pending

### Phase 4 — Furniture Pack
- [4.1 Pack manifest infrastructure](phase-4-furniture-pack/step-4.1-pack-manifest.md) — Pending
- [4.2 Apply furniture pack to demo org](phase-4-furniture-pack/step-4.2-apply-pack.md) — Pending
- [4.3 Inventory: backend (data)](phase-4-furniture-pack/step-4.3-inventory-data.md) — Pending
- [4.4 Inventory: backend (registry)](phase-4-furniture-pack/step-4.4-inventory-registry.md) — Pending
- [4.5 Inventory: Products tab](phase-4-furniture-pack/step-4.5-inventory-products.md) — Pending
- [4.6 Inventory: Stock Alerts tab](phase-4-furniture-pack/step-4.6-inventory-alerts.md) — Pending
- [4.7 Inventory: Add Product modal](phase-4-furniture-pack/step-4.7-inventory-add-product.md) — Pending
- [4.8 Custom Orders: backend](phase-4-furniture-pack/step-4.8-custom-orders-backend.md) — Pending
- [4.9 Custom Orders: frontend](phase-4-furniture-pack/step-4.9-custom-orders-frontend.md) — Pending
- [4.10 Field Operations](phase-4-furniture-pack/step-4.10-field-ops.md) — Pending
- [4.11 Billing/POS: backend](phase-4-furniture-pack/step-4.11-billing-backend.md) — Pending
- [4.12 Billing/POS: frontend](phase-4-furniture-pack/step-4.12-billing-frontend.md) — Pending

### Phase 5 — Commerce & AI
- [5.1 Marketplace abstraction](phase-5-commerce-ai/step-5.1-marketplace-abstraction.md) — Pending
- [5.2 Amazon adapter](phase-5-commerce-ai/step-5.2-marketplace-amazon.md) — Pending
- [5.3 Flipkart adapter](phase-5-commerce-ai/step-5.3-marketplace-flipkart.md) — Pending
- [5.4 Shopify adapter](phase-5-commerce-ai/step-5.4-marketplace-shopify.md) — Pending
- [5.5 Marketplace frontend](phase-5-commerce-ai/step-5.5-marketplace-frontend.md) — Pending
- [5.6 In-Store QR Marketing](phase-5-commerce-ai/step-5.6-qr-marketing.md) — Pending
- [5.7 AI Chatbot in Conversations](phase-5-commerce-ai/step-5.7-ai-chatbot.md) — Pending
- [5.8 AI Auto Follow-up Schedule](phase-5-commerce-ai/step-5.8-ai-followups.md) — Pending
- [5.9 AI Virtual Staging: backend](phase-5-commerce-ai/step-5.9-virtual-staging-backend.md) — Pending
- [5.10 AI Virtual Staging: frontend](phase-5-commerce-ai/step-5.10-virtual-staging-frontend.md) — Pending
- [5.11 Reviews automation](phase-5-commerce-ai/step-5.11-reviews-automation.md) — Pending
- [5.12 Admin Dashboard overview](phase-5-commerce-ai/step-5.12-admin-dashboard.md) — Pending

### Phase 6 — Polish & Launch
- [6.1 Reporting/Analytics depth](phase-6-polish-launch/step-6.1-reporting.md) — Pending
- [6.2 Global search](phase-6-polish-launch/step-6.2-search.md) — Pending
- [6.3 Performance pass](phase-6-polish-launch/step-6.3-performance.md) — Pending
- [6.4 RLS hardening](phase-6-polish-launch/step-6.4-rls-hardening.md) — Pending
- [6.5 Tests](phase-6-polish-launch/step-6.5-tests.md) — Pending
- [6.6 Observability](phase-6-polish-launch/step-6.6-observability.md) — Pending
- [6.7 Deployment](phase-6-polish-launch/step-6.7-deployment.md) — Pending
- [6.8 Documentation](phase-6-polish-launch/step-6.8-documentation.md) — Pending
- [6.9 Beta cutover](phase-6-polish-launch/step-6.9-beta-cutover.md) — Pending

---

## Step file structure

Every step file follows the same template:

```
# Step X.Y — Title

**Goal:** one sentence.
**Phase:** X — <phase title>
**Depends on:** prior step ids
**Status:** Pending | In Progress | Done

## Scope
In-scope: ...
Out of scope: ...

## Files to touch
- path/to/file (created | modified)

## Plan
1. ...

## DB changes / migrations
...

## Tests to add
...

## Verification checklist
Backend: ...
Frontend: ...
Code review: ...

## Self-check (10 rules)
- [ ] Core didn't import packs
- [ ] org_id present on all new tables
- [ ] ...

## Stop & report
Use the master-prompt stop template; await "proceed".
```
