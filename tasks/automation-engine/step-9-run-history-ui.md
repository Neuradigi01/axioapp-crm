# Step 9 — Run history UI + per-contact timeline + manual "Run now"

**Goal:** Per-trigger run-history page (status, payload, error, retry); per-contact automations timeline on the contact detail page (what was sent, when, did it deliver/open/click); manual "Run now" button for ad-hoc fires.
**Status:** Pending
**Depends on:** Steps 4 + 8 (dispatcher + editor live), `core/contacts/` detail page (existing).

---

## Scope

In-scope:
- `APP/.../core/automations/runs/run-history.page.{ts,html}` at `/user/automations/{id}/runs`:
  - Table: scheduled_at, contact name (clickable to contact detail), status badge, channel_message_id, error (if any), retry button (for failed only), expand-row to show full event_payload JSON.
  - Filters: status, since (date).
  - Pagination: 50 per page.
- `APP/.../core/automations/runs/retry.modal.{ts,html}`:
  - Confirms retry; calls `POST /api/v1/automations/runs/{id}/retry`.
- `API/src/app/core/automation/router.py`:
  - `POST /api/v1/automations/runs/{id}/retry` — re-queues a failed run via the Celery task. Gated on `automations.write`.
  - `POST /api/v1/automations/triggers/{id}/run-now {payload}` — manual fire that bypasses event publish; useful for testing and one-off sends. Gated on `automations.write`.
- Per-contact timeline:
  - `GET /api/v1/contacts/{id}/automation-runs` — lists every run row where `contact_id = {id}`. Gated on `contacts.read`.
  - `APP/.../core/contacts/contact-detail/automations-tab.component.{ts,html}`:
    - New tab on the contact detail page (sits alongside Activities, Conversations, Tasks, etc.).
    - Timeline: ordered by `scheduled_at` desc — trigger name, channel, status badge, link to the message (deep-link into Conversations or email-account inbox), open/click metrics (Step 14 fills these — for now, status alone).
- Jest smoke for run history table + retry flow.

Out of scope:
- Open/click tracking pixels — Step 14 wires bounce + open + click webhooks.
- Bulk retry of multiple failed runs (defer).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/automations/runs/run-history.page.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/runs/run-history.page.html` | **NEW** |
| `APP/src/app/features/user/core/automations/runs/retry.modal.ts` | **NEW** |
| `APP/src/app/features/user/core/automations/runs/retry.modal.html` | **NEW** |
| `APP/src/app/features/user/user.routes.ts` | edit — add runs route |
| `API/src/app/core/automation/router.py` | edit — retry + run-now + per-contact-runs endpoints |
| `APP/src/app/features/user/core/contacts/contact-detail/automations-tab.component.ts` | **NEW** |
| `APP/src/app/features/user/core/contacts/contact-detail/automations-tab.component.html` | **NEW** |
| `APP/src/app/features/user/core/contacts/contact-detail/contact-detail.page.html` | edit — add tab entry |
| `API/tests/automation/test_retry_and_run_now.py` | **NEW** |

**~10 files. ~550 lines.**

## Plan

1. Backend endpoints: retry (re-queues via Celery `apply_async`) + run-now (writes a synthetic event_id of `f"manual:{trigger_id}:{uuid}"` so it doesn't dedupe with real events) + per-contact-runs list.
2. Run history page: standard list with expand-row and inline retry.
3. Per-contact timeline tab.
4. Tests: retry succeeds + idempotent, run-now writes a new run row each time, per-contact list filters by contact_id.

## DB changes / migrations

None.

## Tests

5 pytest + 2 Jest:
- `test_retry_failed_run_succeeds`
- `test_retry_succeeded_run_returns_409`
- `test_run_now_creates_fresh_run_row`
- `test_per_contact_runs_filtered_correctly`
- `test_per_contact_runs_rls_isolated`
- Jest: run history empty state + filter wiring.
- Jest: retry modal calls endpoint + refreshes.

## Smoke

```
1. /user/automations/{id}/runs → table of past runs (seeded triggers should already have a few from Steps 5/6 smokes).
2. Click a failed run → expand row → see payload + error.
3. Click Retry → confirm → status flips to queued → after Celery cycle, status updates.
4. /user/automations/{id} editor → click "Run now" with a sample payload → new run row appears.
5. Open a contact detail page → Automations tab → all runs that targeted this contact listed.
```

## Risks

- "Run now" can be used to spam — gate on `automations.write` (Owner/Admin) and add a simple per-trigger rate cap (10 manual fires per hour) in the router.
- Retry on a run referencing an archived template — the Celery task already handles this with `status='skipped'` + error message; no special UI handling needed beyond surfacing the error.

## Self-check (10 rules)

`core/automation/` + `features/user/core/contacts/contact-detail/`. ✓ org_id scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions gate retry + run-now. ✓ pack.yaml untouched. ✓ 10 files / ~550 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 9 — Run history UI + per-contact timeline + manual Run now
Files: 10
Verify: per-trigger run history navigable + retry works + per-contact tab shows automation runs + Run now writes a fresh row.
Tests: 5 pytest + 2 Jest cases.
Awaiting "proceed".
```
