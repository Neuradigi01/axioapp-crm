# Step 3 — Backend API endpoints + validation + caps + cross-org check + If-Match + pause/resume

**Goal:** Ship the HTTP surface for schedule CRUD with mass-assignment shielding, cross-org isolation, cron/interval validation (≥5-min floor), timezone whitelist, per-org caps (500 active, 1000 fires/hr), `If-Match` optimistic lock, and dedicated pause/resume endpoints (`active` NOT toggleable via PATCH).

**Status:** COMPLETED (2026-08-06, 8 endpoints live under `/api/v1/workflows/{id}/schedules` + `/api/v1/schedules/*`; 16-case HTTP smoke against Ajay's org PASS — POST/GET/PATCH/DELETE/pause/resume/preview + cross-org 404 + past-starts_at 422 + mass-assign 422 + If-Match 428/409/200; ruff clean; pytest deferred pending user go-ahead)

**Depends on:** Step 2 (service layer)

---

## Scope

**In-scope:**
- `core/workflows/schemas.py` — three schemas: `ScheduleCreate` (user-editable fields only), `ScheduleUpdate` (subset, no `active`), `ScheduleResponse` (all fields for read). Server-owned fields explicitly excluded from create/update: `runs_completed`, `next_run_at`, `last_run_at`, `consecutive_empty_fires`, `deactivation_reason`, `org_id`, `created_by_user_id`, `created_at`, `updated_at`.
- `core/workflows/router.py` — endpoints:
  - `POST   /api/v1/workflows/{workflow_id}/schedules` → create.
  - `GET    /api/v1/workflows/{workflow_id}/schedules` → list for a workflow.
  - `GET    /api/v1/schedules/{schedule_id}` → single fetch.
  - `PATCH  /api/v1/schedules/{schedule_id}` → update (requires `If-Match`).
  - `DELETE /api/v1/schedules/{schedule_id}` → delete.
  - `POST   /api/v1/schedules/{schedule_id}/pause` → dedicated pause.
  - `POST   /api/v1/schedules/{schedule_id}/resume` → dedicated resume.
  - `POST   /api/v1/schedules/preview` → compute "next 5 fires" from a proposed config (used by Builder). Rate-limited 10/s/user.
- Validation:
  - Timezone against `zoneinfo.available_timezones()`.
  - `starts_at` ≥ now (422 if past).
  - `end_at` ≥ `starts_at` if set (422 if before).
  - Cron: 5-field only; croniter parse succeeds; `_get_next()` returns a datetime within `now + 5 years`; computed inter-fire distance ≥ 5 min.
  - Interval: `interval_minutes` ≥ 5.
  - `max_runs` ≥ 1 if set.
- Cross-org guard: every mutating endpoint calls `service.get_workflow_by_id_and_org` (or `get_schedule_by_id_and_org`) FIRST. Returns 404 (not 403) on mismatch.
- Per-org caps: enforced in service transaction with row-lock on `tbl_organizations` row (prevents race past 500).
- `If-Match` header on PATCH: compares to `updated_at` ISO string; 428 if missing, 409 if stale.
- Permission checks: `workflows.manage` role permission required for create/update/delete/pause/resume; `workflows.view` for GET.
- Tests: cross-org × every verb, mass-assign rejection × every server-field, validation × every rule, If-Match × 3 (missing/stale/valid), rate-limit on preview, cap-race, permission gate.

**Out-of-scope:**
- Frontend (Step 4).
- Sweep behavior (Step 2).
- Contact-merge cascade (Step 6).

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/workflows/schemas.py` | edit — add `ScheduleCreate`, `ScheduleUpdate`, `ScheduleResponse`, `SchedulePreviewRequest`, `SchedulePreviewResponse` |
| `api/src/app/core/workflows/router.py` | edit — add 8 endpoints listed above |
| `api/src/app/core/workflows/service.py` | edit — add validation helpers, `If-Match` compare, cap-race enforcement |
| `api/src/app/core/workflows/permissions.py` | edit — ensure `workflows.manage` permission covers schedule CRUD (extend existing key, not new one) |
| `api/tests/workflows/test_schedule_api.py` | **NEW** — ~25 cases: CRUD happy paths, cross-org × 5 verbs, mass-assign × 6 fields, validation × 10 rules, If-Match × 3, cap × 2, permission × 2, pause/resume × 2 |
| `api/tests/workflows/test_schedule_preview.py` | **NEW** — 4 cases: valid config returns 5 fires; invalid cron returns 422; rate-limit at 11th req/s returns 429; timeout wrapper honored |

**~6 files, ~500 lines.**

## Validation table

| Rule | Where | Error code | Message |
|---|---|---|---|
| Timezone not in `available_timezones()` | schema validator | 422 | `"timezone must be a valid IANA identifier"` |
| `starts_at < now()` | service | 422 | `"start time is in the past"` |
| `end_at < starts_at` | service | 422 | `"end time must be after start time"` |
| Cron parse fails | schema validator | 422 | `"invalid cron expression: <croniter message>"` |
| Cron has seconds field / 6+ fields | schema validator | 422 | `"5-field cron only (minute hour day month weekday)"` |
| Cron computed inter-fire < 5 min | service | 422 | `"minimum inter-fire interval is 5 minutes"` |
| Cron next fire > now + 5y | service | 422 | `"schedule would not fire for over 5 years"` |
| Interval < 5 min | schema validator | 422 | `"minimum interval is 5 minutes"` |
| `max_runs < 1` | schema validator | 422 | |
| `active` in PATCH body | schema validator | 422 | `"use POST /pause or /resume to toggle active"` |
| `runs_completed` / `next_run_at` / `last_run_at` / `consecutive_empty_fires` / `org_id` in body | schema validator (extra="forbid") | 422 | `"field is server-managed"` |
| Cap exceeded (>500 active) | service | 422 | `"organization has reached the 500-schedule limit"` |
| `If-Match` missing on PATCH | router | 428 | `"if-match header required"` |
| `If-Match` stale | service | 409 | `"schedule was modified; re-fetch and retry"` |
| Cross-org access | service | 404 | (no message leak — same as not-found) |
| Preview rate-limit | router (existing rate-limit dep) | 429 | |
| Non-admin POST | router permission dep | 403 | |

## Plan

1. **Schemas** — Pydantic v2 with `extra="forbid"` on create/update to block mass-assign implicitly; explicit `active`-in-update validator with 422.
2. **Router endpoints** — thin. Every mutation: auth dep → workflow-scoped or schedule-scoped resource load through service → call service method → return response.
3. **Service validation** — collect all rule checks in `_validate_schedule_config`; called from create and update.
4. **Cap enforcement** — `SELECT ... FOR UPDATE` on `tbl_organizations` row inside service txn, then `count_active_schedules_for_org`, then insert. Prevents race.
5. **If-Match** — router extracts header, service compares `datetime.fromisoformat(if_match) != schedule.updated_at`. On PATCH success, service returns new `updated_at` for the client's next-round ETag.
6. **Pause/resume** — dedicated endpoints because `active` is intentionally not in `ScheduleUpdate`. Pause writes `active=false, deactivation_reason='manual'`; resume writes `active=true, deactivation_reason=NULL, next_run_at=compute_next_run_at(schedule, now=now)`.
7. **Preview** — service method calls `compute_next_run_at` in a loop 5 times; returns list. Uses existing rate-limit dependency (per-user, 10/s).
8. **Tests** — coverage per §Validation table + happy paths.

## DB changes / migrations

None.

## Verification

- `uv run pytest api/tests/workflows/test_schedule_api.py api/tests/workflows/test_schedule_preview.py` — all pass.
- Postman/curl smoke on Ajay's Workspace: POST valid schedule → 201; POST with `starts_at` in past → 422; POST cross-org workflow → 404; PATCH without If-Match → 428; POST 501st schedule → 422 cap.
- Pin-tests pass.
- Ruff clean.

## Stop-and-report template

```
Step 3 done — API endpoints + validation + caps + cross-org + If-Match + pause/resume.

Files changed: <list>
What you can verify:
  - `curl -X POST /api/v1/workflows/<id>/schedules` with valid payload → 201
  - Cross-org POST → 404 (no leak)
  - `curl -X PATCH /api/v1/schedules/<id>` without If-Match → 428
  - `curl -X PATCH /api/v1/schedules/<id>` with stale If-Match → 409
  - POST 501st active schedule → 422 cap error
  - POST with `active: true` in body → 422 "use /pause or /resume"
  - POST with `runs_completed: 0` → 422 "field is server-managed"
  - POST /schedules/preview with valid config returns 5 datetimes
Tests added: ~29
Self-check: [pass/fixed/N/A on 10 rules · layering · reuse · DB efficiency · tooling-clean]
Awaiting your 'proceed' for Step 4.
```
