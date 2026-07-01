# Step 4 — Appointment hooks + Celery task

**Goal:** Every appointment CRUD (create, update, delete, reassign)
enqueues a Celery task that runs `sync_appointment` for the affected
assignee(s). Async so the CRM UX never waits on Google's API.
**Status:** COMPLETED
**Depends on:** Step 3 (sync service).

---

## Scope

### Celery task — `google_calendar/tasks.py`

```python
@shared_task(
    name="src.app.core.integrations.google_calendar.tasks.sync_appointment",
    bind=True,
    autoretry_for=(GoogleCalendarRateLimited,),
    retry_backoff=True,       # 30s, 60s, 120s, ...
    retry_backoff_max=600,    # cap 10 min
    max_retries=3,
)
def sync_appointment_task(
    self, *, appointment_id: str, user_id: str,
) -> dict:
    """Beat-triggered or hook-triggered sync. Idempotent — safe to
    re-run against the same appointment."""
    return asyncio.run(_sync_appointment_async(appointment_id, user_id))
```

Reassignment fires TWO tasks: one for the old assignee (delete their
event) + one for the new assignee (create in their calendar). The
service layer schedules both.

### Hooks in `core/appointments/service.py`

Wire calls into the post-commit path of the appointment CRUD service
functions:

- `create_appointment` → after commit, dispatch task with
  `(appointment.id, appointment.assigned_to_id)` if assignee set
- `update_appointment` → detect field changes:
  - Any of `title/description/start_at/end_at/location/attendees`
    changed → dispatch task for CURRENT assignee
  - `assigned_to_id` changed → dispatch TWO tasks: old + new
- `delete_appointment` → dispatch task with the appointment's LAST
  known `assigned_to_id` so the event gets removed from that person's
  calendar (task looks up appointment; not found → treats as delete)

Hooks are wrapped in try/except so a broken Celery / Redis never
prevents an appointment write from succeeding — sync is best-effort.
If dispatch fails, the operator's next appointment edit (or the
Step-4b beat sweep — see below) reconciles.

### Reconciliation beat sweep (Step 4b safety net)

Add to `celery_config.py`:

```python
"google-calendar-reconcile": {
    "task": "src.app.core.integrations.google_calendar.tasks.reconcile_pending",
    "schedule": crontab(minute="*/30"),
}
```

`reconcile_pending` walks appointments whose `start_at > now()` and
whose stored `google_calendar_event_id` doesn't match the assignee's
expected calendar (or whose assignee has connected Calendar but their
appointment has no event_id yet). Fires `sync_appointment_task` per
row. Catches drift from missed hooks.

### Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/google_calendar/tasks.py` | **NEW** |
| `API/src/app/core/appointments/service.py` | edit — dispatch hooks in create / update / delete |
| `API/src/celery/celery_config.py` | edit — beat entry for reconcile_pending |

**~3 files, ~200 lines.**

## Verify

1. Create an appointment for Ajay → check Flower — task appears +
   succeeds → open Google Calendar → event visible within 5s
2. Edit the appointment's title → Flower shows another task fire →
   calendar event title updates
3. Reassign to a different employee (who has also connected Calendar)
   → TWO tasks fire; old event disappears, new event appears
4. Reassign to an employee who hasn't connected Calendar → one task
   fires (delete on old assignee), second task is a no-op
5. Delete the appointment → task fires → calendar event disappears
6. Stop Celery, create an appointment (dispatch fails), start Celery,
   wait 30 min for the beat sweep → event appears (reconcile catches
   the drift)

## Self-check

Hooks live in `service.py`. Task registration name pinned. Retries
bounded. Reassignment schedules both delete + create. Reconciliation
beat covers hook drift. Stop-report.
