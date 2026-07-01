# Step 6 — Tests + operator docs

**Goal:** Pin the OAuth / sync surface with pytest cases + document the
one-time Google Cloud setup + operator-facing FAQ.
**Status:** COMPLETED
**Depends on:** Steps 1-5 shipped.

---

## Scope

### Pytest cases (12)

`API/tests/integrations/google_calendar/`:

- OAuth state HMAC — tampered state param 400s
- OAuth state HMAC — user_id in state doesn't match JWT 400s
- Token refresh — access token expired → refresh call fires
- Token refresh — `invalid_grant` → row marked `revoked`
- Sync service — fresh appointment → event created, event_id +
  etag stored
- Sync service — updated appointment → event patched, etag refreshed
- Sync service — deleted appointment → event deleted, event_id nulled
- Sync service — reassignment → old event deleted + new event created
- Sync service — assignee without connection → no-op, no error
- Sync service — Google 404 on PATCH → treats event as gone, creates
  new one
- Sync service — Google 412 on PATCH → marks `last_error`, doesn't
  overwrite
- Celery task retry — rate-limit exception → task retried with backoff

### Jest cases (2)

- Integrations page: Google Calendar card renders correct state (connected
  / disconnected / error) based on API response
- Appointment detail: sync chip renders correct state per assignee's
  connection state

### Operator docs

- `manual-google-calendar-setup.md` (this folder) — the one-time
  Google Cloud checklist the ops team runs before any employee can
  connect. Screenshot-guided.
- `production-test-runbook.md` (this folder) — end-to-end smoke on
  Ajay's Workspace using a real Google account.
- Add a note in `README.md` at the repo root under
  "Google Calendar sync" that the manual-setup doc exists.

### Files to touch

| File | Action |
|---|---|
| `API/tests/integrations/google_calendar/test_oauth.py` | **NEW** |
| `API/tests/integrations/google_calendar/test_sync_service.py` | **NEW** |
| `APP/src/app/features/user/core/settings/integrations/google-calendar-card.component.spec.ts` | **NEW** (optional — Jest cases are deferred if the Angular test harness isn't set up) |
| `tasks/google-calendar-sync/production-test-runbook.md` | **NEW** |

`manual-google-calendar-setup.md` — already shipped in Step 2's
companion doc for the ops team.

**~3-4 files, ~500 lines.**

## Verify

- `docker exec crm-api-1 python -m pytest tests/integrations/google_calendar -v`
  passes all 12
- Runbook smoke on Ajay's Workspace: connect calendar → create
  appointment → event appears → edit → event updates → delete → event
  disappears → reassign → old event deleted + new event on new
  assignee's calendar → revoke access at accounts.google.com → next
  sync marks row `revoked` + card flips to reconnect state

## Self-check

Test isolation — each test opens a fresh session, no cross-test bleed.
Docs cover Google Cloud + operator + end user paths. Stop-report.
