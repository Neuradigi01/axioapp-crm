# Step 5 — Backend: in-app notifications on appointment events (`appointment.assigned`, `appointment.rescheduled`, `appointment.cancelled`)

**Status:** COMPLETED — `appointments/service.py` now imports `from src.app.core.notifications import service as notifications` and ships a `_notify_appointment_event()` helper that builds the title/body/payload per event type and forwards to `notifications.notify()` (which opens its own session and is non-raising — failures are logged, never roll back the appointment write). Wired into 5 call sites: `create_appointment` (suppressed when assignee == actor), `update_appointment` (cancel branch, suppressed when assignee == actor; reads org_id from `get_context()`), `reschedule_appointment` (always fires, including self-reschedule per the paper-trail rule), `reassign_appointment` (suppressed when assignee == actor), and `bulk_reassign_appointments` (collects moved appts and fans out one notification per row, suppressed when assignee == actor). Notification payload carries `appointment_id`, `contact_id`, `contact_name`, `scheduled_at` (ISO), `title`, `location`, `actor_user_id` — same shape across all three event types. Default `in_app=True` behavior is already correct (notifications service defaults missing-preference rows to enabled). 2 files modified, 1 new test file. API watch-reloaded cleanly after the changes.

**Goal:** Emit an in-app notification (persisted + WebSocket-pushed) to the assignee whenever they're assigned an appointment, when an appointment they own is rescheduled, or when an appointment they own is cancelled. The booker themselves does NOT get the notification (avoids self-spam). Pure backend wiring — frontend already shows whatever the notifications service emits.

**Depends on:** Step 4 (assignee picker — otherwise notifications would only ever fire for the booker, which is uninteresting).

## Why this step exists

The notifications module is fully built (`core/notifications/service.py`, WebSocket dispatch in `ws.py`, frontend popover + toast). But the appointments module never calls it. Even if Step 4 ships the Assignee picker, the assigned staff member has no idea they've been booked unless they happen to refresh the appointments page. That's broken multi-user workflow.

## Files changed

### New
- (none — all infrastructure exists)

### Modified
- `API/src/app/core/appointments/service.py` — emit notifications from `create_appointment`, `reassign_appointment`, `reschedule_appointment`, `update_appointment` (when status flips to `cancelled`), and `bulk_reassign_appointments` (one notif per moved appointment).
- `API/src/app/core/permissions/role_templates.py` — no key change, but document the new notification types in the seed comment block.
- `API/src/app/core/notifications/service.py` — verify `create()` signature already supports the call sites (it does); add a small helper `notify_appointment_event()` if any call-site is verbose.

### Tests
- `API/tests/core/appointments/test_notifications_emitted.py` (new) — assert one row per event in `notifications` table, correct user, correct type, correct payload shape.

## Notification types & payloads

Three new types (free-text per the existing schema — no migration needed):

| Type | Fired by | Title | Body |
|---|---|---|---|
| `appointment.assigned` | `create_appointment` (when assignee ≠ creator) and any reassign endpoint | "New appointment: {title}" | "Scheduled {scheduled_at_human} with {contact_name} at {location}" |
| `appointment.rescheduled` | `reschedule_appointment` | "Appointment rescheduled: {title}" | "Moved to {new_scheduled_at_human}" |
| `appointment.cancelled` | `update_appointment` when status flips to `cancelled` (only if assignee ≠ canceller) | "Appointment cancelled: {title}" | "{contact_name} on {scheduled_at_human} was cancelled" |

Payload shape (passed to `notifications.create(payload=...)`):

```python
{
    "appointment_id": str(apt.id),
    "contact_id": str(apt.contact_id) if apt.contact_id else None,
    "contact_name": contact.full_name if contact else None,
    "scheduled_at": apt.scheduled_at.isoformat(),
    "title": apt.title,
    "location": apt.location,
    "actor_user_id": str(actor.legacy_uuid),  # who triggered the event
}
```

The frontend popover already renders `{title}` + `{body}` + a click-through URL derived from `payload.appointment_id`.

## Self-notification suppression

The assigned user gets notified ONLY when someone else booked/reassigned/cancelled for them. Suppression logic:

```python
if assigned_to_user_id != actor.legacy_uuid:
    await notifications.create(...)
```

Applied in `create_appointment`, `reassign_appointment`, `update_appointment`. Reschedule still notifies the assignee even if they self-reschedule (different mental model — they want a paper trail).

## Default preferences

A `NotificationPreference` row is created lazily on first delivery per (user, type, channel). Defaults seeded in `notifications/service.py::_default_preference()`:

| Type | in_app | email | push |
|---|---|---|---|
| `appointment.assigned` | ✅ ON | ❌ OFF | ❌ OFF |
| `appointment.rescheduled` | ✅ ON | ❌ OFF | ❌ OFF |
| `appointment.cancelled` | ✅ ON | ❌ OFF | ❌ OFF |

Email defaults to OFF so existing tenants don't suddenly start receiving emails. Step 6 surfaces the toggle in Settings so users can opt in.

## Tests `test_notifications_emitted.py`

1. **Create assigned to someone else:** Owner books an appointment for Priya → one notification row, `user_id=priya`, `type=appointment.assigned`, payload carries appointment id + contact + scheduled_at.
2. **Create assigned to self:** Owner books for themselves → zero notification rows.
3. **Reassign:** appointment moves from Priya to Rahul → one notification for Rahul; payload carries appointment id; no notification for Priya (per existing `walk_ins.converted` precedent — losing assignment doesn't notify).
4. **Bulk reassign:** 5 appointments moved from Priya to Rahul → 5 notifications for Rahul.
5. **Reschedule:** Priya's appointment moved by Owner from 10am to 2pm → one notification, `type=appointment.rescheduled`, payload carries new `scheduled_at`.
6. **Cancel by booker for someone else:** Owner cancels Priya's appointment → Priya gets `appointment.cancelled`.
7. **Cancel by self:** Priya cancels her own appointment → no notification.
8. **Preference respected:** Priya turns OFF `in_app` for `appointment.assigned` → next booking for her does NOT write a `notifications` row.

## Acceptance

- New appointment for someone else → recipient sees a bell-badge increment in real-time + persistent inbox entry.
- Self-bookings produce no notification.
- Reschedule + cancellation by others produce the right notifications.
- Bulk reassign produces one notification per moved appointment.
- All 8 tests pass.

## Self-check vs the 10 rules

- ✅ Rule 1, 5 — `appointments/` only calls `notifications.create()` (a `core/core` cross-call, which is allowed).
- ✅ Rule 6 — no new permission keys; uses existing `notifications` module.
- ✅ Rule 8 — 3 files modified + 1 new test; under limit.
- ✅ Rule 10 — `appointment.assigned`/`rescheduled`/`cancelled` ship complete.

## Stop-and-report template

> ✅ Step 5 complete.
> **Files changed:** 4 (3 modified, 1 new test).
> **What you can verify:**
> 1. Book an appointment for another user → they see a bell-badge instantly.
> 2. Self-booking → no notification (no self-spam).
> 3. Bulk reassign → one notification per moved row.
> 4. Pref toggle for `appointment.assigned` actually mutes new rows.
> **Tests added:** `test_notifications_emitted.py` (8 cases).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 6.
