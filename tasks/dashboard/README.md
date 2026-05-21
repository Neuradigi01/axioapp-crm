# Dashboard

A focused track for the `/user/dashboard` landing page — the first thing every signed-in user sees. Sits outside the numbered phase tree — vertical-neutral, ship-when-ready, picked up alongside whichever main phase is active.

## Why this exists

`/user/dashboard` is the route every freshly-signed-in user lands on (per Step 1 of RBAC: signup → `/user/dashboard`; per the login form: success → `/user`). Today the folder is empty — there is no dashboard page at all. The current "Welcome" component is a placeholder card; it shows no data, no recent activity, no KPIs. Every CRM has a real dashboard here; ours has a blank wall.

Three problems this track closes:

| Gap | What's missing today |
|---|---|
| **No KPIs on landing** | Owner / Admin / Employee all see the same "Welcome" card. No leads-this-week count, no tasks-due number, no calls-made tally, no pipeline value, no recent activity. |
| **No role differentiation** | Owners need org-wide numbers (team performance, total pipeline). Employees need personal numbers (my tasks, my leads). Currently both see nothing. |
| **No drill-in entry points** | Even when sections of the app have rich data (Leads kanban, Appointments calendar), Dashboard offers no way in. Each user has to remember to click each sidebar item. |

## Design decision — Pattern 1 (permission-scoped single dashboard)

After comparing four standard CRM patterns, this track adopts Pattern 1: **one route, one component, server returns a list of cards based on the caller's permissions**. See [tasks/README.md] for the full comparison; the short version:

- One `/user/dashboard` route shared by every role.
- Backend `GET /api/v1/dashboard/summary` looks at the caller's permission keys and assembles a `cards: [...]` list:
  - Has `users.read` (= Owner / Admin / Sales Manager / any custom role with that grant) → org-wide cards.
  - Lacks `users.read` (= Employee / Support Agent / any custom role without it) → personal "my work" cards.
- Frontend renders the cards generically. Adding a card later is one entry in the backend assembler + one branch in the template.

Custom roles, template roles, and the three default roles all work automatically. No per-role hardcoding in the UI, no role-name checks anywhere.

**Out of scope (deferred to a Pattern 3 follow-up track if/when needed):** widget catalog + drag-drop layout + per-user customization. Those are real features but only meaningful once we have data to put in widgets — which Pattern 1 ships first.

## What this does NOT do

- Does not build a widget library or per-user dashboard customization (Pattern 3 — future).
- Does not build a reports engine (`/user/reporting` is its own separate track).
- Does not add new permission keys. Reuses existing keys (`users.read`, `leads.read`, etc.) for the org-vs-personal branch.
- Does not change the sidebar — the Dashboard nav item is already there (or trivially added).
- Does not store per-user layouts. The `ui_preferences` JSONB column on `tbl_organization_members` (introduced in DR.7) stays untouched; reserved for the future Pattern 3 work.
- Does not implement a leaderboard tab on Dashboard. Staff module already has a leaderboard slot; Dashboard's "top performers" card is a small read of the same data.

## Acceptance criteria

A brand-new visitor signs up → lands at `/user/dashboard`. They see, **with no further clicks**:

1. **A greeting** ("Welcome back, {first_name}").
2. **6–8 KPI cards** appropriate to their role:
   - Owner / Admin: new leads today, total pipeline value, calls this week, open tasks across team, today's appointments (all), conversion rate, top performers (top 3).
   - Employee: my open tasks, my leads (count + value), my appointments today, my calls this week, my personal conversion rate.
3. **A recent activity feed** (last ~10 audit events filtered to user-relevant actions — created/updated/assigned/completed; excludes login/logout noise).
4. **An upcoming appointments strip** (next 5 across the org for Owner/Admin, personal for Employee).
5. **Every card links** to the relevant module page where they can drill in.

Same page, same component, same route — but the contents reshape based on permissions.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend dashboard summary endpoint](step-1-backend-summary-endpoint.md) | Pending | ~½ day |
| 2 | [Frontend dashboard page](step-2-frontend-dashboard-page.md) | Pending | ~½ day |

**Total: ~1 working day.** Each step independently verifiable; pause and report after each per rule 9.

## Dependencies

- Phase 1.5 / 1.6 (users + roles + auth) — Done. Permission-key reads drive the org-vs-personal branch.
- Phase 2 modules (contacts, leads, tasks, appointments, calls) — Done. Dashboard aggregates from these.
- RBAC Step 4 (route guards) — Done. Dashboard route is reached only by authenticated users (existing `furnitureAuthGuard`).

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend new | 4 — `service.py`, `router.py`, `schemas.py`, `__init__.py` | Lives in `api/src/app/core/dashboard/` |
| Backend modified | 1 — `main.py` (register router) | |
| Frontend new | 2 — `dashboard.page.ts`, `dashboard.page.html` | Lives in `app/src/app/features/user/core/dashboard/` |
| Frontend modified | 1 — `user.routes.ts` (wire route) + maybe sidebar entry | The folder already exists empty; adding a real page |
| Tests | 1 backend pytest file | Card-list permission branch coverage |

**~9 files. No migrations. No new permission keys.**

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| Same route, same component for all roles | Single `dashboard.page.ts`; no role-keyed components |
| Org-vs-personal branch driven by permission keys, not role names | Backend service inspects `user.role_id → permission_keys.has('users.read')` |
| Personal-scope queries always filter by `assigned_to = current_user` | Backend service builds the filter once, applies per query |
| Dashboard is read-only | No POST / PATCH / DELETE endpoints in the dashboard module — purely aggregation |
| RLS still authoritative for cross-tenant isolation | Aggregations go through the usual `TenantScoped` filter; no raw SQL bypassing RLS |

## Self-check against the 10 rules

- ✅ Rule 1: `core/dashboard/` never imports `packs/`. The aggregator reads from core models only (contacts, leads, tasks, appointments, calls). Pack-specific KPIs (inventory levels, custom orders status) are out of scope here.
- ✅ Rule 2: No new DB tables; no `org_id` schema changes. Aggregations read existing tenant-scoped tables.
- ✅ Rule 3: Custom fields layered model unaffected.
- ✅ Rule 4: No new dynamic forms.
- ✅ Rule 5: Sidebar registry unchanged. Dashboard nav entry uses the existing core descriptor.
- ✅ Rule 6: Permission registry unchanged. Track consumes existing keys (`users.read`, `leads.read`, etc.).
- ✅ Rule 7: `pack.yaml` untouched. Dashboard is core, not pack-specific.
- ✅ Rule 8: 9 files across 2 steps; each step < 30 min review.
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs. Cards either ship complete with real data or aren't shipped this round.

## After this track

- Every user — Owner, Admin, Employee, template roles, custom roles — has a meaningful landing page on first login.
- Reporting track becomes much smaller: it's "Dashboard's aggregations, but with filters + export."
- Foundation for the Pattern 3 widget-customization track later (the cards API becomes the widget API).
