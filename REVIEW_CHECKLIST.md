# End-to-End Functionality Review Checklist — Core CRM

## 1. Purpose

This file is the master list of **every user-facing functionality in Core CRM**, grouped into modules and ordered so a reviewer can walk the whole product front-to-back. Each functionality gets reviewed **once**, end-to-end, through the full layer chain:

> **UI page component → Angular service → HTTP interceptor + route guards → `/api/v1` FastAPI router → service → data-access (DAL) → SQLAlchemy async session → PostgreSQL (with Row-Level Se

curity)** — plus whatever else the flow touches: Celery/Redis jobs, WebSockets, local file storage, Stripe, WhatsApp (Cloud API / Baileys sidecar), Google & Meta OAuth and webhooks, Gmail/Microsoft OAuth, Firebase, and the AI provider.

A review is not just "does it work". Each item is judged on **correctness, security, performance, code organization, and design fit** — the last one asking whether the feature is even the *right shape* compared to how mature CRMs solve the same problem. When an item is done, its status flips and it is never re-reviewed unless the code changes.

---

## 2. How to use this file — for the human

1. **Pick the next item.** Either scan for the first row marked `NOT_REVIEWED`, or just ask the agent: *"next pending item"* / *"review E.4"*.
2. **Read what the agent presents.** It will give you a full trace plus its own observations, security, performance, organization, and design-fit findings — then stop.
3. **Decide and record.** Flip that row's `Status` to:
   - `REVIEWED` — you're happy, nothing to change.
   - `NEEDS_FIX` — something needs work. Add a one-line note in the `Notes` column (e.g. *"no org scoping on export query — see security finding"*).
4. **Move on.** The agent will not start the next item until you ask.

At **module boundaries** the agent will pause twice more than usual — once *before* the module's first item (to question the module's overall shape) and once *after* its last item (to confirm the module now hangs together). Those two passes are where the expensive structural decisions get made, so read them carefully; approving a wrong shape there costs far more later.

---

## 3. How to use this file — for the AI agent (the review protocol)

### 3.1 Why the protocol is shaped this way

Reviewing items one by one only ever answers *"is what's built, built correctly?"*. It can never catch a **wrong shape** — a missing capability, two features that are really one, or a feature living in the wrong place. A building inspector who only checks each room's wiring will never notice the house has no kitchen. So per-item review is **bookended** by bird's-eye passes that judge shape, not lines.

Every shape judgement is made against how **mature products in this domain** solve the same problem. The benchmarks for this project:

| Area | Benchmark products |
|------|--------------------|
| Core CRM (contacts, leads, pipelines, activities) | HubSpot, Zoho CRM, Salesforce, Pipedrive, Close |
| Omni-channel inbox & WhatsApp business messaging | Intercom, Wati, Interakt, Respond.io |
| Automation & multi-step workflows | HubSpot Workflows, ActiveCampaign, Zapier |
| Campaigns & broadcast email | Mailchimp, ActiveCampaign, Klaviyo |
| SaaS subscription billing | Stripe Billing, Chargebee |

### 3.2 Module-level protocol (the bird's-eye bookends)

Each lettered section (A, B, C …) is one module. A module is reviewed **as a whole**, in four phases.

#### PHASE 0 — Whole-project bird's-eye pass (run ONCE, before any module)

**What this means:** before reviewing anything, step back and look at the entire product the way a new CTO would on day one — not at the code, at the *product*.

**Why it matters:** if a whole capability is missing or two modules are really one, you want to know that before spending 300 item reviews inside the current structure. It's cheaper to redraw the map before the expedition than halfway up the mountain.

Produce:
- What major capabilities should a mature product in this domain have? Which exist here, which are **missing**, which are **redundant** or **mis-placed**?
- Is the module map itself right — should any modules merge, split, or move?
- The 3–8 biggest structural calls, each with its impact across UI / API / DB.

Then **stop and wait** for the human's decisions before starting module A.

#### PHASE 1 — Opening bird's-eye pass (before a module's first `NOT_REVIEWED` item)

**What this means:** judge the module's *shape* before you look at any of its lines.

**Why it matters:** it's the difference between "this door is well-hung" and "this room has no door". Example of the kind of call this catches: *the Reviews module lets you reply to and escalate a review, but has no way to **request** one — yet asking customers for reviews is the single most-used feature in every competing product. That's a missing sub-feature no per-item review of "reply to review" would ever surface.*

Answer, in plain language:
- **What sub-features should this module have?** Is each the right shape, in the right place, correctly modelled?
- **What's missing?** What's **redundant** — two things that are really one?
- **What should be merged / split / moved / added / removed?**
- Do **not** assume the current structure is correct — question it.

Make the big structural calls **here**, spell out their full impact across every layer (UI / API / DB), then **present and WAIT for the human's approval** before touching any item.

#### PHASE 2 — Per-item passes

Walk each `NOT_REVIEWED` item, **one at a time**, through §3.3. **Stop after each one** and wait for the human.

#### PHASE 3 — Closing bird's-eye pass (after the module's last item)

Re-do the whole-module review — design fit, code organization, security, performance — now that you've seen every part. Confirm the module holds together as **one coherent whole**, list anything the per-item passes revealed that changes the module-level picture, then move to the next module.

### 3.3 Per-item process

When asked for the next pending item or a specific ID:

1. **Find the item** — the first `NOT_REVIEWED` row, or the ID requested.
2. **Explore fresh.** Do **not** rely on remembered paths or on what this file says. Re-search, re-read, re-trace from scratch — the code may have changed since this checklist was written. This file tells you *what* to review, never *where* the code is today.
3. **Present the functionality end-to-end in EXACTLY this structure:**

   - **What it does** — 1–2 lines of plain English, from the user's point of view.
   - **Entry point** — the route, button, or trigger that starts the flow.
   - **Frontend / client trace** — every component, service, guard, and interceptor touched, each with file path + the relevant method names.
   - **Backend / server trace** — every endpoint hit, then service → data-access → the actual DB queries, with file paths + method names.
   - **Database tables touched** — and whether each is read, written, or both.
   - **Other systems** — Celery jobs, Redis, WebSockets, file storage, Stripe, WhatsApp, OAuth/webhooks, AI, any third-party API.
   - **What to verify** — a short checklist of correctness checks *specific to this functionality*.
   - **Observations & suggested improvements** — your own assessment: bugs, race conditions, redundant queries, missing validation, UX holes, convention violations, refactor opportunities. Each with a **severity** (critical / medium / low / cosmetic) and a one-line recommendation, citing `file:line`. If nothing stands out, write "none" — do not pad.
   - **SECURITY audit** — see §3.4.
   - **PERFORMANCE audit** — see §3.5.
   - **CODE-ORGANIZATION audit** — see §3.6.
   - **DESIGN FIT** — see §3.7.

4. **Use clickable links with line numbers** — `[router.py:42](API/src/app/core/leads/router.py#L42)`.
5. **Keep the trace factual; put opinions in the Observations section.** Opine freely there, but always cite `file:line` — never vague advice.
6. **STOP after ONE functionality.** Do not start the next until asked.

### 3.4 The SECURITY lens

**What this means:** look at the flow the way an attacker would, and say what they could actually *do* — not just name a category.

**Why it matters:** this product is **multi-tenant**. Every organisation's data sits in the same tables, separated only by an `org_id` column, Row-Level Security policies, and the scoping in each query. One query that forgets `org_id` means Company A reads Company B's customer list. That is the single highest-consequence bug class in this codebase.

Walk every one of these:

- **Authorization & tenant scoping (IDOR).** Can user A reach user B's — or org A reach org B's — data? Is **every** query scoped to the tenant *and*, where relevant, the record owner? Is the `org_id` taken from the **JWT/`TenantContextMiddleware`**, never from a client-supplied field? *Concretely: if changing `/api/v1/leads/{id}` to another org's UUID returns that lead, that's a critical IDOR.*
- **Authentication & route guards.** Is the endpoint actually authenticated? Does the frontend `permissionGuard` have a matching **server-side** permission check? (A hidden button is not access control — the endpoint is.)
- **Input validation.** Are Pydantic schemas strict? Any unbounded strings, unchecked enums, mass-assignment of fields the user shouldn't set?
- **Injection of every kind** — SQL (raw `text()` with interpolation), SSRF (any URL the *server* fetches: webhooks, image fetches, OAuth redirects), XSS (any HTML rendered from user input — template bodies especially), command and template injection (merge-field/variable rendering).
- **Secret handling.** Tokens/API keys encrypted at rest, masked in responses and logs, never returned to the client.
- **Rate limiting / abuse / DoS.** Especially on **public, unauthenticated** endpoints — widget submission, tracking pixels, quick-link redirects, webhooks, public property pages.
- **Sensitive data leaking** into responses, error messages, or logs.

For each risk give: a **concrete exploit scenario** ("an attacker who … could …"), a **severity**, and a **fix**. If the flow is clean, say **why** it's clean (e.g. *"every read goes through `list_leads(db, org_id=ctx.org_id)` and RLS is active on `tbl_leads`, so a forged id returns 404"*) — never just "none".

### 3.5 The PERFORMANCE lens

**What this means:** what this costs today with 50 records, and what it costs at 50,000.

**Why it matters:** almost every performance bug here is invisible in development and fatal in production. A page that runs one extra query per row is instant with 10 contacts and times out with 10,000.

Walk every one of these:

- **N+1 queries** — any DB call inside a loop. *Before: 1 query for 200 leads + 1 per lead for its owner = 201 queries. After: one `selectinload(Lead.owner)` = 2 queries.*
- **Missing indexes** on columns used in `WHERE`, `ORDER BY`, or joins — especially `org_id` composites.
- **Unbounded result sets** — any list endpoint with no `LIMIT`/pagination cap.
- **3+ sequential reads** that should be one query or one batched `IN`.
- **Avoidable awaits on hot paths** — sequential `await`s that could run concurrently.
- **Heavy synchronous work** that belongs in a Celery job (file parsing, PDF/ZIP generation, bulk sends, external API fan-out).
- **Oversized payloads** — returning full rows/blobs where the UI shows three fields.
- **Obvious caching wins.**

**Quantify** it ("at 10k rows this issues 10k queries and returns ~40 MB"), give a severity and a fix. Where it's already fine, **confirm that and say why** — don't just write "none". The project's own soft target is ≈2–3 DB round-trips per request.

### 3.6 The CODE-ORGANIZATION lens

**What this means:** is this code arranged the way a professional, well-run codebase would arrange it — and **is the current layout actually correct**? Don't assume it is; question it.

**Why it matters:** this project has **documented** conventions, and CI enforces two of them. Drift isn't a matter of taste here — it breaks builds and, more importantly, it's how a codebase slowly becomes unmaintainable.

Judge against the project's own rulebooks — [`CLAUDE.md`](CLAUDE.md) (the 10 non-negotiable rules + the Router→Service→DAL spec), [`tasks/README.md`](tasks/README.md), and `API/docs/DATABASE_RULES.md`:

- **Is each file in the right layer?** The contract is strict:
  - `router.py` — endpoints only. Never runs SQL, never touches transactions, never imports another module's DAL.
  - `service.py` — business logic, permissions, validation, and the **only** layer allowed to call `commit / rollback / flush / refresh`.
  - `data_access.py` — pure CRUD. Never commits, never holds business logic, never imports upward.
  - *Before: a router that builds a `select()` and calls `db.execute()` itself. After: router calls `service.list_x()`, which calls `data_access.select_x()`.*
- **Core never imports from packs.** `app/core/**` must not import `app/packs/**`. If it needs to, the thing belongs in core.
- **Tenancy conventions.** Every table `tbl_<snake_name>` (pack tables `tbl_fp_<name>`), every table has `org_id`, every query filters by it.
- **Custom fields & dynamic forms.** Entities that support them use the `custom_data` JSONB column; forms render from `GET /{entity}/fields` rather than hardcoding fields.
- **Registries, not hardcoding.** Sidebar entries and permission keys register themselves per module; core must not know pack specifics at compile time.
- **Duplication and twisted abstractions.** Is there near-duplicate logic to consolidate? An abstraction bent out of shape to serve two callers?
- **Naming.** Are public names self-descriptive?

When something is misplaced or duplicated, say **exactly where it should live and why that's cleaner**. When it's already right, **confirm it and say why**.

### 3.7 The DESIGN-FIT lens (whole-product)

**What this means:** §3.6 asks "is this built correctly *inside* the current design?" — this one questions **the design itself**.

**Why it matters:** the project is in active development with no external users locked into the current shape, so proposing a different data model, a moved responsibility, a merged-or-split entity, or a reworked flow is **fully in scope here, not overreach**.

Step back and judge the feature as a *product decision*, against both the rest of this platform and the benchmark products in §3.1:

- Is it the **right shape** — right data model, right flow, right place in the product?
- Does it duplicate something the platform already does elsewhere? *(This codebase already has three separate A/B testing implementations and two separate email open/click tracking systems — exactly the kind of thing this lens exists to catch.)*
- Would a user coming from HubSpot/Zoho/Intercom find this where they expect it, working the way they expect?

If the design is already right, say so and why. If not, **name the better shape** and spell out what would change across UI / API / DB to get there.

---

## 4. Status legend

| Status | Meaning |
|--------|---------|
| `NOT_REVIEWED` | Not looked at yet. This is the starting state for every row. |
| `REVIEWING` | Currently being reviewed — the agent has presented it and the human hasn't decided yet. |
| `REVIEWED` | Reviewed end-to-end and accepted. Nothing further needed. |
| `NEEDS_FIX` | Reviewed and a problem was found. The `Notes` column says what, in one line. |

---

## 5. Master Index

29 modules, ordered as a walk through the product: entry → core value → communication → engagement → insight → money → people → platform → vertical packs.

---

### A. Authentication & Account Access

Login, signup, password, email verification, all three 2FA methods, sessions, and the guards/interceptor that protect every other page. Backend: `API/src/app/core/auth/` plus preserved legacy auth under `API/src/routers/` + `API/src/services/`. Frontend: `APP/src/app/features/accounts/` and `APP/src/app/features/user/core/auth/`.

**Known flags at map time:** there is no working "resend verification email" action (the notice page only tells the user to log in again); and the layered (non-admin) login path never inspects a 2FA challenge — only the admin/legacy path routes to the two-factor page.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| A.1 | User login (email + password) | NOT_REVIEWED | |
| A.2 | Admin login (legacy admin pool) | NOT_REVIEWED | |
| A.3 | Self-signup / register | NOT_REVIEWED | |
| A.4 | Pre-signup contact verification OTP — email | NOT_REVIEWED | |
| A.5 | Pre-signup contact verification OTP — SMS | NOT_REVIEWED | |
| A.6 | Logout (current session) | NOT_REVIEWED | |
| A.7 | Token refresh / session rotation | NOT_REVIEWED | |
| A.8 | Active-sessions list (login history) | NOT_REVIEWED | |
| A.9 | Revoke a single session | NOT_REVIEWED | |
| A.10 | Legacy login-history list + logout endpoints | NOT_REVIEWED | |
| A.11 | Forgot password (request reset link) | NOT_REVIEWED | |
| A.12 | Reset password (from token) | NOT_REVIEWED | |
| A.13 | Change password (in-app) | NOT_REVIEWED | |
| A.14 | Email verification (click link) | NOT_REVIEWED | |
| A.15 | Email-verification notice screen | NOT_REVIEWED | |
| A.16 | Login-time 2FA challenge + verify | NOT_REVIEWED | |
| A.17 | 2FA "try another way" (switch method mid-login) | NOT_REVIEWED | |
| A.18 | 2FA resend OTP mid-login | NOT_REVIEWED | |
| A.19 | 2FA status read (layered user) | NOT_REVIEWED | |
| A.20 | 2FA self-service status view (settings) | NOT_REVIEWED | |
| A.21 | 2FA setup — Google Authenticator (TOTP) | NOT_REVIEWED | |
| A.22 | 2FA setup — Email OTP | NOT_REVIEWED | |
| A.23 | 2FA setup — SMS OTP | NOT_REVIEWED | |
| A.24 | 2FA verify & enable | NOT_REVIEWED | |
| A.25 | 2FA disable (re-auth guarded) | NOT_REVIEWED | |
| A.26 | 2FA change method (re-auth guarded) | NOT_REVIEWED | |
| A.27 | Action-verify re-auth OTP (send + verify) | NOT_REVIEWED | |
| A.28 | Accept invite (recipient signup from token) | NOT_REVIEWED | |
| A.29 | Captcha challenge | NOT_REVIEWED | |
| A.30 | Route guard — authenticated `/user/**` | NOT_REVIEWED | |
| A.31 | Route guard — permission-key gate + access-denied page | NOT_REVIEWED | |
| A.32 | HTTP auth interceptor (bearer + refresh-and-retry) | NOT_REVIEWED | |
| A.33 | Device push-token register / unregister | NOT_REVIEWED | |

---

### B. Onboarding & Workspace Setup

What happens between "account created" and "usable workspace": the pack/template picker, org creation, and the installer that seeds an org's defaults. Backend: `API/src/app/core/packs/`, `API/src/app/core/tenants/`. Frontend: `APP/src/app/features/accounts/onboarding/`.

**Known flag at map time:** the pack catalog renders tiles for packs with no on-disk `pack.yaml` as `coming_soon` — they look selectable but aren't installable.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| B.1 | Pack catalog listing (available vs coming-soon) | NOT_REVIEWED | |
| B.2 | Onboarding pack/template picker | NOT_REVIEWED | |
| B.3 | Onboarding wizard (template → org name → country/currency/team size) | NOT_REVIEWED | |
| B.4 | Org creation on signup (pending placeholder org) | NOT_REVIEWED | |
| B.5 | Complete onboarding — apply pack + run installer + rotate JWT | NOT_REVIEWED | |
| B.6 | `noOrgGuard` pending-org redirect flow | NOT_REVIEWED | |
| B.7 | Onboarding unauthenticated defensive redirect | NOT_REVIEWED | |

---

### C. App Shell, Navigation & Dashboard

The frame every signed-in page renders inside, plus the landing dashboard. Backend: `API/src/app/core/dashboard/`, `module_registry.py`, `modules_router.py`. Frontend: `APP/src/app/features/user/core/layout/` and `.../core/dashboard/`.

**Known flag at map time:** the header's global search box is **scaffolded only** — an `<input type="search">` with no event binding, no handler, and no backing endpoint.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| C.1 | Registry-driven sidebar navigation (permission-filtered) | NOT_REVIEWED | |
| C.2 | Sidebar collapse / expand (persisted) | NOT_REVIEWED | |
| C.3 | Mobile off-canvas sidebar drawer | NOT_REVIEWED | |
| C.4 | App shell layout host | NOT_REVIEWED | |
| C.5 | Header user menu (profile link + logout) | NOT_REVIEWED | |
| C.6 | Header current-user identity fetch | NOT_REVIEWED | |
| C.7 | Global search box (scaffolded, not wired) | NOT_REVIEWED | |
| C.8 | Global quick-add FAB (cross-entity create shortcut) | NOT_REVIEWED | |
| C.9 | Welcome page | NOT_REVIEWED | |
| C.10 | Role-adaptive dashboard summary | NOT_REVIEWED | |
| C.11 | Dashboard KPI hero tiles + secondary cards grid | NOT_REVIEWED | |
| C.12 | Dashboard recent-activity feed | NOT_REVIEWED | |
| C.13 | Dashboard upcoming-appointments widget (Today / Next 5) | NOT_REVIEWED | |
| C.14 | Dashboard trend chart widget | NOT_REVIEWED | |
| C.15 | Dashboard funnel chart widget | NOT_REVIEWED | |
| C.16 | Today's follow-ups widget (pending / completed / overdue buckets) | NOT_REVIEWED | |
| C.17 | Dashboard quick-actions widget | NOT_REVIEWED | |
| C.18 | Dashboard refresh control | NOT_REVIEWED | |
| C.19 | Dev-only module hot reload | NOT_REVIEWED | |

---

### D. Contacts

The people record: list, detail, bulk operations, groups, consent, and import. Backend: `API/src/app/core/contacts/` (+ `groups/`, `imports/`). Frontend: `APP/src/app/features/user/core/contacts/`.

**Known flag at map time:** the "Notes" tab on contact detail is a placeholder (`placeholderStep: 'later'`), not a real notes surface.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| D.1 | Contacts list (search / source / tag / assignee filter, sort, paginate) | NOT_REVIEWED | |
| D.2 | Create contact (modal + dynamic custom fields + live duplicate check) | NOT_REVIEWED | |
| D.3 | Edit contact | NOT_REVIEWED | |
| D.4 | Contact detail view (Overview / Activities / Notes / Tasks / Automations tabs) | NOT_REVIEWED | |
| D.5 | Delete contact | NOT_REVIEWED | |
| D.6 | Single reassign contact owner | NOT_REVIEWED | |
| D.7 | Bulk reassign contacts | NOT_REVIEWED | |
| D.8 | Bulk add tag | NOT_REVIEWED | |
| D.9 | Bulk delete contacts | NOT_REVIEWED | |
| D.10 | Export contacts CSV (respecting current filter) | NOT_REVIEWED | |
| D.11 | WhatsApp opt-in / opt-out + consent history on a contact | NOT_REVIEWED | |
| D.12 | Contact data-export ZIP (DPDP right-to-access) | NOT_REVIEWED | |
| D.13 | Contact groups list (with member counts) | NOT_REVIEWED | |
| D.14 | Create / edit contact group (static list or dynamic filter DSL + live preview) | NOT_REVIEWED | |
| D.15 | Delete contact group | NOT_REVIEWED | |
| D.16 | Contact import wizard (upload → map → dry-run → commit) | NOT_REVIEWED | |

---

### E. Leads & Pipelines

The deal record and the stage machinery it moves through. Backend: `API/src/app/core/leads/`, `API/src/app/core/pipelines/`. Frontend: `APP/src/app/features/user/core/leads/`, `.../core/pipelines/`.

**Scope note:** how leads *enter* the system (bulk import, widget, ad integrations, quick-add) is module **I**, not here. Saved views appear here as their live consumer and in **W** as the engine.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| E.1 | Leads kanban board (drag between stages) | NOT_REVIEWED | |
| E.2 | Leads list view (cursor pagination, column customization, sort) | NOT_REVIEWED | |
| E.3 | Advanced filter modal (filter DSL over standard + custom fields) | NOT_REVIEWED | |
| E.4 | Create lead (ingest → dedup + round-robin routing) | NOT_REVIEWED | |
| E.5 | Edit lead | NOT_REVIEWED | |
| E.6 | Lead detail view (tabs + attribution panel + custom fields) | NOT_REVIEWED | |
| E.7 | Delete lead | NOT_REVIEWED | |
| E.8 | Move stage (incl. Lost stage with lost-reason capture) | NOT_REVIEWED | |
| E.9 | Single reassign lead | NOT_REVIEWED | |
| E.10 | Bulk reassign leads | NOT_REVIEWED | |
| E.11 | Bulk delete leads | NOT_REVIEWED | |
| E.12 | Export leads CSV | NOT_REVIEWED | |
| E.13 | Saved views on leads list (apply / update / share / delete) | NOT_REVIEWED | |
| E.14 | Lead scoring rules page (list, add/edit, activate, delete) | NOT_REVIEWED | |
| E.15 | Recompute lead scores now (org-wide job) | NOT_REVIEWED | |
| E.16 | Lead routing config (round-robin assignment strategy) | NOT_REVIEWED | |
| E.17 | Pipeline — add stage | NOT_REVIEWED | |
| E.18 | Pipeline — edit stage (name / colour / order) | NOT_REVIEWED | |
| E.19 | Pipeline — delete stage with card relocation | NOT_REVIEWED | |
| E.20 | Pipeline list / detail fetch | NOT_REVIEWED | |

---

### F. Activities & Tasks

The audit trail of what happened on a record, and the to-do list of what happens next. Backend: `API/src/app/core/activities/`, `API/src/app/core/tasks/`. Frontend: `APP/src/app/features/user/core/activities/`, `.../core/tasks/`.

**Known flag at map time:** only `type=note` activities are user-creatable; call/email/status-change/task rows are system-generated. The task form emits empty custom-field definitions — there is no custom-fields endpoint for tasks yet.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| F.1 | Activity timeline (per entity, grouped by day, multi-type) | NOT_REVIEWED | |
| F.2 | Log a note (manual activity composer) | NOT_REVIEWED | |
| F.3 | Tasks list page (All / Mine / Overdue / Due today / Done chips, owner filter, search, sort) | NOT_REVIEWED | |
| F.4 | Create task (modal) | NOT_REVIEWED | |
| F.5 | Edit task | NOT_REVIEWED | |
| F.6 | Complete / reopen task (checkbox toggle) | NOT_REVIEWED | |
| F.7 | Mark task missed | NOT_REVIEWED | |
| F.8 | Delete task | NOT_REVIEWED | |
| F.9 | Bulk reassign tasks | NOT_REVIEWED | |
| F.10 | Bulk mark tasks done | NOT_REVIEWED | |
| F.11 | Bulk delete tasks | NOT_REVIEWED | |
| F.12 | Tasks panel embedded on contact / lead detail | NOT_REVIEWED | |
| F.13 | "My Tasks" header popover | NOT_REVIEWED | |

---

### G. Appointments & Walk-ins

Scheduled visits and unscheduled ones. Backend: `API/src/app/core/appointments/`, `API/src/app/core/walk_ins/`. Frontend: `APP/src/app/features/user/core/appointments/`, `.../core/walk-ins/`.

**Known flags at map time:** single-reassign for walk-ins is wired in code but has no row UI (reachable programmatically only); bulk-delete of walk-ins loops per-row `DELETE` because there is no batch endpoint.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| G.1 | Appointments list / calendar page (toggle, status chips, owner scope, sort) | NOT_REVIEWED | |
| G.2 | Book appointment (modal, conflict handling, custom fields) | NOT_REVIEWED | |
| G.3 | Appointment detail popover + inline status change (completed / no-show) | NOT_REVIEWED | |
| G.4 | Reschedule appointment | NOT_REVIEWED | |
| G.5 | Reassign appointment (single) | NOT_REVIEWED | |
| G.6 | Cancel appointment | NOT_REVIEWED | |
| G.7 | Bulk reassign appointments | NOT_REVIEWED | |
| G.8 | Bulk cancel appointments | NOT_REVIEWED | |
| G.9 | Delete appointment | NOT_REVIEWED | |
| G.10 | Appointment reminder sweep (24h / 1h background beat job) | NOT_REVIEWED | |
| G.11 | Walk-ins list page (status + date chips, owner scope, KPI cards) | NOT_REVIEWED | |
| G.12 | Register walk-in (quick-register; creates or links a contact) | NOT_REVIEWED | |
| G.13 | Advance walk-in status (browsing → interested → follow-up → converted/left) | NOT_REVIEWED | |
| G.14 | Check out walk-in (stamp time-out) | NOT_REVIEWED | |
| G.15 | Convert walk-in to lead | NOT_REVIEWED | |
| G.16 | Single reassign walk-in (no row UI yet) | NOT_REVIEWED | |
| G.17 | Bulk reassign walk-ins | NOT_REVIEWED | |
| G.18 | Bulk checkout walk-ins | NOT_REVIEWED | |
| G.19 | Bulk delete walk-ins (per-row loop) | NOT_REVIEWED | |
| G.20 | Delete walk-in | NOT_REVIEWED | |

---

### H. Product Catalog

The org's sellable items. Backend: `API/src/app/core/catalog/`. Frontend: `APP/src/app/features/user/core/catalog/`.

**Known flag at map time:** "category" is a free-text column on the item, not a managed entity — the dropdown is derived client-side from loaded items, and there is **no category CRUD resource or endpoint**.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| H.1 | Catalog browse (search, category filter, KPI strip, card grid) | NOT_REVIEWED | |
| H.2 | View product (read-only detail modal) | NOT_REVIEWED | |
| H.3 | Create product | NOT_REVIEWED | |
| H.4 | Edit product | NOT_REVIEWED | |
| H.5 | Delete product | NOT_REVIEWED | |
| H.6 | Upload / replace product cover image (multipart, type-validated) | NOT_REVIEWED | |
| H.7 | Category filtering (client-derived; no category entity) | NOT_REVIEWED | |

---

### I. Lead Capture & Ingestion

Every path by which a lead **enters** the system: typed in by hand, imported from a file, submitted through an embedded form on the customer's own website, or pushed in by Google/Meta ad platforms. Backend: `API/src/app/core/leads/imports/`, `.../core/embed/`, `.../core/integrations/{google,meta}/`. Frontend: `.../core/leads/import/`, the Settings Embed tab, and the Integrations hub. Also the standalone `widget/` bundle at the repo root.

**Scope note:** the generic Integrations *hub shell* (list/disconnect/status/rotate-secret) is module **X**; the ad-specific OAuth, webhooks, subscriptions, mapping, and dead-letter queue live here because they exist only to capture leads.

**Known flag at map time:** the `sticky_by_source` routing strategy is a documented placeholder that silently falls through to round-robin — v1 accepts only `round_robin`.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| I.1 | Manual quick-add lead (modal) | NOT_REVIEWED | |
| I.2 | Merged-vs-created feedback on manual add | NOT_REVIEWED | |
| I.3 | Per-source badge on lead cards / rows | NOT_REVIEWED | |
| I.4 | Filter leads by source | NOT_REVIEWED | |
| I.5 | Upload import file (drag-drop + source-platform picker) | NOT_REVIEWED | |
| I.6 | Column-mapping editor | NOT_REVIEWED | |
| I.7 | Import preview (first N rows) | NOT_REVIEWED | |
| I.8 | Commit mapping → enqueue import job | NOT_REVIEWED | |
| I.9 | Celery bulk-import processor (dedup, create, custom-field routing, error CSV) | NOT_REVIEWED | |
| I.10 | Cancel an in-flight import | NOT_REVIEWED | |
| I.11 | Import history list (status / platform filters) | NOT_REVIEWED | |
| I.12 | Import result / detail page | NOT_REVIEWED | |
| I.13 | Download per-import error report CSV | NOT_REVIEWED | |
| I.14 | Download original uploaded source file | NOT_REVIEWED | |
| I.15 | List mapping presets per source platform | NOT_REVIEWED | |
| I.16 | Save current mapping as an org preset | NOT_REVIEWED | |
| I.17 | Delete an org-owned preset | NOT_REVIEWED | |
| I.18 | Issue embed API key (plaintext shown once) | NOT_REVIEWED | |
| I.19 | List embed keys (active / revoked) | NOT_REVIEWED | |
| I.20 | Revoke embed key | NOT_REVIEWED | |
| I.21 | Widget form-config editor (fields, labels, required, reorder, thank-you) | NOT_REVIEWED | |
| I.22 | Widget branding editor (accent colour, logo, powered-by toggle) | NOT_REVIEWED | |
| I.23 | Widget spam-protection config (reCAPTCHA keys, min-fill-time) | NOT_REVIEWED | |
| I.24 | Widget custom-field picker (contact + lead fields opt-in) | NOT_REVIEWED | |
| I.25 | Install-snippet generation + copy to clipboard | NOT_REVIEWED | |
| I.26 | Public widget lead submission (unauthenticated, key in header/body) | NOT_REVIEWED | |
| I.27 | Public widget config fetch for the renderer | NOT_REVIEWED | |
| I.28 | Widget spam gates (honeypot, min-fill-time, reCAPTCHA, per-key + per-IP rate limit) | NOT_REVIEWED | |
| I.29 | Widget submission log (outcome / date filters) | NOT_REVIEWED | |
| I.30 | Widget submission summary card + per-day chart | NOT_REVIEWED | |
| I.31 | Standalone embeddable widget bundle (customer-site renderer) | NOT_REVIEWED | |
| I.32 | WhatsApp consent capture on widget submit | NOT_REVIEWED | |
| I.33 | Google Ads connect / OAuth authorize | NOT_REVIEWED | |
| I.34 | Google Ads OAuth callback (state verify → token exchange → persist) | NOT_REVIEWED | |
| I.35 | Google Ads — list accessible ad accounts | NOT_REVIEWED | |
| I.36 | Google Ads — list Lead Form assets on a customer | NOT_REVIEWED | |
| I.37 | Google Ads lead webhook receiver (per-tenant secret URL + key check) | NOT_REVIEWED | |
| I.38 | Google lead-processing Celery job | NOT_REVIEWED | |
| I.39 | Meta connect / OAuth authorize | NOT_REVIEWED | |
| I.40 | Meta OAuth callback (short → long token exchange) | NOT_REVIEWED | |
| I.41 | Meta — list managed Pages | NOT_REVIEWED | |
| I.42 | Meta — list Lead Forms on a Page | NOT_REVIEWED | |
| I.43 | Meta — subscribe Page to leadgen (+ Messenger/IG, cache token) | NOT_REVIEWED | |
| I.44 | Meta — unsubscribe Page | NOT_REVIEWED | |
| I.45 | Meta webhook verify handshake | NOT_REVIEWED | |
| I.46 | Meta lead webhook receiver (HMAC-signed, fan-out per change) | NOT_REVIEWED | |
| I.47 | Meta lead-processing Celery job (Graph fetch → map → dedup → ingest) | NOT_REVIEWED | |
| I.48 | Meta data-deletion callback + public status lookup | NOT_REVIEWED | |
| I.49 | Form-subscription CRUD (list / create / update / delete) | NOT_REVIEWED | |
| I.50 | Field-mapping editor for a subscription | NOT_REVIEWED | |
| I.51 | Dead-letter queue list (provider filter, open failures) | NOT_REVIEWED | |
| I.52 | Dead-letter queue replay | NOT_REVIEWED | |
| I.53 | Dead-letter queue discard | NOT_REVIEWED | |
| I.54 | Cross-source open-lead dedup + "touchpoint" merge (all 5 channels) | NOT_REVIEWED | |
| I.55 | Contact dedup by phone / email at ingest | NOT_REVIEWED | |
| I.56 | Round-robin assignee routing on new leads | NOT_REVIEWED | |

---

### J. Conversations (Omni-channel Inbox)

The shared team inbox across WhatsApp, SMS, email, Messenger, Instagram, and push. Backend: `API/src/app/core/conversations/` (+ `adapters/`). Frontend: `APP/src/app/features/user/core/conversations/`.

**Known flag at map time:** **mark read / unread has no endpoint.** `unread_count` is incremented on inbound but `ConversationPatch` exposes only `assigned_to_id` / `status` / `ai_handling`, and no client method exists — the badge appears to be display-only and not user-resettable. Every benchmark inbox lets you mark a thread unread; expect a Phase 1 discussion.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| J.1 | Inbox list with channel / status / search filters | NOT_REVIEWED | |
| J.2 | Assignee filter chips (Mine / Unassigned / per-staff), persisted per org | NOT_REVIEWED | |
| J.3 | Tag filter chips (OR semantics) | NOT_REVIEWED | |
| J.4 | Thread / message view (bubbles, statuses, reply snippets) | NOT_REVIEWED | |
| J.5 | Unread-count badge on list rows | NOT_REVIEWED | |
| J.6 | Mark read / unread (no endpoint found — verify) | NOT_REVIEWED | |
| J.7 | Send text message (optimistic append + rollback) | NOT_REVIEWED | |
| J.8 | Send media message (image / video / audio / document + caption) | NOT_REVIEWED | |
| J.9 | Send location | NOT_REVIEWED | |
| J.10 | Send interactive message (reply buttons / CTA URL / list) | NOT_REVIEWED | |
| J.11 | React to a message (add / replace / remove emoji) | NOT_REVIEWED | |
| J.12 | Reply-to / quote a message | NOT_REVIEWED | |
| J.13 | Post internal note with @-mentions | NOT_REVIEWED | |
| J.14 | Assign / reassign a conversation | NOT_REVIEWED | |
| J.15 | Sender pill / staff name + avatar resolution | NOT_REVIEWED | |
| J.16 | Change conversation status (open / snoozed / closed) — verify UI control | NOT_REVIEWED | |
| J.17 | Toggle AI handling on a conversation | NOT_REVIEWED | |
| J.18 | Conversation tags — create / rename / recolour / delete | NOT_REVIEWED | |
| J.19 | Assign / unassign a tag on a conversation | NOT_REVIEWED | |
| J.20 | Export conversation transcript as CSV | NOT_REVIEWED | |
| J.21 | Export conversation transcript as PDF | NOT_REVIEWED | |
| J.22 | Click-to-WhatsApp ad attribution chip | NOT_REVIEWED | |
| J.23 | WhatsApp 24-hour session-window banner + "Pick template" CTA | NOT_REVIEWED | |
| J.24 | Send-From phone picker (multi-number orgs) | NOT_REVIEWED | |
| J.25 | Live inbox refresh via notifications WebSocket | NOT_REVIEWED | |
| J.26 | Inbound webhook receiver per channel | NOT_REVIEWED | |
| J.27 | Webhook subscription verify handshake per channel | NOT_REVIEWED | |
| J.28 | Channel adapters (WhatsApp / SMS / Email / Messenger / Instagram / Push) | NOT_REVIEWED | |
| J.29 | Block-number action from the thread header | NOT_REVIEWED | |

---

### K. WhatsApp Business Platform

By far the largest module — provider connection, template lifecycle with Meta approval, auto-replies, keyword and assignment automation, consent/block list, Flows, QR quick-links, webhooks, phone health, and analytics. Backend: `API/src/app/core/integrations/whatsapp/` and `.../whatsapp_web/`, plus the Baileys sidecar at `sidecars/whatsapp-web/`. Frontend: `APP/src/app/features/user/core/whatsapp/` and `.../core/reporting/whatsapp/`.

**Known flag at map time:** the **unofficial (Baileys) provider has a complete, permission-gated backend but no Angular UI** — all four management endpoints exist and no component consumes them. A user cannot connect the unofficial provider from the product today.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| K.1 | Connect WhatsApp via Meta Embedded Signup (FB.login popup) | NOT_REVIEWED | |
| K.2 | Manual "Advanced (self-host)" connect (paste credentials) | NOT_REVIEWED | |
| K.3 | Test WhatsApp connection (ping Meta with stored creds) | NOT_REVIEWED | |
| K.4 | Disconnect WhatsApp (retain ids for reconnect prefill) | NOT_REVIEWED | |
| K.5 | View WhatsApp connection status card | NOT_REVIEWED | |
| K.6 | List connected phone numbers (multi-number Send-From picker) | NOT_REVIEWED | |
| K.7 | Send capacity / messaging-tier quota banner | NOT_REVIEWED | |
| K.8 | Connect WhatsApp Web (Baileys) pairing session — backend only | NOT_REVIEWED | |
| K.9 | Live QR-pairing SSE stream — backend only | NOT_REVIEWED | |
| K.10 | Disconnect WhatsApp Web session — backend only | NOT_REVIEWED | |
| K.11 | View WhatsApp Web session status — backend only | NOT_REVIEWED | |
| K.12 | Sidecar → API inbound event ingest (HMAC-signed, no JWT) | NOT_REVIEWED | |
| K.13 | Baileys sidecar service (session lifecycle, outbound send, media, health) | NOT_REVIEWED | |
| K.14 | Cloud vs unofficial provider selection at send time | NOT_REVIEWED | |
| K.15 | WhatsApp templates management page (list + status / category / language filters) | NOT_REVIEWED | |
| K.16 | Create template draft (template wizard) | NOT_REVIEWED | |
| K.17 | Edit a draft / rejected template | NOT_REVIEWED | |
| K.18 | Submit template for Meta approval | NOT_REVIEWED | |
| K.19 | Duplicate a template | NOT_REVIEWED | |
| K.20 | Delete template (local + Meta) | NOT_REVIEWED | |
| K.21 | Template live preview (WhatsApp-style bubble) | NOT_REVIEWED | |
| K.22 | Per-template performance card (sent/delivered/read/replied/CTR, daily series) | NOT_REVIEWED | |
| K.23 | Sync template library from Meta | NOT_REVIEWED | |
| K.24 | Approved-template picker for campaigns | NOT_REVIEWED | |
| K.25 | Inbound template approval / rejection status webhook | NOT_REVIEWED | |
| K.26 | Business profile editor (about, description, address, email, websites, vertical) | NOT_REVIEWED | |
| K.27 | Refresh profile from Meta (re-sync + staleness stamp) | NOT_REVIEWED | |
| K.28 | Upload business profile picture | NOT_REVIEWED | |
| K.29 | Business hours editor (Mon–Sun) | NOT_REVIEWED | |
| K.30 | Greeting auto-reply toggle + message / template | NOT_REVIEWED | |
| K.31 | Away / out-of-hours auto-reply toggle + message / template | NOT_REVIEWED | |
| K.32 | Auto-reply dispatch on inbound (cooldown-aware) | NOT_REVIEWED | |
| K.33 | Per-phone profile editing (multi-number) | NOT_REVIEWED | |
| K.34 | WhatsApp automation page (keyword + assignment + AI tabs) | NOT_REVIEWED | |
| K.35 | List keyword automation rules | NOT_REVIEWED | |
| K.36 | Create keyword rule (keywords + match type + actions) | NOT_REVIEWED | |
| K.37 | Edit keyword rule | NOT_REVIEWED | |
| K.38 | Delete keyword rule | NOT_REVIEWED | |
| K.39 | Reorder keyword rules (drag → priority) | NOT_REVIEWED | |
| K.40 | Test / dry-run a keyword rule against sample text | NOT_REVIEWED | |
| K.41 | Keyword rule engine execution on inbound | NOT_REVIEWED | |
| K.42 | List auto-assignment rules | NOT_REVIEWED | |
| K.43 | Create auto-assignment rule (strategy + config + skip-outside-hours) | NOT_REVIEWED | |
| K.44 | Edit auto-assignment rule | NOT_REVIEWED | |
| K.45 | Delete auto-assignment rule | NOT_REVIEWED | |
| K.46 | Reorder auto-assignment rules | NOT_REVIEWED | |
| K.47 | Auto-assignment engine execution on inbound | NOT_REVIEWED | |
| K.48 | Block-list page (search + paginate blocked numbers) | NOT_REVIEWED | |
| K.49 | Add number to block list (reason + notes) | NOT_REVIEWED | |
| K.50 | Remove number from block list | NOT_REVIEWED | |
| K.51 | DPDP opt-in auto-flip on inbound (STOP → opted-out + confirmation) | NOT_REVIEWED | |
| K.52 | WhatsApp Flows library page | NOT_REVIEWED | |
| K.53 | Pick a bundled flow starter template | NOT_REVIEWED | |
| K.54 | Create a flow | NOT_REVIEWED | |
| K.55 | Edit flow JSON definition (flow builder) | NOT_REVIEWED | |
| K.56 | Preview a flow | NOT_REVIEWED | |
| K.57 | Publish flow to Meta | NOT_REVIEWED | |
| K.58 | Delete flow | NOT_REVIEWED | |
| K.59 | Test-send a published flow to a phone number | NOT_REVIEWED | |
| K.60 | Flow submission capture on inbound (`nfm_reply`) | NOT_REVIEWED | |
| K.61 | Quick-links page (list + paginate) | NOT_REVIEWED | |
| K.62 | Create quick link (label + phone + prefilled message) | NOT_REVIEWED | |
| K.63 | Edit quick link | NOT_REVIEWED | |
| K.64 | Delete quick link | NOT_REVIEWED | |
| K.65 | View per-link stats (clicks / scans / attributed conversations) | NOT_REVIEWED | |
| K.66 | Download QR as PNG | NOT_REVIEWED | |
| K.67 | Download QR as SVG (vector / print) | NOT_REVIEWED | |
| K.68 | Public 302 redirect to wa.me with click tracking (rate-limited) | NOT_REVIEWED | |
| K.69 | QR / wa.me inbound attribution match (prefilled-hash pairing) | NOT_REVIEWED | |
| K.70 | Cloud webhook verify handshake (per-org verify token) | NOT_REVIEWED | |
| K.71 | Cloud inbound webhook receiver (per-org routing + signature verify) | NOT_REVIEWED | |
| K.72 | Message status webhook (delivered / read / failed) | NOT_REVIEWED | |
| K.73 | Phone quality / tier change webhook | NOT_REVIEWED | |
| K.74 | Click-to-WhatsApp ad attribution on inbound | NOT_REVIEWED | |
| K.75 | Phone health card (quality rating, tier, 30-day timeline) | NOT_REVIEWED | |
| K.76 | Force-refresh phone health from Meta | NOT_REVIEWED | |
| K.77 | Hourly phone-health refresh background job | NOT_REVIEWED | |
| K.78 | WhatsApp reports page | NOT_REVIEWED | |
| K.79 | Message volume widget (sent / received / failed) | NOT_REVIEWED | |
| K.80 | Response-time widget (median / p95 / histogram) | NOT_REVIEWED | |
| K.81 | Conversation outcomes widget (status + tag breakdown) | NOT_REVIEWED | |
| K.82 | Agent leaderboard widget | NOT_REVIEWED | |
| K.83 | Cost estimate widget (Meta categories × region rates) | NOT_REVIEWED | |
| K.84 | Quality timeline widget | NOT_REVIEWED | |
| K.85 | Ad ROI / click-to-WhatsApp attribution widget | NOT_REVIEWED | |

---

### L. Calls (Call Center)

Manual call logging, recordings, transcripts, dispositions, and call analytics. Backend: `API/src/app/core/calls/`. Frontend: `APP/src/app/features/user/core/calls/`.

**Known flag at map time:** call-outcome **create / update / delete** endpoints exist and are permission-gated, but no frontend calls them — `calls-api.service.ts` exposes only `listOutcomes()`. Dispositions are effectively unmanageable from the UI.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| L.1 | Call center page (tabbed shell) | NOT_REVIEWED | |
| L.2 | Call logs list with filters (contact / direction / assignee) + pagination | NOT_REVIEWED | |
| L.3 | Log a call (direction, time, duration, outcome, notes, assignee) | NOT_REVIEWED | |
| L.4 | View a single call | NOT_REVIEWED | |
| L.5 | Edit a logged call | NOT_REVIEWED | |
| L.6 | Delete a logged call | NOT_REVIEWED | |
| L.7 | Call-picker modal (attach a call from another surface) | NOT_REVIEWED | |
| L.8 | Upload a call recording (≤30 MB, audio types) | NOT_REVIEWED | |
| L.9 | Play back a call recording | NOT_REVIEWED | |
| L.10 | View a call transcript | NOT_REVIEWED | |
| L.11 | Create / update a call transcript | NOT_REVIEWED | |
| L.12 | List call outcomes / dispositions | NOT_REVIEWED | |
| L.13 | Create a call outcome (no UI caller) | NOT_REVIEWED | |
| L.14 | Update a call outcome (no UI caller) | NOT_REVIEWED | |
| L.15 | Delete a call outcome (no UI caller) | NOT_REVIEWED | |
| L.16 | Call analytics dashboard (outcome distribution, volume, direction split) | NOT_REVIEWED | |
| L.17 | Phone book tab (dial list / contact lookup) | NOT_REVIEWED | |
| L.18 | Book an appointment from a call | NOT_REVIEWED | |

---

### M. Email

Mailbox connection (Gmail / Microsoft), sync, sending with compliance gates, open/click/unsubscribe tracking, and deliverability (SPF/DKIM/DMARC, bounces, suppressions). Backend: `API/src/app/core/email/` (+ `tracking/`, `gmail/`, `microsoft/`), `.../core/email_sender_setup/`, and the email adapter in `.../core/conversations/adapters/email.py`.

**Known flag at map time — significant:** there is **no interactive email compose surface**. `EmailAdapter.send()` deliberately raises, pointing at a "dedicated email-compose endpoint" that does not exist in any router. Only automated senders (campaigns, sequences, workflow send-nodes) reach `send_email()`; a user staring at a contact record can only click a `mailto:` link. Sending a one-off email from the CRM — table stakes in every benchmark product — is not implemented.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| M.1 | Settings → Email Accounts tab | NOT_REVIEWED | |
| M.2 | Gmail OAuth connect | NOT_REVIEWED | |
| M.3 | Gmail OAuth callback (token exchange → watch → 30-day backfill) | NOT_REVIEWED | |
| M.4 | Microsoft OAuth connect | NOT_REVIEWED | |
| M.5 | Microsoft OAuth callback (token exchange → subscription → backfill) | NOT_REVIEWED | |
| M.6 | DPDP/GDPR consent acknowledgment before OAuth redirect | NOT_REVIEWED | |
| M.7 | List connected email accounts (own vs org-wide) | NOT_REVIEWED | |
| M.8 | Disconnect an email account (provider teardown + token nulling) | NOT_REVIEWED | |
| M.9 | Gmail Pub/Sub push receiver (OIDC-verified) | NOT_REVIEWED | |
| M.10 | Microsoft Graph subscription-validation handshake | NOT_REVIEWED | |
| M.11 | Microsoft Graph change-notification receiver (clientState HMAC) | NOT_REVIEWED | |
| M.12 | Mailbox sync daemon (backfill + incremental) | NOT_REVIEWED | |
| M.13 | Inbound email → conversation threading (Message-ID / References / subject) | NOT_REVIEWED | |
| M.14 | Send email from a connected mailbox (no interactive compose route) | NOT_REVIEWED | |
| M.15 | Send blocked on opt-out (compliance gate, 451) | NOT_REVIEWED | |
| M.16 | Send blocked on missing physical address (CAN-SPAM gate) | NOT_REVIEWED | |
| M.17 | Per-account daily send cap (soft warn + hard 429) | NOT_REVIEWED | |
| M.18 | Email open tracking pixel (public, unauthenticated) | NOT_REVIEWED | |
| M.19 | Click tracking + redirect (public, unauthenticated) | NOT_REVIEWED | |
| M.20 | Unsubscribe landing page (opt-out + cancel sequence enrollments) | NOT_REVIEWED | |
| M.21 | RFC 8058 one-click unsubscribe | NOT_REVIEWED | |
| M.22 | CAN-SPAM footer with org address + unsubscribe link | NOT_REVIEWED | |
| M.23 | Per-IP rate limiting on all tracking endpoints | NOT_REVIEWED | |
| M.24 | Sender-setup tab (verified sending domains) | NOT_REVIEWED | |
| M.25 | Add a sending domain | NOT_REVIEWED | |
| M.26 | View copy-paste DNS records (SPF / DKIM / DMARC) | NOT_REVIEWED | |
| M.27 | Re-verify a domain's DNS | NOT_REVIEWED | |
| M.28 | Delete a sending domain | NOT_REVIEWED | |
| M.29 | Domain auth status widget (verdict, 6h cache, force refresh) | NOT_REVIEWED | |
| M.30 | Bounce / complaint webhook intake (Mailgun HMAC; others by shape) | NOT_REVIEWED | |
| M.31 | Suppression list viewer (channel + reason filters) | NOT_REVIEWED | |
| M.32 | Remove a suppression (manual rehabilitation) | NOT_REVIEWED | |

---

### N. Templates Library

The central multi-channel content library (Email / WhatsApp / SMS / FB / IG / push) that Automations, Workflows, and Campaigns all render from. Backend: `API/src/app/core/templates/`. Frontend: `APP/src/app/features/user/core/templates/`.

**Known flag at map time:** "Duplicate" is referenced in the editor help text but is **not implemented** — duplicate-to-fork was replaced by direct in-place editing for Owner/Admin.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| N.1 | Template list (channel / status / search filters + pagination) | NOT_REVIEWED | |
| N.2 | Create template (channel-aware editor) | NOT_REVIEWED | |
| N.3 | Edit template (draft → new version) | NOT_REVIEWED | |
| N.4 | Variable / merge-field insertion | NOT_REVIEWED | |
| N.5 | Live preview (render against sample context) | NOT_REVIEWED | |
| N.6 | Delete / soft-archive template | NOT_REVIEWED | |
| N.7 | Test send (one-off rendered copy to a recipient) | NOT_REVIEWED | |
| N.8 | Version history drawer + view a past version | NOT_REVIEWED | |
| N.9 | Internal review workflow (submit / approve / reject / request-changes / publish) | NOT_REVIEWED | |
| N.10 | Submit WhatsApp template for external (Meta) approval | NOT_REVIEWED | |
| N.11 | Check / refresh external (Meta) status | NOT_REVIEWED | |
| N.12 | Resubmit a Meta-rejected template | NOT_REVIEWED | |
| N.13 | SMS DLT metadata get / patch (India compliance) | NOT_REVIEWED | |
| N.14 | Hourly external-status sweep against Meta (beat job) | NOT_REVIEWED | |

---

### O. Automations (single-event triggers)

One event in, one action out — the simple half of the automation story. Backend: `API/src/app/core/automation/` (+ `tracking.py`). Frontend: `APP/src/app/features/user/core/automations/`.

**Design note carried from discovery:** this module has its **own** HMAC open/click tracking, separate from the Campaigns module's tracking. Two independent tracking systems is a design-fit question for the Phase 1 pass.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| O.1 | Trigger list (event-type / enabled / channel / search filters) | NOT_REVIEWED | |
| O.2 | Create trigger (event → condition → action/template) | NOT_REVIEWED | |
| O.3 | Edit trigger | NOT_REVIEWED | |
| O.4 | Enable / disable trigger | NOT_REVIEWED | |
| O.5 | Delete trigger | NOT_REVIEWED | |
| O.6 | Save & Test (dry-run against pasted payload) | NOT_REVIEWED | |
| O.7 | Run-now (manual fire, real run row) | NOT_REVIEWED | |
| O.8 | Run history per trigger | NOT_REVIEWED | |
| O.9 | Retry a failed run | NOT_REVIEWED | |
| O.10 | Cross-entity run-history filter (feeds contact detail) | NOT_REVIEWED | |
| O.11 | Event-type discovery catalog | NOT_REVIEWED | |
| O.12 | Public open-tracking pixel (HMAC-signed, unauthenticated) | NOT_REVIEWED | |
| O.13 | Public click-redirect tracking (HMAC-signed, unauthenticated) | NOT_REVIEWED | |
| O.14 | Background send job — render + dispatch a queued run | NOT_REVIEWED | |
| O.15 | Daily time-based scan (birthday, stale-lead events) | NOT_REVIEWED | |
| O.16 | Event dispatch / enrollment from other modules' domain events | NOT_REVIEWED | |

---

### P. Workflows (multi-step)

The visual flowchart builder — branching, waits, goals, A/B splits — and the engine that runs it. Backend: `API/src/app/core/workflows/`. Frontend: `APP/src/app/features/user/core/workflows/`.

**Scope note:** the former Email Sequences module is fully absorbed here; `/user/settings/email-sequences` redirects to the Workflows Marketing category.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| P.1 | Workflow list + folder sidebar + status/category/channel/search filters + bulk select | NOT_REVIEWED | |
| P.2 | Folder CRUD (create / rename-move / delete) | NOT_REVIEWED | |
| P.3 | Per-workflow run-history drawer | NOT_REVIEWED | |
| P.4 | Create workflow (blank canvas) | NOT_REVIEWED | |
| P.5 | Edit workflow on SVG canvas (drag-drop nodes, branching, node config) | NOT_REVIEWED | |
| P.6 | Node-type editors (send / wait / branch / switch / A-B / goal / enroll / tag / update-field / routing / lifecycle / notify / webhook / create-record) | NOT_REVIEWED | |
| P.7 | Activate workflow (re-validates graph) | NOT_REVIEWED | |
| P.8 | Pause workflow | NOT_REVIEWED | |
| P.9 | Archive workflow (soft; protected on system defaults) | NOT_REVIEWED | |
| P.10 | Clone workflow | NOT_REVIEWED | |
| P.11 | Templates gallery list | NOT_REVIEWED | |
| P.12 | Gallery preview modal (read-only graph) | NOT_REVIEWED | |
| P.13 | "Use this template" — clone from gallery into a draft | NOT_REVIEWED | |
| P.14 | Test-fire (synthetic dry-run graph walk) | NOT_REVIEWED | |
| P.15 | Version history drawer + view a historical version | NOT_REVIEWED | |
| P.16 | Rollback to a prior version | NOT_REVIEWED | |
| P.17 | Export workflow JSON | NOT_REVIEWED | |
| P.18 | Import workflow JSON | NOT_REVIEWED | |
| P.19 | A/B pair two workflows | NOT_REVIEWED | |
| P.20 | A/B unpair | NOT_REVIEWED | |
| P.21 | A/B stats banner + full comparison page | NOT_REVIEWED | |
| P.22 | Run detail / step timeline page | NOT_REVIEWED | |
| P.23 | Diagnostics — "why didn't this fire?" condition trace | NOT_REVIEWED | |
| P.24 | Per-workflow analytics dashboard (KPIs, funnel, skip reasons, send rollup) | NOT_REVIEWED | |
| P.25 | Daily enrolled / completed / goal-reached series | NOT_REVIEWED | |
| P.26 | Background engine tick (one hop per node, self-re-enqueuing) | NOT_REVIEWED | |
| P.27 | Sweep parked wait-nodes due to resume (beat) | NOT_REVIEWED | |
| P.28 | Expire wait-for-event waits onto timeout edge (beat) | NOT_REVIEWED | |
| P.29 | Evaluate / auto-promote A/B winners + owner notification (beat) | NOT_REVIEWED | |
| P.30 | Refresh cached per-row running/completed counters (beat) | NOT_REVIEWED | |
| P.31 | Enrollment — workflows subscribe to domain events and start runs | NOT_REVIEWED | |
| P.32 | Email-Sequences absorbed redirect | NOT_REVIEWED | |

---

### Q. Campaigns

One-off broadcast sends to a selected audience, with stats. Backend: `API/src/app/core/campaigns/`. Frontend: `APP/src/app/features/user/core/campaigns/`.

**Known flag at map time:** there is **no pause or cancel** for a running campaign — the lifecycle is draft → start → running/scheduled → done/failed, and edit/delete are restricted to draft/failed. Every benchmark product has a stop button; treat this as a Phase 1 shape question.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| Q.1 | Campaign list | NOT_REVIEWED | |
| Q.2 | Create campaign (channel, audience, template/inline, sender, schedule, A/B config) | NOT_REVIEWED | |
| Q.3 | Edit campaign (draft only) | NOT_REVIEWED | |
| Q.4 | Delete campaign (draft / failed only) | NOT_REVIEWED | |
| Q.5 | Audience selection (query / source / tag / group / explicit ids) with live preview | NOT_REVIEWED | |
| Q.6 | Readiness pre-flight (blockers + warnings before start) | NOT_REVIEWED | |
| Q.7 | Start / send / schedule broadcast | NOT_REVIEWED | |
| Q.8 | Campaign detail with stats KPIs + live polling | NOT_REVIEWED | |
| Q.9 | Per-message table (delivery / read / bounce / open / click states) | NOT_REVIEWED | |
| Q.10 | Retry a failed message | NOT_REVIEWED | |
| Q.11 | Analytics tab (funnel, failures breakdown, A/B variant comparison) | NOT_REVIEWED | |
| Q.12 | Background send job — broadcast chunk dispatch with retry | NOT_REVIEWED | |
| Q.13 | Scheduled dispatch of campaigns whose send time elapsed (beat) | NOT_REVIEWED | |
| Q.14 | A/B winner decision after holdback | NOT_REVIEWED | |

---

### R. Reviews

Customer review inbox, replies, and escalation. Backend: `API/src/app/core/reviews/`. Frontend: `APP/src/app/features/user/core/reviews/`.

**Known flags at map time — this module has the largest shape gap found during mapping:** there is **no way to request a review** (no send/request endpoint), and the "auto-request after event" toggle is **UI-only**, persisted to `localStorage` with no backend at all. Requesting reviews is the primary feature of every competing reputation tool. Expect a substantial Phase 1 discussion.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| R.1 | Reviews inbox / list (rating, source, status filters) | NOT_REVIEWED | |
| R.2 | Reviews stats / KPIs + rating distribution | NOT_REVIEWED | |
| R.3 | Reply to a review | NOT_REVIEWED | |
| R.4 | Escalate a review for owner attention | NOT_REVIEWED | |
| R.5 | Review detail / update / delete (backend CRUD; no dedicated detail page) | NOT_REVIEWED | |
| R.6 | Create / ingest a review (backend only, no UI entry) | NOT_REVIEWED | |
| R.7 | "Auto-request after event" toggle (UI-only, no backend) | NOT_REVIEWED | |

---

### S. Reporting & Analytics

Cross-product reporting. Backend: `API/src/app/core/reporting/`. Frontend: `APP/src/app/features/user/core/reporting/`.

**Known flag at map time — the biggest structural gap found during mapping.** This module is **almost entirely empty**. The frontend folder contains only a `.gitkeep` plus the WhatsApp sub-folder. There is no generic reporting dashboard, no report list, no export, and no shared date-range filter. Of the endpoints in `reporting/router.py`, ~95% are WhatsApp/campaign analytics consumed by module **K** (listed there, not duplicated here), and the campaign funnel/failures/A-B endpoints back **Q.11**. The only thing genuinely belonging to S is the staff workload report — which is itself rendered inside a Settings → Team sub-tab, not in a reporting section. Every benchmark CRM ships a reporting area as a first-class product surface; this one effectively has none. Expect a substantial Phase 1 discussion about whether S should exist as a real module.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| S.1 | Staff workload report (per-user open-record counts) | NOT_REVIEWED | |
| S.2 | Active-only toggle on the workload report | NOT_REVIEWED | |

---

### T. Billing & Subscription (SaaS)

The money layer: public pricing, plans, Stripe Checkout, seats, trials, entitlements, usage metering, and the middleware that degrades an org to read-only when it stops paying. Backend: `API/src/app/core/subscriptions/` (+ `webhooks/`, `middleware.py`). Frontend: `APP/src/app/features/user/core/billing/` and the public `APP/src/app/features/pricing/`.

**Important naming trap:** despite its name, `API/src/app/core/billing/` is **not** SaaS billing — it is customer invoice CRUD (`/api/v1/invoices`) backing the furniture pack's POS, and is reviewed under module **AB**. SaaS subscription billing lives entirely in `core/subscriptions/`. The permission keys overlap confusingly (`billing.read` / `billing.write` are shared by both surfaces; only `billing.manage` is SaaS-only) — worth raising in the Phase 1 pass.

**Known flags at map time:** `POST /subscriptions/change` and `POST /subscriptions/cancel` are fully implemented with no frontend caller — **there is no way for a customer to cancel their subscription from the UI**. Also, the checkout redirect allow-list permits only `localhost`/`127.0.0.1`, so production checkout redirects would be rejected.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| T.1 | Public pricing page (plan comparison grid) | NOT_REVIEWED | |
| T.2 | Monthly / annual cycle toggle on pricing page | NOT_REVIEWED | |
| T.3 | "Start free trial" CTA carrying plan + cycle into signup | NOT_REVIEWED | |
| T.4 | Public plan catalogue list (unauthenticated) | NOT_REVIEWED | |
| T.5 | Single plan lookup | NOT_REVIEWED | |
| T.6 | View current subscription (plan, status, seats, usage, trial) | NOT_REVIEWED | |
| T.7 | Billing page — current-plan card | NOT_REVIEWED | |
| T.8 | Billing page — seats card | NOT_REVIEWED | |
| T.9 | Billing page — usage-meter bars | NOT_REVIEWED | |
| T.10 | Billing page — invoice history table | NOT_REVIEWED | |
| T.11 | Upgrade modal (pick plan + cycle + seats) | NOT_REVIEWED | |
| T.12 | Start Stripe Checkout / "Continue to payment" | NOT_REVIEWED | |
| T.13 | Checkout success landing + polling until webhook lands | NOT_REVIEWED | |
| T.14 | Checkout cancel landing + "Try again" | NOT_REVIEWED | |
| T.15 | Change plan / billing cycle (no UI caller) | NOT_REVIEWED | |
| T.16 | Seat change cost preview (live on +/−) | NOT_REVIEWED | |
| T.17 | Add seats (prorated Stripe charge) | NOT_REVIEWED | |
| T.18 | Reduce seats (scheduled at period boundary) | NOT_REVIEWED | |
| T.19 | Trial-cannot-add-seats guard | NOT_REVIEWED | |
| T.20 | Cancel subscription (no UI button) | NOT_REVIEWED | |
| T.21 | Trial banner + days-remaining countdown | NOT_REVIEWED | |
| T.22 | Trial-ended / read-only banner with Upgrade CTA | NOT_REVIEWED | |
| T.23 | Past-due "payment failed → update card" banner | NOT_REVIEWED | |
| T.24 | Archived / cancelled "contact support" banner | NOT_REVIEWED | |
| T.25 | Feature-lock tile (page + inline variants) | NOT_REVIEWED | |
| T.26 | `*crmRequiresFeature` entitlement structural directive | NOT_REVIEWED | |
| T.27 | Frontend entitlement lookup (plan tier → feature key) | NOT_REVIEWED | |
| T.28 | Backend entitlement enforcement + usage-cap decorator | NOT_REVIEWED | |
| T.29 | Read-only / archived / past-due write blocking (402 + upgrade URL) | NOT_REVIEWED | |
| T.30 | Stripe webhook — `checkout.session.completed` (activates subscription) | NOT_REVIEWED | |
| T.31 | Stripe webhook — `invoice.paid` | NOT_REVIEWED | |
| T.32 | Stripe webhook — `invoice.finalized` | NOT_REVIEWED | |
| T.33 | Stripe webhook — `invoice.payment_failed` (→ past due) | NOT_REVIEWED | |
| T.34 | Stripe webhook — `customer.subscription.updated` | NOT_REVIEWED | |
| T.35 | Stripe webhook — `customer.subscription.deleted` | NOT_REVIEWED | |
| T.36 | Webhook signature verification + dedup ledger | NOT_REVIEWED | |
| T.37 | Usage metering per capped resource (contacts, storage, sends, API calls…) | NOT_REVIEWED | |
| T.38 | Hourly billing-period rollover + monthly counter reset (job) | NOT_REVIEWED | |
| T.39 | Midnight-UTC daily counter reset (job) | NOT_REVIEWED | |
| T.40 | Trial lifecycle advance (trialing → read-only → archived → deleted) (job) | NOT_REVIEWED | |
| T.41 | "Trial ending soon" reminder emails (job) | NOT_REVIEWED | |
| T.42 | Trial provisioning on signup | NOT_REVIEWED | |
| T.43 | Open-redirect rejection on checkout success / cancel URLs | NOT_REVIEWED | |

---

### U. Users, Roles & Permissions (RBAC)

Who is in the workspace and what they may do. Backend: `API/src/app/core/users/`, `.../core/permissions/`, `.../core/invitations/`, and ownership transfer in `.../core/tenants/`. Frontend: the Settings → Team and Settings → Roles tabs.

**Scope note:** the recipient-facing accept-invite page and its endpoints are reviewed as **A.28**; this module covers the sender side (invite, list, revoke).

**Known flag at map time:** `POST /api/v1/users` (create a user directly) is live and permission-gated but has no frontend caller — the UI only invites.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| U.1 | List org users | NOT_REVIEWED | |
| U.2 | Create user directly (no UI caller) | NOT_REVIEWED | |
| U.3 | Edit user inline (name, phone, role) | NOT_REVIEWED | |
| U.4 | Activate a user | NOT_REVIEWED | |
| U.5 | Deactivate a user (two-step offboarding modal) | NOT_REVIEWED | |
| U.6 | Pre-deactivation open-records count | NOT_REVIEWED | |
| U.7 | Bulk record reassignment on offboarding | NOT_REVIEWED | |
| U.8 | Invite a member (email + role) | NOT_REVIEWED | |
| U.9 | List pending invitations | NOT_REVIEWED | |
| U.10 | Revoke a pending invitation | NOT_REVIEWED | |
| U.11 | Copy invite link to clipboard | NOT_REVIEWED | |
| U.12 | List roles with permission / member counts | NOT_REVIEWED | |
| U.13 | Create custom role | NOT_REVIEWED | |
| U.14 | Edit custom role (rename + replace permission grants) | NOT_REVIEWED | |
| U.15 | Delete custom role | NOT_REVIEWED | |
| U.16 | Permission matrix editor (global permission registry) | NOT_REVIEWED | |
| U.17 | List role templates (with installed flag) | NOT_REVIEWED | |
| U.18 | Install a role template | NOT_REVIEWED | |
| U.19 | Transfer org ownership (typed confirmation + demote-to-role) | NOT_REVIEWED | |
| U.20 | System-role immutability guard (PATCH/DELETE → 403) | NOT_REVIEWED | |

---

### V. Staff & Staff Portal

Two surfaces for the same people: the manager-facing staff dashboard inside the CRM, and the separate PIN-login tablet portal for shop-floor staff. Backend: `API/src/app/core/staff/`, `.../core/staff_portal/`. Frontend: `APP/src/app/features/user/core/staff/` and the top-level `APP/src/app/staff-portal/`.

**Known flags at map time:** **staff PIN setup has no endpoint and no UI** — the PIN hash is verified at portal login but `StaffProfileUpsert` carries no `pin` field, so PINs appear to be seeded via CLI only. That makes the tablet portal effectively unprovisionable from the product. Also, the Stock Updates and Store Marketing dashboard tabs are placeholder stubs, and the staff KPI header values (`presentToday`, `totalRevenue`, `todaysRevenue`) are hardcoded zeros.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| V.1 | Staff dashboard shell with KPI header | NOT_REVIEWED | |
| V.2 | Staff directory / list | NOT_REVIEWED | |
| V.3 | Staff Overview tab | NOT_REVIEWED | |
| V.4 | Staff Leaderboard tab | NOT_REVIEWED | |
| V.5 | Staff Targets & Commission tab | NOT_REVIEWED | |
| V.6 | Staff Attendance tab | NOT_REVIEWED | |
| V.7 | Staff Activity Log tab | NOT_REVIEWED | |
| V.8 | Staff Field Operations tab | NOT_REVIEWED | |
| V.9 | Add / edit staff profile (commission, target, rating, employment, join date) | NOT_REVIEWED | |
| V.10 | Per-staff performance metrics | NOT_REVIEWED | |
| V.11 | Admin clock-in for a staff member | NOT_REVIEWED | |
| V.12 | Admin clock-out for a staff member | NOT_REVIEWED | |
| V.13 | Staff-portal user picker (tablet, unauthenticated) | NOT_REVIEWED | |
| V.14 | Staff-portal PIN login (→ short-lived staff token) | NOT_REVIEWED | |
| V.15 | Staff-portal session guard + token expiry | NOT_REVIEWED | |
| V.16 | Staff-portal shell / navigation | NOT_REVIEWED | |
| V.17 | Staff-portal — My Dashboard (home + performance) | NOT_REVIEWED | |
| V.18 | Staff-portal — My Attendance + self clock-in | NOT_REVIEWED | |
| V.19 | Staff-portal — self clock-out | NOT_REVIEWED | |
| V.20 | Staff-portal — My Activity log | NOT_REVIEWED | |
| V.21 | Staff-portal — My Sales | NOT_REVIEWED | |
| V.22 | Staff-portal — Stock Updates | NOT_REVIEWED | |
| V.23 | Staff-portal — Field Visits page (backed by the furniture field-ops module; see AB) | NOT_REVIEWED | |
| V.24 | Staff PIN setup / rotation (no endpoint or UI — gap) | NOT_REVIEWED | |

---

### W. Customization Platform

The engine that lets each org reshape forms and views without code — custom fields, dynamic form rendering, standard-field overrides, saved views. Backend: `API/src/app/core/custom_fields/`, `.../standard_fields/`, `.../saved_views/`. Frontend: `.../core/custom-fields/`, `.../core/standard-fields/`, `.../core/shared/dynamic-form/`.

**Known flag at map time:** the saved-views backend accepts `entity` as `Literal["leads"]` only — the leads list is its sole consumer; no other entity is wired.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| W.1 | Custom-field definitions CRUD (per entity: contact / lead / walk-in / appointment / task) | NOT_REVIEWED | |
| W.2 | Reorder custom fields (drag-and-drop, persists display order) | NOT_REVIEWED | |
| W.3 | Dynamic-form render contract (`GET /custom-fields/{entity}/render`) | NOT_REVIEWED | |
| W.4 | Dynamic form renderer (host + per-field renderer + validators) | NOT_REVIEWED | |
| W.5 | Standard-field overrides (per-org label / required / hidden / min / max) | NOT_REVIEWED | |
| W.6 | Standard-field render contract (merged defaults + overrides) | NOT_REVIEWED | |
| W.7 | Saved views CRUD (mine / shared) | NOT_REVIEWED | |

---

### X. Settings & Integrations

The settings shell and its permission-filtered tabs, plus the Integrations hub. Backend: `API/src/app/core/settings/`, `.../core/integrations/` (hub only). Frontend: `APP/src/app/features/user/core/settings/`.

**Scope note:** several tabs are *hosted* here but *owned* elsewhere (Team/Roles → U, Email Accounts/Sender Setup → M, Custom Fields/Standard Fields → W, Embed Widget → I). For those rows, review the tab's mounting, permission gate, and wiring — the inner feature is reviewed in its owning module. Likewise, provider-specific connect/webhook flows belong to their home modules (I, K, M); this module covers the generic hub. The Lead Scoring Rules page is reviewed as **E.14**.

**Known flag at map time:** orphaned `settings/email-sequences/*` components still exist even though the tab was removed and the route now redirects to Workflows.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| X.1 | Settings shell with permission-filtered tab bar + initial-tab resolution | NOT_REVIEWED | |
| X.2 | Tab: Profile (self-service name / phone edit + password change) | NOT_REVIEWED | |
| X.3 | Tab: Appearance | NOT_REVIEWED | |
| X.4 | Tab: Notifications (per-user preferences) | NOT_REVIEWED | |
| X.5 | Tab: Two-factor | NOT_REVIEWED | |
| X.6 | Tab: Login history | NOT_REVIEWED | |
| X.7 | Tab: Store Profile (org settings) | NOT_REVIEWED | |
| X.8 | Tab: Team (hosts module U) | NOT_REVIEWED | |
| X.9 | Tab: Roles (hosts module U) | NOT_REVIEWED | |
| X.10 | Tab: Email Accounts (hosts module M) | NOT_REVIEWED | |
| X.11 | Tab: Sender Setup (hosts module M) | NOT_REVIEWED | |
| X.12 | Tab: AI Settings | NOT_REVIEWED | |
| X.13 | Tab: Send Rules — quiet hours + frequency cap | NOT_REVIEWED | |
| X.14 | Tab: Custom Fields (hosts module W) | NOT_REVIEWED | |
| X.15 | Tab: Standard Fields (hosts module W) | NOT_REVIEWED | |
| X.16 | Tab: Embed Widget (hosts module I) | NOT_REVIEWED | |
| X.17 | Integrations hub page (top-level module + legacy redirect) | NOT_REVIEWED | |
| X.18 | Integrations hub — list connected providers | NOT_REVIEWED | |
| X.19 | Integrations hub — disconnect a provider | NOT_REVIEWED | |
| X.20 | Integrations hub — per-provider delivery status tiles (polled) | NOT_REVIEWED | |
| X.21 | Integrations hub — rotate webhook secret | NOT_REVIEWED | |
| X.22 | Profile deep-link redirect (`/user/profile` → Settings) | NOT_REVIEWED | |

---

### Y. Notifications

In-app notification bell, live WebSocket push, and per-type preferences. Backend: `API/src/app/core/notifications/` (+ `ws.py`). Frontend: `APP/src/app/features/user/core/notifications/`.

**Known flag at map time:** the preferences endpoints exist server-side, but `notifications-api.service.ts` exposes only list / markRead / markAllRead / WebSocket — confirm where (or whether) the preferences UI is actually wired before treating it as live.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| Y.1 | In-app notification bell + unread badge | NOT_REVIEWED | |
| Y.2 | Notification popover list (lazy fetch on first open) | NOT_REVIEWED | |
| Y.3 | Initial unread count + list on header init | NOT_REVIEWED | |
| Y.4 | Mark a single notification read | NOT_REVIEWED | |
| Y.5 | Mark all notifications read | NOT_REVIEWED | |
| Y.6 | Click-through deeplink from a notification | NOT_REVIEWED | |
| Y.7 | WebSocket live push (JWT + live-session verified before accept) | NOT_REVIEWED | |
| Y.8 | Live toast on incoming notification | NOT_REVIEWED | |
| Y.9 | Socket teardown on logout | NOT_REVIEWED | |
| Y.10 | List notification preferences | NOT_REVIEWED | |
| Y.11 | Update a notification-type preference (channel toggles) | NOT_REVIEWED | |

---

### Z. AI Assistant

AI touchpoints across the product. Backend: `API/src/app/core/ai/` and `.../core/integrations/whatsapp/ai_handler.py`.

**Known flags at map time — read before reviewing anything here.** There is **no standalone AI module**: `APP/.../core/ai/` contains only a `.gitkeep`, and `API/src/app/core/ai/` contains a single file whose `_invoke_llm` is an explicitly-documented **deterministic heuristic stub** — regex matching on hours/price/greeting, with confidence derived from word count. **No LLM vendor SDK is called anywhere in the codebase.** Every row below runs on canned responses, not a model. The surrounding plumbing (settings, escalation, badges, metrics) is genuinely live and well-built; only the intelligence is absent.

Capabilities that **do not exist** (no rows created, but worth raising in Phase 1): AI chatbot / suggest-reply inside Conversations, AI auto follow-up generation, AI summarization, and AI lead scoring. Also note **two competing, unconnected AI settings surfaces** exist — the scaffolded Settings → AI tab and the live WhatsApp → Automation → AI settings.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| Z.1 | LLM invocation core (`generate_response` → `_invoke_llm`) — heuristic stub | NOT_REVIEWED | |
| Z.2 | WhatsApp AI agent auto-responder (inbound → AI reply) | NOT_REVIEWED | |
| Z.3 | AI confidence-threshold handover to a human | NOT_REVIEWED | |
| Z.4 | AI handover-keyword short-circuit (skip AI, escalate immediately) | NOT_REVIEWED | |
| Z.5 | AI escalation → auto-assign a human (reuses assignment engine) | NOT_REVIEWED | |
| Z.6 | AI settings editor (default-enable, threshold, handover keywords, system prompt) | NOT_REVIEWED | |
| Z.7 | Per-conversation "Let AI handle it" toggle | NOT_REVIEWED | |
| Z.8 | AI-Handled / Needs-Human status pill on the thread header | NOT_REVIEWED | |
| Z.9 | "AI Handled" badge in the conversation list | NOT_REVIEWED | |
| Z.10 | AI badge on AI-authored message bubbles | NOT_REVIEWED | |
| Z.11 | AI metrics report widget (AI vs human, response + escalation rates) | NOT_REVIEWED | |
| Z.12 | AI conversation-history context builder (rolling 20-turn window) | NOT_REVIEWED | |
| Z.13 | Org-wide AI master switch + personality / welcome message (scaffolded, no consumer) | NOT_REVIEWED | |
| Z.14 | AI in reviews automation (scaffolded, no backend) | NOT_REVIEWED | |

---

### AA. Audit & Activity Logs

The tamper-evidence trail: who did what, when. Backend: `API/src/app/core/audit/`.

**Known flag at map time:** there is **no audit-log viewer in the frontend**. The endpoint, permission key, and org-wide writer surface all exist, but a full-text search across `APP/src` finds no viewer page or route — the log is write-only from a user's perspective. (`audit.full_log` is an enterprise-tier feature key, so this may be deliberate sequencing rather than an oversight — confirm during Phase 1.)

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| AA.1 | Audit log list (paginated) | NOT_REVIEWED | |
| AA.2 | Filter audit log by action | NOT_REVIEWED | |
| AA.3 | Filter audit log by entity type | NOT_REVIEWED | |
| AA.4 | Filter audit log by date range | NOT_REVIEWED | |
| AA.5 | Tenant isolation on audit reads | NOT_REVIEWED | |
| AA.6 | Security / audit event recording (org-wide writer surface) | NOT_REVIEWED | |
| AA.7 | Audit-derived integration delivery counts | NOT_REVIEWED | |

---

### AB. Furniture Pack (Layer 2)

The furniture vertical: inventory and warehouses, made-to-order custom orders, field visits (measurement/installation), and point-of-sale invoicing. Backend: `API/src/app/packs/furniture/modules/` plus `API/src/app/core/billing/` (invoice CRUD). Frontend: `APP/src/app/features/user/packs/furniture/`.

**Known flags at map time:** three declared pack modules — **marketplace (Amazon/Flipkart/Shopify), QR marketing, and virtual staging** — are **entirely scaffolded**: each has only an empty `__init__.py` on the backend (no router, service, models, or descriptor) and only a `.gitkeep` on the frontend. No routes, no endpoints, no functionality. No rows are created for them. Several inventory and custom-order endpoints are also live with no UI to reach them (flagged per row).

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| AB.1 | Inventory products list (Products tab) | NOT_REVIEWED | |
| AB.2 | Products grid / list view toggle | NOT_REVIEWED | |
| AB.3 | Product search / category / warehouse filtering | NOT_REVIEWED | |
| AB.4 | Add product (modal; atomic catalog + inventory row) | NOT_REVIEWED | |
| AB.5 | Product cover image upload (chained off Add Product) | NOT_REVIEWED | |
| AB.6 | Edit product (endpoint live; no UI entry point) | NOT_REVIEWED | |
| AB.7 | Delete product (endpoint live; no UI entry point) | NOT_REVIEWED | |
| AB.8 | Product card detail display (cover, SKU, price, on-hand qty) | NOT_REVIEWED | |
| AB.9 | Stock alerts tab (low / out-of-stock, severity + status filters) | NOT_REVIEWED | |
| AB.10 | Refresh stock alerts | NOT_REVIEWED | |
| AB.11 | Mark alert as "Ordered" via reorder modal | NOT_REVIEWED | |
| AB.12 | Mark alert closed | NOT_REVIEWED | |
| AB.13 | Warehouse CRUD (backend live; read-only in UI, no management screen) | NOT_REVIEWED | |
| AB.14 | Stock movement history per item (backend live; no UI) | NOT_REVIEWED | |
| AB.15 | Record stock movement (receipt / adjust / dispatch / transfer) | NOT_REVIEWED | |
| AB.16 | Custom orders list view | NOT_REVIEWED | |
| AB.17 | Custom orders pipeline / kanban view | NOT_REVIEWED | |
| AB.18 | Move order stage by drag-and-drop | NOT_REVIEWED | |
| AB.19 | Create custom order (multi-step modal: contact → details → measurements → photos) | NOT_REVIEWED | |
| AB.20 | Contact search / select inside the order modal | NOT_REVIEWED | |
| AB.21 | Add / remove measurement rows during order creation | NOT_REVIEWED | |
| AB.22 | Attach / remove photos during order creation | NOT_REVIEWED | |
| AB.23 | Custom order detail page | NOT_REVIEWED | |
| AB.24 | Custom order detail — measurements panel | NOT_REVIEWED | |
| AB.25 | Custom order detail — photos gallery | NOT_REVIEWED | |
| AB.26 | Custom order stage-history timeline (backend live; render unconfirmed) | NOT_REVIEWED | |
| AB.27 | Edit / delete custom order (endpoints live; detail page appears read-only) | NOT_REVIEWED | |
| AB.28 | Field visits list | NOT_REVIEWED | |
| AB.29 | Field visits status filter tabs (open / completed / all) | NOT_REVIEWED | |
| AB.30 | Schedule a field visit (contact, purpose, date/time, assignee) | NOT_REVIEWED | |
| AB.31 | Field visit detail page | NOT_REVIEWED | |
| AB.32 | Complete a field visit (with measurement capture) | NOT_REVIEWED | |
| AB.33 | Add / remove measurement rows in the complete-visit modal | NOT_REVIEWED | |
| AB.34 | Field visit photos — list + multipart upload with caption | NOT_REVIEWED | |
| AB.35 | Cross-link from a field visit to its custom order | NOT_REVIEWED | |
| AB.36 | Update / delete field visit (endpoints live; no UI traced) | NOT_REVIEWED | |
| AB.37 | Staff portal — my assigned field visits queue | NOT_REVIEWED | |
| AB.38 | Staff portal — mark a visit complete on the spot | NOT_REVIEWED | |
| AB.39 | Staff portal — open / done visit counters | NOT_REVIEWED | |
| AB.40 | Staff portal — visit detail + photos (backend live; partial UI) | NOT_REVIEWED | |
| AB.41 | Billing page tab switcher (Invoices / POS) | NOT_REVIEWED | |
| AB.42 | Invoice list | NOT_REVIEWED | |
| AB.43 | Invoice status filter chips (draft / issued / paid / void) | NOT_REVIEWED | |
| AB.44 | Invoice detail page | NOT_REVIEWED | |
| AB.45 | Invoice payments list on detail | NOT_REVIEWED | |
| AB.46 | Invoice print / PDF download | NOT_REVIEWED | |
| AB.47 | POS product catalog browse + add to cart | NOT_REVIEWED | |
| AB.48 | POS cart line quantity +/− and line removal | NOT_REVIEWED | |
| AB.49 | POS clear cart | NOT_REVIEWED | |
| AB.50 | POS discount entry (flat / percent) | NOT_REVIEWED | |
| AB.51 | POS payment method selection (cash / card / UPI / EMI / cheque / bank) | NOT_REVIEWED | |
| AB.52 | POS checkout / complete sale (single transaction: contact → invoice → issue → pay → stock dispatch) | NOT_REVIEWED | |
| AB.53 | POS walk-in contact auto-create by phone | NOT_REVIEWED | |
| AB.54 | Record an additional payment on an invoice (service method; no UI button) | NOT_REVIEWED | |
| AB.55 | Void an invoice (service method; no UI button) | NOT_REVIEWED | |
| AB.56 | Overdue-invoice scan job (fires `invoice.overdue_7d`) | NOT_REVIEWED | |

---

### AC. Real Estate Pack (Layer 2)

The real-estate vertical: property listings with a full publish lifecycle and token-gated public pages. Backend: `API/src/app/packs/real_estate/modules/property/` (+ `public_router.py`). Frontend: `APP/src/app/features/user/packs/real_estate/property/` and the public `APP/src/app/features/public/`.

**Scope note:** the pack contains **only** the property module — no other sub-modules exist. The demo-data seeder and pack installer are developer CLI scripts, not user-triggerable, so they get no rows.

| ID | Functionality | Status | Notes |
|----|---------------|--------|-------|
| AC.1 | Property listing list (table with pagination) | NOT_REVIEWED | |
| AC.2 | Property list status tabs with counts (draft/published/unpublished/archived/sold) | NOT_REVIEWED | |
| AC.3 | Property list filters (type, category, city, search, owner, price range, sort) | NOT_REVIEWED | |
| AC.4 | Property list pagination | NOT_REVIEWED | |
| AC.5 | Create property | NOT_REVIEWED | |
| AC.6 | Edit property | NOT_REVIEWED | |
| AC.7 | Open property from list row | NOT_REVIEWED | |
| AC.8 | Amenities multi-entry input | NOT_REVIEWED | |
| AC.9 | Property image upload (multi-file, type + size validated) | NOT_REVIEWED | |
| AC.10 | Delete a property image (with confirm) | NOT_REVIEWED | |
| AC.11 | Set featured image | NOT_REVIEWED | |
| AC.12 | Reorder property images (endpoint + client method; drag UI unconfirmed) | NOT_REVIEWED | |
| AC.13 | Publish property (blocked when no images) | NOT_REVIEWED | |
| AC.14 | Unpublish property | NOT_REVIEWED | |
| AC.15 | Archive property (with confirm) | NOT_REVIEWED | |
| AC.16 | Unarchive property (returns to draft) | NOT_REVIEWED | |
| AC.17 | Mark property sold | NOT_REVIEWED | |
| AC.18 | Delete property (hard delete, with confirm) | NOT_REVIEWED | |
| AC.19 | Copy public URL to clipboard (mints Fernet token) | NOT_REVIEWED | |
| AC.20 | Clipboard-blocked fallback modal | NOT_REVIEWED | |
| AC.21 | Preview public listing in a new tab | NOT_REVIEWED | |
| AC.22 | Status-aware row action menu (per-status, permission-gated action sets) | NOT_REVIEWED | |
| AC.23 | Optimistic status update + revert on error | NOT_REVIEWED | |
| AC.24 | Public property grid by org slug (unauthenticated) | NOT_REVIEWED | |
| AC.25 | Public property card → detail link | NOT_REVIEWED | |
| AC.26 | Public property detail page (Fernet-token gated, published-only) | NOT_REVIEWED | |
| AC.27 | Public detail image carousel (prev / next) | NOT_REVIEWED | |
| AC.28 | Public detail thumbnail strip selection | NOT_REVIEWED | |
| AC.29 | Public detail — call agent (tel: link) | NOT_REVIEWED | |
| AC.30 | Public detail — email agent (mailto: link) | NOT_REVIEWED | |
| AC.31 | Public shell (unauthenticated layout wrapper) | NOT_REVIEWED | |
| AC.32 | Public asset URL resolution for images | NOT_REVIEWED | |

---

## 6. Notes on coverage

- **Intentionally excluded — not part of Core CRM:**
  - `APP/src/app/features/admin/` — the legacy template's admin panel. `CLAUDE.md` marks it untouched indefinitely; it is not part of this product.
  - `AixoApp/` — a rebranded white-label copy of the frontend. Development happens in `APP/` + `API/`; reviewing the fork would double every row.
  - `Flutter/` — explicitly not part of this product.
  - The legacy **non-auth** template routers mounted at `/api/...` (app-config, routes/config, common scaffolding). The legacy **auth** endpoints *are* in scope, because they still back live login, 2FA, and login-history surfaces.
- **Conventions are documented, not inferred.** The code-organization lens (§3.6) is judged against real rulebooks in this repo: [`CLAUDE.md`](CLAUDE.md), [`tasks/README.md`](tasks/README.md), and `API/docs/DATABASE_RULES.md`. Two of these are CI-enforced by pin-tests (the `tbl_` table-naming rule and the Router→Service→DAL layering rule), so drift is a build failure, not an opinion.
- **The folder names in `CLAUDE.md` are aspirational.** That doc describes a post-rename layout (`api/`, `app/`); on disk the live folders are still `API/` and `APP/`. Trace against what exists, not what the doc predicts.
- **`CLAUDE.md` understates what is built.** It frames the project as "Layer 1 core only", but Workflows, Automations, the full WhatsApp platform, SaaS billing, ad integrations, and two vertical packs are all live and routed. This checklist reflects the live product.
- **Vertical packs are included** (modules AB, AC) by explicit decision, because their routes are live and reachable today — even though `CLAUDE.md` marks Layer 2 as parked.
- **Background jobs are listed as rows.** Celery beat sweeps and queued send jobs are user-facing in effect (a user's action or a user's data causes them to run) and carry real correctness, security, and cost risk, so they are reviewed like any screen.
- **Rows flagged "scaffolded" / "UI-only" / "not wired" are kept, not dropped.** A feature that looks present to a user but does nothing is a real finding, and the review should confirm and record it rather than silently skip it.
- **`[VERIFY]` markers**, where present in a row, mean the mapping pass could not fully confirm the wiring. Confirm it first during that item's review.

---

## 7. Progress summary

| Metric | Count |
|--------|-------|
| **Total functionalities** | **677** across 29 modules |
| Reviewed | 0 |
| Needs fix | 0 |
| In progress | 0 |
| Pending | 677 |

Per-module totals (useful for planning how many sessions a module will take):

| Module | Count | | Module | Count | | Module | Count |
|---|---|---|---|---|---|---|---|
| A. Authentication | 33 | | K. WhatsApp Platform | 85 | | U. RBAC | 20 |
| B. Onboarding | 7 | | L. Calls | 18 | | V. Staff & Portal | 24 |
| C. Shell & Dashboard | 19 | | M. Email | 32 | | W. Customization | 7 |
| D. Contacts | 16 | | N. Templates | 14 | | X. Settings & Integrations | 22 |
| E. Leads & Pipelines | 20 | | O. Automations | 16 | | Y. Notifications | 11 |
| F. Activities & Tasks | 13 | | P. Workflows | 32 | | Z. AI Assistant | 14 |
| G. Appointments & Walk-ins | 20 | | Q. Campaigns | 14 | | AA. Audit Logs | 7 |
| H. Catalog | 7 | | R. Reviews | 7 | | AB. Furniture Pack | 56 |
| I. Lead Capture | 56 | | S. Reporting | 2 | | AC. Real Estate Pack | 32 |
| J. Conversations | 29 | | T. Billing & Subscription | 43 | | | |

Update this table as reviews complete. Also update the whole-project Phase 0 pass status here once it has been run and approved:

| Pass | Status |
|------|--------|
| Phase 0 — whole-project bird's-eye | NOT_REVIEWED |
