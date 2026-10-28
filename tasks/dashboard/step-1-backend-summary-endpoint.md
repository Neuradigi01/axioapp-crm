# Step 1 — Backend dashboard summary endpoint

**Goal:** Stand up `GET /api/v1/dashboard/summary` — a single aggregation endpoint that returns the cards + recent activity + upcoming appointments the dashboard page needs. The shape of the response adapts to the caller's permissions: Owner/Admin/anyone with `users.read` gets org-wide aggregates; Employee/anyone without gets personal-scope.
**Track:** Dashboard
**Status:** COMPLETED
**Depends on:** Phase 1.5/1.6 (auth + perms), Phase 2 (contacts/leads/tasks/appointments/calls/activities exist).

---
 
## Scope

One new core module — `api/src/app/core/dashboard/` — with three small files (service, router, schemas) plus a one-line registration in `main.py`. No database changes. No new permission keys. Pure aggregation over existing tenant-scoped tables.

## Response shape

```json
{
  "greeting": {
    "first_name": "Ajay",
    "role_name": "Owner",
    "org_name": "Ajay's Workspace"
  },
  "scope": "org",
  "cards": [
    { "key": "leads.new_today",       "label": "New leads today",       "value": 7,        "format": "number",   "link": "/user/leads?since=today" },
    { "key": "leads.pipeline_value",  "label": "Total pipeline value",  "value": 1240000,  "format": "currency", "link": "/user/leads" },
    { "key": "tasks.open_count",      "label": "Open tasks (team)",     "value": 23,       "format": "number",   "link": "/user/tasks" },
    { "key": "appointments.today",    "label": "Today's appointments",  "value": 4,        "format": "number",   "link": "/user/appointments" },
    { "key": "calls.this_week",       "label": "Calls this week",       "value": 89,       "format": "number",   "link": "/user/calls" },
    { "key": "contacts.total",        "label": "Total contacts",        "value": 412,      "format": "number",   "link": "/user/contacts" }
  ],
  "recent_activity": [
    { "action": "leads.created",          "entity_label": "Anil Kumar",   "actor_name": "Sarah K.", "at": "2026-05-21T11:30:00Z" },
    { "action": "appointments.scheduled", "entity_label": "Site Visit",   "actor_name": "You",      "at": "2026-05-21T10:45:00Z" }
  ],
  "upcoming_appointments": [
    { "id": "...", "title": "Demo with Rajesh", "starts_at": "2026-05-21T14:00:00Z", "with_contact_name": "Rajesh Mehta" }
  ]
}
```

`scope` is `"org"` or `"personal"` — a hint the frontend can render in the header ("Showing team data" vs "Showing your data"). The frontend doesn't make routing decisions off it; cards already differ in label/value.

## Card catalogue

Two sets — org-wide and personal — assembled from the same underlying queries with a different filter applied.

### Org-wide (gated on `users.read`)

| Card key | Source | Filter | Format |
|---|---|---|---|
| `leads.new_today` | `leads` | `created_at::date = current_date` | number |
| `leads.pipeline_value` | `leads` | `pipeline_stage NOT IN (won, lost)` and a `value` field if present (else count of open leads) | currency or number |
| `tasks.open_count` | `tasks` | `is_done=false` | number |
| `appointments.today` | `appointments` | `starts_at::date = current_date` | number |
| `calls.this_week` | `calls` | `created_at >= date_trunc('week', now())` | number |
| `contacts.total` | `contacts` | `(none)` | number |
| `conversion.rate` | `leads` | `won / (won + lost)` × 100 over last 30 days | percent |
| `top_performers` | `tasks` + `leads` joined to `tbl_organization_members` | grouped by assignee, top 3 by `tasks.completed_this_week + leads.created_this_week` | list of 3 `{name, count}` (handled as a special-format card; first cut renders just top 1) |

### Personal (default — when `users.read` is missing)

Same shapes, scoped with `assigned_to = current_user_uuid` (or `created_by = current_user_uuid` where the entity has no assignee column).

| Card key | Source | Filter |
|---|---|---|
| `tasks.my_open` | `tasks` | `assigned_to = me AND is_done=false` |
| `leads.my_count` | `leads` | `assigned_to = me` |
| `appointments.my_today` | `appointments` | `assigned_to = me AND starts_at::date = today` |
| `calls.my_this_week` | `calls` | `created_by = me AND created_at >= week_start` |
| `contacts.my_count` | `contacts` | `owner = me` if owner field exists, else `created_by = me` |
| `conversion.my_rate` | `leads` | personal won/(won+lost) over last 30 days |

If a personal-scope card has no underlying owner/assigned_to column on the entity (e.g., `contacts` may not have one yet), drop it from the response rather than showing 0 — better to omit than mislead.

## Recent activity

Read `audit_logs` for the caller's org, filtered to user-relevant actions:

- Include: `leads.*`, `contacts.*`, `appointments.*`, `tasks.*`, `calls.*`, `walkins.*`, `walk_ins.*`, `reviews.*`, `invitations.sent`, `invitations.accepted`, `roles.assigned_to_user`, `ownership.transferred`
- Exclude: `auth.login.*`, `auth.password.changed`, `auth.access_denied`, `users.self_updated`

For personal scope, additionally filter `user_id = current_user_uuid` so the user only sees actions they performed.

Limit 10, ordered `created_at DESC`.

`entity_label` is best-effort:
- For leads/contacts: join to fetch `full_name` (contacts) or the lead's contact name
- For appointments: the `title` column
- For tasks: the `title` column
- For invitations: the email
- Fall back to `entity_type:entity_id` if a lookup misses

`actor_name` resolves `user_id` → `UserInfo.first_name + last_name`, or `"You"` when it's the caller. Falls back to `"System"` if `user_id` is null.

## Upcoming appointments

`appointments` filtered `starts_at > now()` ordered ASC, limit 5. Personal scope adds `assigned_to = me`.

Each row carries `{ id, title, starts_at, with_contact_name }` — the contact name is a join lookup; falls back to empty string if appointment has no contact.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/dashboard/__init__.py` | created (module marker) |
| `api/src/app/core/dashboard/service.py` | created — assemble cards, activity, upcoming |
| `api/src/app/core/dashboard/router.py` | created — `GET /dashboard/summary` |
| `api/src/app/core/dashboard/schemas.py` | created — Pydantic v2 response shapes |
| `api/src/app/main.py` | modified — register `dashboard_router` |
| `api/tests/test_dashboard_summary.py` | created — happy paths for org + personal scope; missing-column resilience |

**6 files. No migrations. No new permission keys.**

## Plan

1. Create the `core/dashboard/` package with the three module files.
2. In `service.py`:
   - `is_org_scope(user)` — wraps the `users.read` permission check.
   - `_assemble_org_cards(session, org_id)` — runs the org-wide queries, returns a list of `DashboardCard`. Each query is a `SELECT COUNT(*)` or `SUM(value)` — no joins beyond the existing tenant filter.
   - `_assemble_personal_cards(session, org_id, user_uuid, member_bigint_id)` — same shape, with `assigned_to` / `created_by` filter applied.
   - `_recent_activity(session, org_id, user_uuid_filter)` — reads `audit_logs`, applies the include-list, resolves `entity_label` and `actor_name`.
   - `_upcoming_appointments(session, org_id, user_uuid_filter)` — appointments query.
   - `get_summary(session, user)` — composes the above.
3. In `router.py`: `GET /summary`, gated by `get_current_user` (no specific permission key — every authenticated user has a dashboard).
4. Register the router in `main.py` next to the other v1 routers.
5. Tests: hit the endpoint as Owner, Admin, Employee from `core-demo`. Assert `scope` value, assert `cards[*].key` set, assert numbers come back as integers, assert recent activity items have `entity_label` resolved when possible.

## Tests

`api/tests/test_dashboard_summary.py`:

- **Owner gets org scope.** Login as `owner@core-demo.local` → `GET /dashboard/summary` → `scope == 'org'`; card keys include `leads.new_today`, `tasks.open_count`, `appointments.today` etc.
- **Admin gets org scope.** Login as `admin@core-demo.local` → same.
- **Employee gets personal scope.** Login as `employee@core-demo.local` → `scope == 'personal'`; card keys are the `*.my_*` variants; the employee's view of `tasks.my_open` matches the count of their assigned undone tasks.
- **Recent activity excludes login noise.** Create a couple of fixtures (a lead, a task assigned to the employee), force a login row, hit the endpoint, assert the lead/task appear but the `auth.login.success` row does not.
- **Personal upcoming respects assignment.** Insert two appointments — one assigned to employee, one to admin. As employee → only theirs shows.
- **Missing-column resilience.** If a personal-scope query can't run for an entity that has no `assigned_to` column, the card is omitted from the response rather than 500-ing.

## Smoke

```
docker exec template_api-api-1 pytest tests/test_dashboard_summary.py -v

# Manual curl as each demo role:
curl -s -H "Authorization: Bearer $OWNER_TOK"    http://localhost:8000/api/v1/dashboard/summary | jq '.scope, .cards[].key'
curl -s -H "Authorization: Bearer $EMPLOYEE_TOK" http://localhost:8000/api/v1/dashboard/summary | jq '.scope, .cards[].key'
```

Expected: owner returns `"org"` + `leads.new_today, leads.pipeline_value, tasks.open_count, appointments.today, calls.this_week, contacts.total, conversion.rate, top_performers`. Employee returns `"personal"` + `tasks.my_open, leads.my_count, appointments.my_today, calls.my_this_week, contacts.my_count?, conversion.my_rate`.

## Risks

- **Schema variance across modules.** `leads` may not have a `value` field; `contacts` may not have `owner`. Each card builder must check the column exists (via SQLAlchemy's `inspect()` or a try/except scoped tight) and omit the card if not.
- **Audit-log volume on busy orgs.** `recent_activity` query has a `LIMIT 10` + `ORDER BY created_at DESC` — relies on the existing index on `audit_logs(created_at)`. If that index doesn't exist, this query is slow on million-row orgs. Verify before adding more cards that hit the same table.
- **N+1 on entity_label resolution.** Naive approach does a separate SELECT per audit row to resolve the entity. Mitigation: batch the lookups by entity_type, do one SELECT per type with `WHERE id IN (...)`. Acceptable for v1 with 10-row limit; revisit if we ever raise that limit.
- **Cross-tenant safety.** Every query MUST filter by `org_id`. Existing `TenantScoped` mixin handles this for the layered models; raw audit_logs query needs explicit `WHERE org_id = ?`.

## Rollback

Revert the 6 source files. No DB state to roll back. Frontend dashboard page (Step 2) will fail to load if shipped after rollback — ship/rollback together.
