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

| Phase | Title | Steps | Track |
|-------|-------|-------|--------|
| 1 | [Foundation & Scaffolding](phase-1-foundation/README.md) | 10 | Core |
| 2 | [Core CRM Engine](phase-2-core-crm/README.md) | 16 | Core |
| 2.5 | [Core CRM Admin UI](phase-2.5-core-admin-ui/README.md) | 6 | Core (Done) |
| 3 | [Communication & Staff](phase-3-communication-staff/README.md) | 17 | Core |
| 4 | [Furniture Pack & First Modules](phase-4-furniture-pack/README.md) | 12 | Furniture pack |
| 4.5 | [Demo Roles Setup + DR.6/7](phase-4.5-demo-roles-setup/README.md) | 7 | Core (Done) |
| 5 | [Core CRM v1 Launch](phase-5-core-crm-launch/README.md) | 13 | **Core — current focus** |
| 6 | [Furniture Pack Features (Layer 2)](phase-6-furniture-pack-features/README.md) | 8 | Furniture pack (post-launch) |
| — | [Lead Infrastructure](lead-infrastructure/README.md) | 4 | Core (side track) |
| — | [RBAC, Ownership & Self-Signup](rbac-ownership/README.md) | 5 | Core (side track) |
| — | [Dev Tools UI](dev-tools-ui/README.md) | 1 | Dev-only (side track) |
| — | [Dashboard](dashboard/README.md) | 3 | Core (side track) |
| — | [Tasks page](tasks-page/README.md) | 2 | Core (side track) |
| — | [Standard Field Overrides](standard-field-overrides/README.md) | 6 | Core (side track) |
| — | [Manual Lead Entry](manual-lead-entry/README.md) | 2 | Core (Lead Capture, 1/4) |
| — | [Bulk Import](bulk-import/README.md) | 6 | Core (Lead Capture, 2/4) |
| — | [Embeddable Widget](embeddable-widget/README.md) | 9 | Core (Lead Capture, 3/4) |
| — | [Ad Integrations](ad-integrations/README.md) | 8 | Core (Lead Capture, 4/4) |

**Total: 135 step files** (76 original plan + DR.1–7 + Phase 2.5 + Lead Infrastructure + RBAC/Ownership + Dev Tools UI + Dashboard + Tasks-page + Standard-Field-Overrides + Lead-Capture (4 tracks) side tracks).

Phase 5 was restructured to gather **all core CRM v1 work** (features + polish + hardening) so the path to a shipped template is one phase. Phase 6 was reshaped to hold **all furniture-pack-specific work** that's irrelevant to a generic CRM template adopter.

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

### Phase 5 — Core CRM v1 Launch (all core CRM: features + polish + ship-blockers)
- [5.1 Admin Dashboard overview](phase-5-core-crm-launch/step-5.1-admin-dashboard.md) — Pending — SHOULD
- [5.2 AI Chatbot in Conversations](phase-5-core-crm-launch/step-5.2-ai-chatbot.md) — Pending — NICE
- [5.3 AI Auto Follow-up Schedule](phase-5-core-crm-launch/step-5.3-ai-followups.md) — Pending — NICE
- [5.4 Reviews automation](phase-5-core-crm-launch/step-5.4-reviews-automation.md) — Pending — NICE
- [5.5 Reporting/Analytics depth](phase-5-core-crm-launch/step-5.5-reporting.md) — Pending — NICE
- [5.6 Global search](phase-5-core-crm-launch/step-5.6-search.md) — Pending — NICE
- [5.7 Performance pass](phase-5-core-crm-launch/step-5.7-performance.md) — Pending — NICE
- [5.8 RLS hardening](phase-5-core-crm-launch/step-5.8-rls-hardening.md) — Pending — **MUST**
- [5.9 Tests](phase-5-core-crm-launch/step-5.9-tests.md) — Pending — **MUST**
- [5.10 Observability](phase-5-core-crm-launch/step-5.10-observability.md) — Pending — **MUST**
- [5.11 Deployment](phase-5-core-crm-launch/step-5.11-deployment.md) — Pending — **MUST**
- [5.12 Documentation](phase-5-core-crm-launch/step-5.12-documentation.md) — Pending — **MUST**
- [5.13 Beta cutover](phase-5-core-crm-launch/step-5.13-beta-cutover.md) — Pending — **MUST**

### Phase 6 — Furniture Pack Features (Layer 2 — post-launch)
- [6.1 Marketplace abstraction](phase-6-furniture-pack-features/step-6.1-marketplace-abstraction.md) — Pending
- [6.2 Amazon adapter](phase-6-furniture-pack-features/step-6.2-marketplace-amazon.md) — Pending
- [6.3 Flipkart adapter](phase-6-furniture-pack-features/step-6.3-marketplace-flipkart.md) — Pending
- [6.4 Shopify adapter](phase-6-furniture-pack-features/step-6.4-marketplace-shopify.md) — Pending
- [6.5 Marketplace frontend](phase-6-furniture-pack-features/step-6.5-marketplace-frontend.md) — Pending
- [6.6 In-Store QR Marketing](phase-6-furniture-pack-features/step-6.6-qr-marketing.md) — Pending
- [6.7 AI Virtual Staging: backend](phase-6-furniture-pack-features/step-6.7-virtual-staging-backend.md) — Pending
- [6.8 AI Virtual Staging: frontend](phase-6-furniture-pack-features/step-6.8-virtual-staging-frontend.md) — Pending

### Lead Infrastructure (side track — pipeline-stage CRUD on the Leads kanban)
- [Step 1: Backend stage CRUD endpoints](lead-infrastructure/step-1-backend-stage-crud.md) — Pending
- [Step 2: Frontend stage editor popover](lead-infrastructure/step-2-frontend-stage-editor.md) — Pending
- [Step 3: Frontend add-stage popover](lead-infrastructure/step-3-frontend-add-stage.md) — Pending
- [Step 4: Frontend board wiring](lead-infrastructure/step-4-frontend-board-wiring.md) — Pending

### RBAC, Ownership & Self-Signup (side track — Owner-driven role management + signup branching)
- [Step 1: Normal signup creates org + assigns Owner](rbac-ownership/step-1-normal-signup-creates-org.md) — Pending
- [Step 2: Role-template registry + auto-seed on org creation](rbac-ownership/step-2-role-templates-auto-seed.md) — Pending
- [Step 3: Ownership transfer (backend + UI)](rbac-ownership/step-3-ownership-transfer.md) — Pending
- [Step 4: Frontend route guards + Access Denied page](rbac-ownership/step-4-route-guards-access-denied.md) — Pending
- [Step 5: Security audit events wiring](rbac-ownership/step-5-security-audit-events.md) — Pending

### Dev Tools UI (side track — dev-only UI affordances, env-gated)
- [Step 1: Demo logins floating pill (replaces DR.2 dropdown)](dev-tools-ui/step-1-demo-logins-floating-pill.md) — Pending

### Dashboard (side track — `/user/dashboard` landing page, role-adaptive via permissions)
- [Step 1: Backend dashboard summary endpoint](dashboard/step-1-backend-summary-endpoint.md) — Pending
- [Step 2: Frontend dashboard page](dashboard/step-2-frontend-dashboard-page.md) — Pending
- [Step 3: Sidebar entry for Dashboard](dashboard/step-3-sidebar-entry.md) — Pending

### Tasks page (side track — `/user/tasks` standalone list, permission-scoped)
- [Step 1: Backend org-wide list endpoint + filter params](tasks-page/step-1-backend-org-list-endpoint.md) — Pending
- [Step 2: Frontend tasks list page + create/edit modal](tasks-page/step-2-frontend-tasks-list-page.md) — Pending

### Standard Field Overrides (side track — Owner/Admin can customise label/required/hidden/min/max of every standard form field per org)
- [Step 1: Backend registry of overridable standard fields + permission key](standard-field-overrides/step-1-backend-registry.md) — Done
- [Step 2: Backend `standard_field_overrides` table + CRUD endpoints](standard-field-overrides/step-2-backend-overrides-table-endpoints.md) — Done
- [Step 3: Backend `/standard-fields/{entity}/render` merge endpoint](standard-field-overrides/step-3-backend-render-endpoint.md) — Done
- [Step 4: Frontend Settings → Standard Fields tab](standard-field-overrides/step-4-frontend-settings-tab.md) — Done
- [Step 5: Frontend wire overrides into Leads + Contacts modals](standard-field-overrides/step-5-frontend-wire-leads-contacts.md) — Done
- [Step 6: Frontend wire overrides into remaining form modals](standard-field-overrides/step-6-frontend-wire-remaining-entities.md) — Done

### Lead Capture & Ingestion (4 independent tracks — manager-specced 2026-05-22; build order: manual → bulk → widget → ads)

#### Manual Lead Entry (Track 1/4 — half-day, unblocks demos)
- [Step 1: Backend `lead.source` enum column + audit event](manual-lead-entry/step-1-backend-source-and-audit.md) — Done
- [Step 2: Frontend quick-add floating button + source badge on list](manual-lead-entry/step-2-frontend-quick-add-and-badge.md) — Done

#### Bulk Import (Track 2/4 — ~4½ days, unlocks competitor-CRM migrations)
- [Step 1: Backend `lead_imports` table + upload endpoint](bulk-import/step-1-backend-imports-table-and-upload.md) — Done
- [Step 2: Backend Celery import job (parse + validate + dedup + commit)](bulk-import/step-2-backend-celery-import-job.md) — Pending
- [Step 3: Backend `import_presets` per source platform](bulk-import/step-3-backend-source-platform-presets.md) — Pending
- [Step 4: Frontend upload page + source-platform selector](bulk-import/step-4-frontend-upload-page.md) — Pending
- [Step 5: Frontend column-mapping UI + preview](bulk-import/step-5-frontend-mapping-ui.md) — Pending
- [Step 6: Frontend import history + error-report download](bulk-import/step-6-frontend-import-history.md) — Pending

#### Embeddable Widget (Track 3/4 — ~6 days, customer-site lead capture)
- [Step 1: Backend `embed_keys` table + key issuance/revocation](embeddable-widget/step-1-backend-embed-keys.md) — Pending
- [Step 2: Backend public `POST /embed/leads` + rate limit](embeddable-widget/step-2-backend-public-submission-endpoint.md) — Pending
- [Step 3: Backend per-org widget config](embeddable-widget/step-3-backend-widget-config.md) — Pending
- [Step 4: Frontend Settings Embed tab (keys + config + snippet)](embeddable-widget/step-4-frontend-settings-embed-tab.md) — Pending
- [Step 5: Widget build pipeline (Vite, vanilla TS)](embeddable-widget/step-5-widget-build-pipeline.md) — Pending
- [Step 6: Widget loader + form renderer](embeddable-widget/step-6-widget-loader-and-renderer.md) — Pending
- [Step 7: Widget CSS-variable theming + class-name override](embeddable-widget/step-7-widget-theming.md) — Pending
- [Step 8: Widget spam protection (honeypot + min-time + reCAPTCHA hook)](embeddable-widget/step-8-widget-spam-protection.md) — Pending
- [Step 9: Frontend submission log + abuse signals](embeddable-widget/step-9-frontend-submission-log.md) — Pending

#### Ad Integrations (Track 4/4 — ~8 days code + 1–2 weeks of OAuth app review in parallel)
- [Step 1: Backend `integrations` table + encrypted token storage](ad-integrations/step-1-backend-integrations-table.md) — Pending
- [Step 2: Backend Google Ads OAuth flow](ad-integrations/step-2-backend-google-oauth.md) — Pending
- [Step 3: Backend Google Ads webhook + signature + retry/DLQ](ad-integrations/step-3-backend-google-webhook.md) — Pending
- [Step 4: Backend Meta OAuth + auto-subscription](ad-integrations/step-4-backend-meta-oauth-and-subscription.md) — Pending
- [Step 5: Backend Meta Lead Ads webhook + signature verification](ad-integrations/step-5-backend-meta-webhook.md) — Pending
- [Step 6: Backend cross-source dedup + lead routing (round-robin)](ad-integrations/step-6-backend-dedup-and-routing.md) — Pending
- [Step 7: Frontend Settings Integrations page (connect/disconnect + form picker)](ad-integrations/step-7-frontend-settings-integrations-page.md) — Pending
- [Step 8: Frontend field mapping editor + integration status + DLQ](ad-integrations/step-8-frontend-mapping-editor-and-status.md) — Pending

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
