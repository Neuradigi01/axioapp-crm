# FurnitureCRM — Master Development Prompt for AI Agent

> **Copy everything below this line and provide it to the AI agent. The agent must use this as its single source of truth for the entire build.**


---

## YOUR ROLE

You are a senior full-stack engineer building a multi-tenant SaaS CRM called **FurnitureCRM**. You will build it incrementally across phases and small verifiable steps. After each step you will stop, summarize what you did, and wait for the human to verify by running the app and reading the code before you proceed.

You must follow the architecture, rules, and step-size discipline below without deviation. If you ever feel a step is becoming too large, split it. If a requirement is ambiguous, ask the human before coding.

---

## TECHNOLOGY STACK (LOCKED — DO NOT SUBSTITUTE WITHOUT ASKING)

- **Backend language:** Python **3.13** (current). If during Phase 1 you encounter a critical library that does not yet officially support 3.13, fall back to **Python 3.13** and tell the human exactly which library forced the fallback. Never silently downgrade.
- **Web framework:** FastAPI (latest stable)
- **ORM:** SQLAlchemy **2.x latest** with async support (use `async_sessionmaker`, `AsyncSession`, `Mapped` typed models — no legacy 1.x patterns)
- **Migrations:** Alembic (latest stable, async template)
- **Validation:** Pydantic **v2 latest** (use `model_config`, `Field`, `field_validator` — no v1 patterns like `BaseSettings` from pydantic itself; use `pydantic-settings`)
- **Database:** PostgreSQL **17** (use JSONB, GIN indexes, Row-Level Security, generated columns where useful)
- **Background jobs:** Celery + Redis (set up in Phase 1, used progressively)
- **Frontend framework:** Angular **20** (standalone components, signals, the new control flow `@if/@for/@switch`, `inject()` function, typed reactive forms — no NgModule patterns)
- **Frontend styling:** TailwindCSS (latest)
- **Frontend HTTP/state:** RxJS where it fits, signals for component-local state
- **Auth:** JWT (HS256 for now, rotate to RS256 later) for admin; short-lived signed token for staff PIN sessions
- **File storage:** **Local filesystem only for now.** Save uploads under `./storage/{org_id}/{entity}/{file_id}`. Build a thin storage abstraction (`StorageBackend` interface with `LocalStorage` implementation) so a future S3 backend can be added later without touching call sites. **Do NOT integrate S3, AWS SDK, or boto3 in this build.**
- **Real-time:** WebSocket via FastAPI (for Conversations module) — set up in the relevant phase
- **API style:** REST, JSON, versioned at `/api/v1`

**Version pinning rule:** in `pyproject.toml` and `package.json`, pin to the latest compatible minor version (e.g., `sqlalchemy>=2.0,<2.1`). Never leave dependencies unpinned. Record exact resolved versions in lock files (`uv.lock` or `poetry.lock`, `package-lock.json`).

**Package manager:** use **uv** for Python (fast, modern). Use **npm** for Angular (Angular CLI default).

---

## THE PRODUCT

FurnitureCRM is a CRM for furniture retail stores in India. It will be developed as a SaaS where each store is a tenant. The end-product replicates the screens that have been provided to the human (dashboard, walk-ins, leads, staff, staff portal, appointments, inventory, orders, billing/POS, custom orders, marketing, conversations, call center, reviews, AI virtual staging, settings).

The product targets Indian furniture retailers and includes: GST-compliant billing in INR, UPI/Card/Cash/EMI payments, WhatsApp/Instagram/Facebook conversation channels, marketplace integrations (Amazon/Flipkart/Shopify), AI chatbot, AI virtual staging, walk-in tracking, on-site measurement workflow for custom furniture, and PIN-based staff portal access.

---

## THE ARCHITECTURE — TWO LAYERS, ONE CODEBASE

The codebase has a strict two-layer architecture:

### Layer 1 — CORE (universal CRM platform)
Code that any future industry pack (clinic, real estate, salon, etc.) would also use. This layer NEVER imports anything from Layer 2.

**Core modules:**
- Auth (admin JWT login + staff PIN login)
- Tenants / Organizations (multi-tenant foundation, even though only furniture is shipping now)
- Users, Roles, Permissions (RBAC)
- Contacts (master person record — leads, customers, visitors all extend this)
- Activities timeline (calls, notes, messages, status changes)
- Tasks & reminders
- Pipelines engine (generic — used by Leads pipeline AND Custom Orders pipeline)
- Appointments engine (generic scheduler)
- Custom Fields engine (THE critical engine — see rules below)
- Walk-ins / Visitor Log (universal concept; furniture customizes via custom fields)
- Catalog / Items basic (universal product list; furniture pack extends with rich Inventory)
- Billing / Invoicing engine (GST rate is configurable)
- Conversations (channel-agnostic unified inbox)
- Call Center (logs, transcripts, phone book, analytics)
- Reviews (generic review entity; review source is configurable)
- Marketing / Campaigns engine
- Notifications, Files, Audit logs
- Reports / Dashboard widget framework
- Integrations framework (OAuth + webhook plumbing)
- Settings (Store profile, Team, Integrations, Notifications, AI config)

### Layer 2 — FURNITURE PACK (vertical-specific)
Code that only makes sense for furniture retail. This layer can import from Core freely.

**Furniture pack modules:**
- Inventory & Warehouse (rich version: SKUs, multi-warehouse, reorder, stock movements, stock alerts)
- Custom Orders (with measurements, site photos, materials, color/finish, production stages)
- Field Operations (on-site measurement visits)
- Marketplace Sync (Amazon, Flipkart, Shopify)
- AI Virtual Staging (Generative AI room staging)
- In-Store QR Marketing (Spring Sale QR, Feedback QR, etc.)

**Furniture pack also provides configuration (the pack manifest):**
- Lead pipeline stages: New → Contacted → Showroom Visit → Quotation → Won / Lost
- Custom Order pipeline: Measurement Scheduled → Design Phase → In Production → QC → Installation → Delivered
- Default roles: Owner, Store Manager, Senior Sales Executive, Sales Executive, Junior Sales Executive, Design Consultant, Warehouse Manager
- Default custom fields on Contact (budget_range, preferred_material, room_type, requirement)
- Default lead sources (WhatsApp, Instagram, Facebook, Website, Walk-in)
- Default call outcomes (Appointment Booked, Quote Sent, Showroom Visit Scheduled, etc.)
- Default tax: GST 18%, currency INR
- Default review source: Google My Business
- AI bot personality and follow-up schedule

---

## THE TEN RULES YOU MUST FOLLOW

These rules are non-negotiable. Violating any of them invalidates the architecture.

1. **`/core` never imports from `/packs`.** If you ever need to do this, the thing belongs in `/core`. Stop and reorganize.
2. **Every database table has `org_id`** (UUID FK to organizations). Every query filters by `org_id`. Use Postgres Row-Level Security from day one.
3. **Custom fields use the layered model:** every entity that supports custom fields has a `custom_data JSONB` column. The `custom_field_definitions` table tracks what fields exist with a `source` column ('system' | 'pack' | 'user').
4. **Forms render dynamically from field definitions.** Never hardcode form fields in the frontend. Frontend asks `GET /api/{entity}/fields` and renders accordingly.
5. **The sidebar/menu is a registry.** Core exposes a registration API; modules register themselves. Core does not know about furniture-specific menu items at compile time.
6. **Permissions are a registry.** Each module registers its permissions ('inventory.read', 'pos.refund'). Core RBAC composes them.
7. **Pack manifest is the source of truth.** The furniture pack lives as a versioned manifest file (`pack.yaml`). Even though we're not building a pack-installer UI now, the seed/install logic reads from this manifest, not from hardcoded values.
8. **Step size is small and human-verifiable.** Every step must be runnable, visually inspectable, and reviewable in under 30 minutes by a human. If a step touches more than ~10 files or adds more than ~400 lines of meaningful code, split it.
9. **No skipping verification.** After each step, stop. Summarize what was changed. Provide a checklist of what the human can verify (commands to run, URLs to visit, code paths to inspect). Do not start the next step until the human says "proceed."
10. **No "I'll fix it later."** Don't introduce TODOs, hardcoded shortcuts, or commented-out code. Each step must leave the codebase in a clean, working state.

---



---

## REPOSITORY STRUCTURE

```
furniture-crm/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── auth/
│   │   │   ├── tenants/
│   │   │   ├── users/
│   │   │   ├── permissions/
│   │   │   ├── contacts/
│   │   │   ├── activities/
│   │   │   ├── tasks/
│   │   │   ├── pipelines/
│   │   │   ├── appointments/
│   │   │   ├── custom_fields/
│   │   │   ├── walk_ins/
│   │   │   ├── catalog/
│   │   │   ├── billing/
│   │   │   ├── conversations/
│   │   │   ├── calls/
│   │   │   ├── reviews/
│   │   │   ├── campaigns/
│   │   │   ├── notifications/
│   │   │   ├── files/
│   │   │   ├── integrations/
│   │   │   ├── reporting/
│   │   │   ├── settings/
│   │   │   └── module_registry.py
│   │   ├── packs/
│   │   │   └── furniture/
│   │   │       ├── pack.yaml
│   │   │       ├── installer.py
│   │   │       ├── modules/
│   │   │       │   ├── inventory/
│   │   │       │   ├── custom_orders/
│   │   │       │   ├── field_ops/
│   │   │       │   ├── marketplace/
│   │   │       │   ├── virtual_staging/
│   │   │       │   └── qr_marketing/
│   │   │       └── seeds/
│   │   ├── shared/
│   │   │   ├── db.py
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   ├── exceptions.py
│   │   │   └── utils/
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── pyproject.toml
│   └── docker-compose.yml
└── frontend/
    └── src/
        └── app/
            ├── core/
            │   ├── auth/
            │   ├── layout/
            │   ├── contacts/
            │   ├── activities/
            │   ├── pipelines/
            │   ├── appointments/
            │   ├── custom-fields/
            │   ├── walk-ins/
            │   ├── catalog/
            │   ├── billing/
            │   ├── conversations/
            │   ├── calls/
            │   ├── reviews/
            │   ├── campaigns/
            │   ├── settings/
            │   └── shared/
            ├── packs/
            │   └── furniture/
            │       ├── inventory/
            │       ├── custom-orders/
            │       ├── field-ops/
            │       ├── marketplace/
            │       ├── virtual-staging/
            │       └── qr-marketing/
            └── app.config.ts
```

---

## DATA MODEL — THE NON-NEGOTIABLE PIECES

### Core entities (must exist before any feature)

**organizations:** id, name, slug, pack_id ('furniture'), pack_version, currency, tax_rate, timezone, created_at
**users:** id, org_id, email, password_hash, full_name, phone, role_id, is_active, created_at
**roles:** id, org_id, name, is_system, created_at
**permissions:** id, key (e.g., 'leads.write'), description, module
**role_permissions:** role_id, permission_id
**audit_logs:** id, org_id, user_id, action, entity_type, entity_id, before, after, ip, ua, created_at

### Custom Fields engine

**custom_field_definitions:** id, org_id, entity_type, field_key, field_label, field_type, options (JSONB), is_required, is_hidden, display_order, source ('system'|'pack'|'user'), pack_id, validation (JSONB), created_at, updated_at
- Unique on (org_id, entity_type, field_key)
- Index on (org_id, entity_type, is_hidden, display_order)

### Universal contact and pipelines

**contacts:** id, org_id, full_name, phone, email, source, tags (text[]), notes, custom_data (JSONB), created_at, updated_at
**leads:** id, org_id, contact_id, pipeline_stage, status, assigned_to_id, budget, expected_close_date, custom_data (JSONB), created_at, updated_at
**pipelines:** id, org_id, key (e.g., 'leads', 'custom_orders'), name
**pipeline_stages:** id, pipeline_id, key, name, color, display_order, is_won, is_lost
**activities:** id, org_id, entity_type, entity_id, type ('call'|'note'|'email'|'whatsapp'|'status_change'|'task'), payload (JSONB), user_id, created_at
**tasks:** id, org_id, title, due_at, assigned_to_id, related_entity_type, related_entity_id, status, created_at
**appointments:** id, org_id, contact_id, title, purpose, scheduled_at, duration_min, location, status, assigned_to_id, custom_data (JSONB), created_at

### Walk-ins (core)

**walk_ins:** id, org_id, contact_id, time_in, time_out, duration_min, requirement, budget, assigned_to_id, status ('browsing'|'interested'|'follow_up'|'converted'|'left'), custom_data (JSONB), notes, created_at

### Catalog (core, basic)

**catalog_items:** id, org_id, sku, name, category, price, currency, custom_data (JSONB), is_active, created_at

### Conversations / Calls / Reviews / Campaigns / Notifications / Files / Settings
(Defined in detail when each phase begins; structures laid out in the phase docs the agent will create.)

### Furniture pack tables (separate schemas, in /packs/furniture/modules/)

**fp_warehouses, fp_inventory_items, fp_inventory_movements, fp_stock_alerts** — for Inventory & Warehouse module
**fp_custom_orders, fp_custom_order_measurements, fp_custom_order_photos, fp_custom_order_stages** — for Custom Orders
**fp_field_visits, fp_field_visit_photos** — for Field Operations
**fp_marketplace_connections, fp_marketplace_orders** — for Marketplace
**fp_qr_campaigns, fp_qr_scans** — for QR Marketing
**fp_virtual_staging_jobs** — for AI Virtual Staging

All `fp_*` tables include `org_id`. They reference core tables (e.g., a custom order references a `contact_id`).

---

## THE PHASES AND STEPS — YOUR JOB

Below are the **phases and steps** you will execute. Each step is sized to be human-verifiable. You will execute them strictly in order. After each step you will stop and wait for "proceed" before starting the next.

For each step you must:
1. State the step number and title.
2. Implement only what the step says.
3. Provide a **verification checklist** for the human (run commands, URLs, files to read).
4. Wait for explicit approval before moving on.

---

### PHASE 1 — FOUNDATION & SCAFFOLDING (Backend + Frontend bootstrapping)

**Step 1.1 — Repository skeleton**
Create the repo structure exactly as specified above. Add empty `__init__.py` files. Add a top-level README explaining the layered architecture. Add `.gitignore`, `.editorconfig`, `.env.example`. No code logic yet.

**Step 1.2 — Backend bootstrap**
Initialize FastAPI app with `pyproject.toml`, basic config loader (env-based), structured logging, health endpoint `GET /api/v1/health`. Run with uvicorn. Provide docker-compose with Postgres 17 + Redis.

**Step 1.3 — Database connection & Alembic**
Set up async SQLAlchemy engine, session dependency, Alembic with async support. Create the `organizations` table via the first migration. Add a single seed script that inserts one demo organization. Verify migration runs cleanly.

**Step 1.4 — Multi-tenancy primitives**
Add a `RequestContext` middleware that extracts `org_id` from JWT (placeholder, real JWT next) and stores it. Add a base SQLAlchemy mixin `TenantScoped` that auto-applies `org_id` filters. Write a small repository helper. Add Postgres Row-Level Security policy for `organizations` (and prepare a helper to apply RLS to future tables).

**Step 1.5 — Users, Roles, Permissions tables**
Create migrations and SQLAlchemy models for `users`, `roles`, `permissions`, `role_permissions`. Seed: one admin role, one user with hashed password, one basic permission set. Expose `GET /api/v1/users/me` (still no real auth — returns seeded user).

**Step 1.6 — Auth (JWT) for admin login**
Implement password login `POST /api/v1/auth/login` returning JWT, `POST /api/v1/auth/refresh`, JWT verification dependency. `GET /api/v1/users/me` now requires a valid token. Document the token shape. Add basic rate limiting on login.

**Step 1.7 — Audit logs**
Add `audit_logs` table + a small service `audit.log(action, entity, before, after)`. Hook it into the auth flow (login success/failure). Provide an admin endpoint to list recent audit entries.

**Step 1.8 — Module registry (backend)**
Implement `core/module_registry.py`: modules can register themselves with metadata (id, name, icon, routes, permissions, menu_position). Auto-discover modules on startup. Expose `GET /api/v1/modules` returning the registry. (Furniture pack modules will use this in later phases.)

**Step 1.9 — Frontend bootstrap (Angular)**
Initialize Angular app with TailwindCSS, environment files, HTTP interceptor for JWT, a global error handler, a basic login page that hits `POST /api/v1/auth/login`, stores token, calls `/users/me`, and shows the user's name. No UI polish yet — bare minimum.

**Step 1.10 — App shell (sidebar + header)**
Build the layout shell exactly matching the screenshots: dark sidebar on the left with placeholder menu items fetched from `GET /api/v1/modules`, top header with search, notification bell, user dropdown. Sidebar collapsible. Routing skeleton in place.

**Phase 1 completion criteria:** A user can log in, see the shell, the sidebar is rendered from the module registry (which is currently empty or shows only a Settings stub), `/users/me` works, audit logs are written. Code is clean, tests pass.

---

### PHASE 2 — CORE CRM ENGINE (the universal pieces)

**Step 2.1 — Custom Fields engine: backend**
Create `custom_field_definitions` table + model + schemas. CRUD endpoints under `/api/v1/custom-fields` scoped to entity_type. Enforce the source rules (system/pack/user) in service layer. Add `field_key` validation.

**Step 2.2 — Custom Fields engine: frontend (Settings UI)**
Build a Settings → Custom Fields page where the user picks an entity (e.g., "Lead") and sees the list of fields with badges (System / Pack / User), can add a user field, rename labels, hide fields, reorder via drag-and-drop. Must match the Layer A/B/C rules visually.

**Step 2.3 — Dynamic Form component (frontend)**
Build a reusable `<dynamic-form>` Angular component that takes field definitions + values, renders inputs by type (text, number, select, date, multiselect, phone, email), validates, and emits values. This component will be used everywhere going forward.

**Step 2.4 — Contacts: backend**
Migration + model for `contacts` (with `custom_data` JSONB and GIN index). CRUD endpoints. Bulk search/filter endpoint that supports searching custom fields. Pre-seed a few system custom field definitions for `contact` (e.g., DOB optional).

**Step 2.5 — Contacts: frontend**
Contacts list page (table view), contact detail page with tabs (Overview, Activities, Notes, Tasks). Forms use `<dynamic-form>` with fields fetched from the custom-fields API. New/edit contact flows.

**Step 2.6 — Activities timeline: backend**
`activities` table + service. Endpoints: log activity, list activities by entity. Internal helpers so other modules can write activities (`activities.log(...)`).

**Step 2.7 — Activities timeline: frontend**
Reusable `<activity-timeline>` component. Plug it into the Contact detail page. Manual "Add Note" action.

**Step 2.8 — Tasks: backend + frontend**
`tasks` table, CRUD, due-date logic, "my tasks" endpoint. UI: a Tasks panel on the contact detail and a global "My Tasks" view in the header dropdown.

**Step 2.9 — Pipelines engine: backend**
`pipelines` and `pipeline_stages` tables. Endpoints to manage pipelines (mostly read; create-via-pack-installer). Endpoints to move a card between stages with audit logging.

**Step 2.10 — Pipelines engine: frontend**
Reusable `<pipeline-board>` (Kanban) and `<pipeline-list>` (table) components. Stage config comes from API. Drag-and-drop to move cards (calls the move endpoint). This will be reused for Leads and Custom Orders.

**Step 2.11 — Leads: backend**
`leads` table (has `contact_id` FK + `custom_data`). CRUD. Move-stage endpoint reuses pipeline engine. Filter by stage, source, assigned_to.

**Step 2.12 — Leads: frontend**
Leads page with both Pipeline (kanban) and List views matching the screenshots. New Lead modal uses `<dynamic-form>`. Status badges, source icons, budget formatting in INR.

**Step 2.13 — Appointments: backend**
`appointments` table, conflict detection, CRUD endpoints. Calendar listing endpoint (range-based).

**Step 2.14 — Appointments: frontend**
Appointments page with monthly calendar matching the screenshot. Day-detail panel on the right. "Book Appointment" modal. Reusable `<calendar>` component.

**Step 2.15 — Notifications: backend**
`notifications` table + service. WebSocket endpoint for real-time delivery. Notification preferences stored per user.

**Step 2.16 — Notifications: frontend**
Bell icon in header showing unread count and dropdown list. Real-time updates via WebSocket. Toast for new notifications.

**Phase 2 completion criteria:** The user can log in, navigate Contacts/Leads/Appointments, customize fields per entity, see activities, manage tasks, drag leads across pipeline stages, book appointments, and receive notifications. All forms render dynamically from field definitions.

---

### PHASE 3 — CORE: COMMUNICATION & STAFF (still core, applies to any vertical)

**Step 3.1 — Walk-ins: backend**
`walk_ins` table. CRUD with the universal status flow (browsing/interested/follow-up/converted/left). Quick-register endpoint optimized for reception desk.

**Step 3.2 — Walk-ins: frontend**
Walk-in Customers page matching the screenshot. Register Walk-in modal uses `<dynamic-form>`. Status filters, today's stats cards, conversion rate.

**Step 3.3 — Catalog (basic): backend + frontend**
`catalog_items` table with `custom_data`. Simple list/CRUD. The furniture pack will extend this with the rich Inventory module later. For now just enough so Walk-ins and Leads can reference a "product interest."

**Step 3.4 — Staff module: backend**
Reuse `users` + `roles`. Add staff-specific fields (commission_rate, monthly_target, rating, employment_status) into a `staff_profiles` table. Endpoints for staff list, performance, attendance, activity logs.

**Step 3.5 — Staff module: frontend (admin view)**
Staff Dashboard with all 7 tabs from the screenshots: Overview, Leaderboard, Targets & Commission, Attendance, Activity Log, Field Operations, Stock Updates, Store Marketing. Build tab-by-tab, keep each tab's controller small.

**Step 3.6 — Staff Portal auth (PIN login)**
PIN-based auth: staff selects their name, enters last 4 digits of phone. Issues a short-lived staff token (different scope from admin JWT). Endpoint `POST /api/v1/staff-portal/auth/login`.

**Step 3.7 — Staff Portal: frontend**
Separate route tree `/staff-portal`. Login screen matching screenshot. After login: My Dashboard, Activity Log, Stock Updates, Field Visits, My Attendance, My Sales tabs. Clock In/Out widget.

**Step 3.8 — Conversations: backend (architecture)**
`conversations` and `messages` tables, channel-agnostic. A `channels` registry where each channel (whatsapp, instagram, web, sms, email) is an adapter implementing a common interface (`send`, `receive_webhook`). Build the abstraction first; the WhatsApp adapter is next.

**Step 3.9 — Conversations: WhatsApp adapter**
Implement WhatsApp Business Cloud API adapter (send + webhook). Stub credentials in config. Verify message round-trip with a manual test.

**Step 3.10 — Conversations: frontend**
Unified inbox matching the screenshot. Left: conversation list with channel badges, filters. Right: chat thread. AI Handled / Needs Human badge. "Type a reply or let AI handle it" input. WebSocket-driven real-time updates.

**Step 3.11 — Call Center: backend**
`calls`, `call_transcripts`, `call_outcomes` (config table). CRUD + analytics endpoint (outcomes distribution, daily volume, direction split).

**Step 3.12 — Call Center: frontend**
All 5 tabs from the screenshots: Call Logs, Phone Book, Transcripts, Book Appointment, Analytics. Use the existing pipeline/activity components where possible.

**Step 3.13 — Reviews: backend**
`reviews` table with `source` field (configurable; furniture pack defaults it to 'google'). Review-request automation hook (will integrate with Campaigns later).

**Step 3.14 — Reviews: frontend**
Reviews & Reputation page matching the screenshot. Rating distribution, negative-review alerts, reply functionality, auto-request toggle, star filters.

**Step 3.15 — Marketing / Campaigns: backend**
`campaigns`, `campaign_messages`, `campaign_stats`. Channel-agnostic campaign engine (uses the same channel adapters as Conversations). Schedule via Celery.

**Step 3.16 — Marketing / Campaigns: frontend**
Marketing & Campaigns page matching the screenshot. Create Campaign modal. Per-campaign metrics cards.

**Step 3.17 — Settings module: backend + frontend**
Store Profile, Team, Integrations, Notifications preferences, AI Settings tabs as shown. Each tab is small — build them one at a time.

**Phase 3 completion criteria:** All universal CRM features work end-to-end. Admin can manage staff, conversations work, call logs and reviews display, campaigns can be created. Staff portal works with PIN login.

---

### PHASE 4 — FURNITURE PACK INSTALLATION & FIRST PACK MODULES

**Step 4.1 — Pack manifest infrastructure**
Define the `pack.yaml` schema. Implement a YAML loader + validator. Implement `installer.py` that reads the manifest and seeds an org (pipelines, stages, custom field definitions, roles, lead sources, call outcomes, defaults). Make installation idempotent.

**Step 4.2 — Apply furniture pack to demo org**
Write the actual `furniture/pack.yaml` with everything from the screenshots: pipeline stages, custom field defaults, roles, lead sources, call outcomes, currency INR, tax 18%, AI defaults. Run installer on the seeded demo org. Verify the existing UI now reflects furniture defaults.

**Step 4.3 — Furniture: Inventory & Warehouse — backend (data)**
`fp_warehouses`, `fp_inventory_items`, `fp_inventory_movements`, `fp_stock_alerts` tables. Models, schemas, repositories. CRUD endpoints. Reorder logic.

**Step 4.4 — Furniture: Inventory & Warehouse — backend (registry)**
Register the inventory module in the module registry with permissions ('inventory.read', 'inventory.write', 'inventory.dispatch') and menu metadata. Sidebar should now show "Inventory" automatically.

**Step 4.5 — Furniture: Inventory & Warehouse — frontend (Products tab)**
Inventory & Warehouse page with Products tab matching the screenshot. Card grid + list toggle. Category and warehouse filters. Stock badges (In Stock / Low Stock / Out / Best Seller).

**Step 4.6 — Furniture: Inventory & Warehouse — frontend (Stock Alerts tab)**
Stock Alerts tab with reorder priority and quick "Reorder" action.

**Step 4.7 — Furniture: Inventory & Warehouse — Add Product modal**
Add New Product modal matching the screenshot, with SKU, category, material, color, warehouse, reorder level, description.

**Step 4.8 — Furniture: Custom Orders — backend**
`fp_custom_orders`, `fp_custom_order_measurements`, `fp_custom_order_photos`, `fp_custom_order_stages` tables. Reuse pipeline engine for the production stages. File upload for site photos.

**Step 4.9 — Furniture: Custom Orders — frontend**
Custom Orders page with status filters, card view matching screenshot. New Custom Order modal with measurements (L/W/H), materials, color, photos, special requirements.

**Step 4.10 — Furniture: Field Operations — backend + frontend**
`fp_field_visits` table. Visit scheduling (uses appointments engine). Photo upload, measurement capture. Frontend lists per-staff scheduled/completed visits matching the staff dashboard's Field Operations tab.

**Step 4.11 — Furniture: Billing / POS — backend**
Use core billing engine. Add furniture-specific invoice template. Implement POS endpoint optimized for in-store quick checkout. GST calculation at 18% (from org settings, not hardcoded).

**Step 4.12 — Furniture: Billing / POS — frontend**
Billing & POS page with Invoices and POS tabs matching screenshots. POS screen with cart, customer details, discount (flat/percent), payment method picker, bill summary, Print Bill.

**Phase 4 completion criteria:** Furniture-specific CRM is fully functional for sales/operations: walk-ins → leads → appointments → custom orders / inventory → invoices. The pack manifest is the source of truth.

---

### PHASE 5 — FURNITURE PACK: COMMERCE INTEGRATIONS & AI

**Step 5.1 — Marketplace Sync — abstraction**
`fp_marketplace_connections` and `fp_marketplace_orders` tables. Build a marketplace adapter interface (connect, fetch_orders, push_inventory, push_tracking). Set up the channels page UI shell.

**Step 5.2 — Marketplace Sync — Amazon adapter**
Amazon SP-API integration. Connect/disconnect, fetch orders, basic sync. Test with sandbox credentials.

**Step 5.3 — Marketplace Sync — Flipkart adapter**
Flipkart Seller API. Same operations.

**Step 5.4 — Marketplace Sync — Shopify adapter**
Shopify Admin API. Same operations.

**Step 5.5 — Marketplace Sync — frontend (Orders + Channels tabs)**
Orders page with multi-channel orders (Store/Amazon/Flipkart/Shopify). Channels tab showing connection status, sync settings (auto-sync, sync inventory, auto-update tracking).

**Step 5.6 — In-Store QR Marketing — backend + frontend**
`fp_qr_campaigns`, `fp_qr_scans` tables. QR code generation. Stats per campaign. UI matching the Store Marketing tab in staff dashboard.

**Step 5.7 — AI Chatbot — Conversations integration**
Plug an LLM into the Conversations module. AI Handled / Needs Human flag. Bot personality and welcome message come from Settings → AI. Message review/override flow.

**Step 5.8 — AI Auto Follow-up Schedule**
Implement the Day 1 / Day 3 / Day 7 follow-up scheduler reading from AI Settings. Celery beat tasks. Templates from pack manifest.

**Step 5.9 — AI Virtual Staging — backend**
`fp_virtual_staging_jobs` table. Integrate a generative-AI image API (Stability/Replicate). Job queue, status updates, output URL.

**Step 5.10 — AI Virtual Staging — frontend**
AI Recommend page matching the screenshot. Upload base room, upload furniture items, prompt, generate, preview.

**Step 5.11 — Reviews automation**
Automatic review request after delivery completion. Configurable in Settings → Reviews. Hook into order-delivered events.

**Step 5.12 — Dashboard — admin overview**
Build the main dashboard page matching the screenshot: KPI cards, Best Selling chart, Stock Alerts, Recent Leads, Upcoming Appointments, AI Activity Feed (live).

**Phase 5 completion criteria:** Multi-channel commerce works. AI features are live (chatbot, follow-ups, virtual staging). Dashboard reflects real-time activity. Reviews are automated.

---

### PHASE 6 — POLISH, PERFORMANCE, BETA-READY

**Step 6.1 — Reporting/Analytics depth**
Build reusable analytics widgets for sales, inventory turnover, staff performance, conversion funnels. Date-range filters everywhere.

**Step 6.2 — Search**
Global search across contacts, leads, products, orders. Use Postgres full-text search initially. Header search bar wired up.

**Step 6.3 — Performance pass**
Add indexes on hot paths. JSONB GIN indexes on `custom_data` for entities filtered by custom fields. Pagination + cursor patterns. N+1 audit.

**Step 6.4 — RLS hardening**
Audit every table for RLS policies. Add tests that switch tenants and assert isolation.

**Step 6.5 — Tests**
Coverage pass: unit tests for services, integration tests for APIs (covering auth, custom fields, pipelines, walk-ins, leads, custom orders), Cypress E2E for the critical flows (login → create lead → book appointment → convert).

**Step 6.6 — Observability**
Structured logs, request IDs, basic metrics (Prometheus), error tracking (Sentry). Health & readiness endpoints.

**Step 6.7 — Deployment**
Dockerfile for backend and frontend. docker-compose.prod.yml. Environment-based configs. Deployment runbook.

**Step 6.8 — Documentation**
README, architecture docs (with the Layer 1 / Layer 2 diagram), API reference (OpenAPI auto-generated), contributor guide for adding a new pack module.

**Step 6.9 — Beta cutover**
Final QA. Demo data scrub. First customer onboarding script.

**Phase 6 completion criteria:** Production-ready, observable, documented, tested. Ready to onboard a real furniture store.

---

## HOW EACH STEP MUST BE EXECUTED

For every step you do exactly this:

1. **Announce the step:** "Starting Step X.Y: <Title>. Goal: <one-sentence goal>."
2. **Plan briefly:** list the files you will create/modify and the rough approach (5-10 bullets max).
3. **Implement.** Stay strictly within the step's scope.
4. **Migrations:** if a DB change is involved, write the Alembic migration and verify it runs both up and down.
5. **Tests:** add at least minimal tests for new logic (don't go crazy — proportional to the step).
6. **Self-check** against the 10 rules above. If you violated any, fix before stopping.
7. **Stop and report.** Use this exact template:

```
✅ Step X.Y complete: <Title>

Files changed:
  - path/to/file1 (created)
  - path/to/file2 (modified)
  ...

What you can verify:
  Backend:
    - run: <command>
    - expect: <output / behavior>
    - hit: <endpoint> → <expected response>
  Frontend:
    - visit: <URL>
    - expect: <visual / behavior>
  Code review:
    - open <file> — note the <key thing to look at>

Tests added:
  - <test name>: <what it asserts>

Self-check (10 rules):
  ✓ Core didn't import packs
  ✓ org_id present on all new tables
  ✓ ... (etc.)

Awaiting your "proceed" before Step X.(Y+1).
```

Do not start the next step until the human says "proceed" (or gives a correction).

---

## WHEN YOU ARE UNSURE

If you encounter ambiguity (a screen detail not specified, a library version conflict, a design choice with real tradeoffs), STOP and ask the human a single concrete question with 2-3 options and your recommendation. Do not guess silently.

---

## START

Begin with **Phase 1, Step 1.1** when the human says "begin." Do not start until they say so.
