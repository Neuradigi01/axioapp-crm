# Step 2 — Backend: `/api/v1/dashboard/followups` endpoint

**Goal:** One endpoint that returns everything the widget needs in a
single round-trip: today's follow-up list + the 5 KPI counts
(today_total / pending_today / completed_today / overdue /
missed_last_7d) + server-side filters + pagination.
**Status:** COMPLETED
**Depends on:** Step 1 (needs `followup_type` column).

---

## Scope

### New route

`GET /api/v1/dashboard/followups`

Query parameters (all optional):

- `bucket` — `today` (default) · `pending` · `completed_today` ·
  `overdue` · `missed`. The bucket decides the base date/status
  filter; a click on a KPI card passes this. Semantics per bucket
  (real `TaskStatus` is `open · done · cancelled · missed`):
  - `today` → `due_at::date = today AND status IN (open, done)`
    (skips `cancelled` and `missed` — actionable + already-done view)
  - `pending` → `due_at::date = today AND status = 'open'`
  - `completed_today` → `status = 'done' AND updated_at::date =
    today` (Task has no `completed_at`; `updated_at` bumps on the
    status transition and is the closest deterministic proxy)
  - `overdue` → `due_at < today AND status = 'open'` — `cancelled`
    and `missed` are both terminal closures, deliberately excluded
  - `missed` → `status = 'missed' AND updated_at::date >= today -
    7d` (last week's missed for the dashboard; older is on the Tasks
    page's Missed filter for audit)
- `assigned_to` — UUID · limits to that assignee (Owner/Admin only;
  ignored for Employee scope since they're already scoped to self)
- `followup_type` — one of the enum values
- `priority` — `high` · `med` · `low` (matches the real
  `TaskPriority` enum; the widget renders "Med" as "Medium")
- `q` — free-text search on the linked contact's name / phone /
  email OR the task title
- `page` (default 1) · `page_size` (default 20, max 50)

Response shape:

```json
{
  "scope": "org",
  "counts": {
    "today_total": 12,
    "pending_today": 8,
    "completed_today": 3,
    "overdue": 1,
    "missed_last_7d": 4
  },
  "page": 1,
  "page_size": 20,
  "total": 12,
  "items": [
    {
      "id": "…",
      "title": "Send quote PDF",
      "due_at": "2026-07-01T10:30:00+05:30",
      "priority": "high",
      "status": "open",
      "followup_type": "email",
      "notes_preview": "Customer requested v2 with fabric swatches…",
      "assigned_to": { "id": "…", "name": "Ajay Gogane" },
      "linked_entity": {
        "type": "lead",
        "id": "…",
        "label": "Rahul Sharma · Sofa selection"
      }
    }
  ]
}
```

### Scope + RBAC (server-decided, not client)

Mirrors the existing `dashboard/summary` pattern in
`core/dashboard/service.py`:

- Caller has `users.read` permission → `scope='org'`, endpoint returns
  every follow-up in the tenant.
- Otherwise → `scope='personal'`, endpoint filters to
  `assigned_to_id = caller`.

The `assigned_to` query param is ignored in personal scope so an
employee can't peek at a peer's follow-ups by URL-hacking.

### Layered breakdown

Follows the manager-locked Router → Service → DAL pattern:

- **`router.py`** — new `GET /followups` endpoint (thin — parses
  query params, calls service, returns response).
- **`service.py`** — `get_followups(session, caller, filters)` →
  returns `FollowupsResponse`. Resolves scope, applies bucket filter,
  runs both the list + counts queries in parallel with
  `asyncio.gather`.
- **`data_access.py`** — pure CRUD helpers:
  - `list_tasks_for_bucket(session, org_id, ..., limit, offset)` —
    the list query (returns rows + total).
  - `count_followups_by_bucket(session, org_id, ...)` — the 4
    aggregate counts in one grouped query.

### `q` (search) — where it hits

Search runs against:
- `tbl_tasks.title` (ILIKE)
- Linked contact's `full_name`, `email`, `phone` via `LEFT JOIN
  tbl_contacts ON tbl_tasks.related_entity_id = tbl_contacts.id AND
  tbl_tasks.related_entity_type = 'contact'`
- Linked lead's contact via a two-hop `LEFT JOIN tbl_leads ON
  tbl_tasks.related_entity_id = tbl_leads.id AND
  tbl_tasks.related_entity_type = 'lead' LEFT JOIN tbl_contacts ON
  tbl_leads.contact_id = tbl_contacts.id`

(Task has no direct `contact_id` — the polymorphic
`related_entity_type` / `related_entity_id` pair is the link, so
both joins are gated on the type discriminator.)

Trigram-index-friendly on tables where GIN pg_trgm already exists
(contacts have one). Tasks table gets no new index in this step;
the existing partial index on `(org_id, due_at)` carries most
queries. If the `q` filter becomes hot in profiling, add a trigram
index on `tbl_tasks.title` in a follow-up step.

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/dashboard/router.py` | EDIT — add `@router.get("/followups")` handler |
| `API/src/app/core/dashboard/service.py` | EDIT — add `get_followups()` service function |
| `API/src/app/core/dashboard/data_access.py` | **NEW** — first DAL file in this module; hosts the list + count queries |
| `API/src/app/core/dashboard/schemas.py` | EDIT — add `FollowupItem`, `FollowupCounts`, `FollowupsResponse`, `FollowupBucket` |
| `API/tests/dashboard/test_followups.py` | **NEW** (test file — deferred to Step 7) |

**~5 files touched, ~350 lines.**

---

## Verify

- `openapi.json` lists `GET /api/v1/dashboard/followups` with all
  documented query params.
- Curl smoke as Owner:
  ```bash
  curl -H "Authorization: Bearer $TOKEN" \
    'http://localhost:30007/api/v1/dashboard/followups?bucket=today'
  # → scope=org, counts populated, items[] length ≤ page_size
  ```
- Curl smoke as Employee returns `scope=personal` and only their own
  rows (verify by checking `assigned_to.id` on every item).
- `bucket=overdue` returns tasks with `due_at < now()` AND `status !=
  done`; sort is `due_at ASC` (oldest overdue first — most urgent).
- `bucket=today` sort is `due_at ASC, priority DESC` (earlier +
  higher-priority first).

---

## Self-check

Rule 2 — every query filters by `org_id` (via TenantScoped auto-filter
+ explicit passthrough for the join tables). Rule 6 — no new
permission key needed; reuses `users.read`. Rule 8 — under the split
threshold. Rule 10 — no TODOs, no hardcoded shortcuts.

Stop-report + wait for "proceed" before Step 3.
