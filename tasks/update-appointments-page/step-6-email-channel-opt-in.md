# Step 6 — Email channel for appointment notifications (opt-in) + Settings UI to toggle

**Status:** COMPLETED — `core/notifications/email_renderer.py` (new) renders `(subject, html, text)` for `appointment.assigned` / `rescheduled` / `cancelled`. `core/notifications/service.py` extended: `notify()` now resolves recipient email via `tbl_user_info` (joined through `tbl_user_login.legacy_uuid`), consults a new `_email_opted_in()` helper that defaults to OFF (only an explicit `enabled=true` row dispatches — keeps tenants from being suddenly emailed for new types), and best-effort sends via the existing `get_email_backend()`. SMTP failures are caught, logged at WARNING, and audited as `notification.email.failed` without rolling back the in-app row. Settings UI rebuilt: `notifications-tab.component.ts` now ships a `TYPE_LABELS` dictionary that pre-seeds the three appointment rows even when the user has no preferences saved (so the user can opt into email without having to receive a notification first); html drops the push column (deferred to a future mobile-focused track) and shows the human label + raw type. 5 files (1 new renderer + 1 new test + 3 modified). API watch-reloaded cleanly (HTTP 200 on `/api/v1/health`).

**Goal:** Wire the existing SMTP backend to the notifications service so users who opt in to **email** for a given appointment notification type actually receive an email. Add the Settings UI rows that let them toggle per-type (`appointment.assigned`, `appointment.rescheduled`, `appointment.cancelled`) per channel (in-app / email). Push channel stays defined but unimplemented — separate future track when there's mobile demand.

**Depends on:** Step 5 (notifications must be firing for the appointment events; this step adds the email channel on top).

## Why this step exists

The user's brief was explicit: *"user can choose if he want email or not for the appointments."* Step 5 ships in-app notifications (always on by default, opt-out per type). This step ships **email opt-in** so a staff member can elect to also get an email for every appointment they're assigned — handy for staff who don't keep the dashboard open, or for after-hours bookings.

## Files changed

### New
- `API/src/app/core/notifications/email_renderer.py` — small renderer building `(subject, html, text)` from `(notification_type, payload)`. Three appointment templates (`assigned`, `rescheduled`, `cancelled`).

### Modified
- `API/src/app/core/notifications/service.py` — in `create()`, after persisting + WebSocket dispatch, if user's pref for `(type, email)` is `True`, render via `email_renderer` and send via the existing `shared.email.smtp_backend.send_email()`. Failure to send must NOT roll back the persisted notification (in-app delivery is the source of truth).
- `APP/src/app/features/user/core/settings/tabs/notification-preferences-tab.component.ts` — surface the three appointment rows in the preferences table.
- `APP/src/app/features/user/core/settings/tabs/notification-preferences-tab.component.html` — render the toggle rows.

### Tests
- `API/tests/core/notifications/test_email_channel_appointment.py` (new) — assert email send is invoked (or skipped) per preference, payload renders into the template, and SMTP failure does NOT roll back the notification row.

## `email_renderer.py`

One-screen module. Three template functions, one dispatch:

```python
"""Render appointment-type notifications into SMTP payloads.

Plain-text bodies (HTML mirrors in `_html_for`) — minimum viable so we
don't ship a templating dependency. Add Jinja2 only when we have
more than ~5 templates total.
"""
from src.app.core.notifications.models import NotificationChannel
from src.app.core.notifications.schemas import NotificationOut


def render_email(notif: NotificationOut) -> tuple[str, str, str] | None:
    """Return (subject, html_body, text_body) or None if the type is
    not email-renderable. Unknown types -> None (caller skips email).
    """
    if notif.type == "appointment.assigned":
        return _render_appointment_assigned(notif)
    if notif.type == "appointment.rescheduled":
        return _render_appointment_rescheduled(notif)
    if notif.type == "appointment.cancelled":
        return _render_appointment_cancelled(notif)
    return None


def _render_appointment_assigned(notif: NotificationOut) -> tuple[str, str, str]:
    p = notif.payload
    subject = f"New appointment: {p.get('title', 'Untitled')}"
    text = (
        f"Hi,\n\n"
        f"You've been assigned a new appointment:\n\n"
        f"  Title:    {p.get('title')}\n"
        f"  Contact:  {p.get('contact_name')}\n"
        f"  When:     {p.get('scheduled_at')}\n"
        f"  Location: {p.get('location') or '—'}\n\n"
        f"Open the dashboard to see details.\n"
    )
    html = f"<p>Hi,</p><p>You've been assigned a new appointment:</p>" \
           f"<ul>" \
           f"<li><b>Title:</b> {p.get('title')}</li>" \
           f"<li><b>Contact:</b> {p.get('contact_name')}</li>" \
           f"<li><b>When:</b> {p.get('scheduled_at')}</li>" \
           f"<li><b>Location:</b> {p.get('location') or '—'}</li>" \
           f"</ul>"
    return subject, html, text


# ... rescheduled + cancelled follow the same shape
```

Plain text + simple HTML so we don't have to introduce Jinja2 templates today. When we hit ~5 templates, refactor.

## `service.py` change

In `notifications.service.create()`, after the existing persist + WS push, add the email dispatch:

```python
# Existing persist + WebSocket push code stays as-is...

# Email channel (best-effort; failure does NOT roll back the notif).
if pref.email:
    try:
        rendered = render_email(notification_out)
        if rendered is not None:
            subject, html_body, text_body = rendered
            await smtp.send_email(
                to=user_info.email,
                subject=subject,
                html=html_body,
                text=text_body,
            )
            await audit.log(
                "notification.email.sent",
                org_id=notification_out.org_id,
                user_id=user_info.member_id,
                after={"notification_id": str(notification_out.id),
                       "type": notification_out.type},
            )
    except Exception:
        logger.warning(
            "email delivery failed for notification %s (type=%s, user=%s)",
            notification_out.id, notification_out.type, user_info.member_id,
            exc_info=True,
        )
        await audit.log(
            "notification.email.failed",
            org_id=notification_out.org_id,
            user_id=user_info.member_id,
            after={"notification_id": str(notification_out.id),
                   "type": notification_out.type},
        )
```

In-app delivery is the source of truth; email is opportunistic. If SMTP is down the user still sees the bell + popover.

## Settings UI

Existing `notification-preferences-tab.component.html` already renders a table of `{type, channel, enabled}` rows from `GET /api/v1/notifications/preferences`. After Step 5 lands its defaults, the three appointment rows appear automatically:

| Notification | In-app | Email |
|---|:---:|:---:|
| New appointment assigned to me | toggle (default ON) | toggle (default OFF) |
| Appointment I own was rescheduled | toggle (default ON) | toggle (default OFF) |
| Appointment I own was cancelled | toggle (default ON) | toggle (default OFF) |

The TS just needs to add display strings for the three types in the existing `TYPE_LABELS` dictionary; the HTML iterates whatever rows the API returns.

## Push channel

Not implemented in this step. The channel enum and per-user preference exist, but the actual FCM/web-push sender is deferred to a future `tasks/notifications-push-channel/` track (needs `firebase-admin` SDK, service worker registration, browser permission prompt — non-trivial). Today the push toggle is hidden from the Settings UI (don't surface a control we can't honour); when push lands, the row gets uncommented.

## Tests `test_email_channel_appointment.py`

1. **Email preference ON → email sent:** Mock `smtp.send_email`. User opts in `(appointment.assigned, email)`. Owner books for them. Assert `send_email` called once with subject containing the title.
2. **Email preference OFF → email NOT sent:** Default user. Owner books for them. Assert `send_email` NOT called.
3. **Email send failure → notification still persisted:** Mock `smtp.send_email` to raise. Owner books. Notification row exists, audit event `notification.email.failed` written, parent transaction not rolled back.
4. **Rescheduled email body carries new scheduled_at:** Mock `send_email`, capture body, assert ISO timestamp appears.
5. **Cancelled email body carries contact name + original scheduled_at:** Same pattern.
6. **Unknown notification type → no email attempted:** Mock `render_email` returns `None` for an unknown type; `send_email` not called.

## Acceptance

- Toggling email ON in Settings → next booking for the user produces an email.
- Email content matches the appointment payload (title, contact, time, location).
- Email failures don't break the in-app notification.
- 6 tests pass.

## Self-check vs the 10 rules

- ✅ Rule 1 — `notifications/` calls `shared/email/` (allowed: `core/` → `shared/`).
- ✅ Rule 5, 7 — no module/sidebar registry changes.
- ✅ Rule 8 — 4 files modified + 1 new + 1 new test; 6 total, under limit.
- ✅ Rule 10 — email channel ships complete (with renderer + tests + Settings UI surface); push channel correctly deferred to a future track rather than half-shipped.

## Stop-and-report template

> ✅ Step 6 complete (track done).
> **Files changed:** 6.
> **What you can verify:**
> 1. Settings → Notifications shows appointment rows with in-app + email toggles.
> 2. Toggle email ON, book yourself an appointment from another logged-in window → email arrives in your inbox.
> 3. Stop SMTP (`docker-helper.cmd down` on the mail container) → bookings still notify in-app + log `notification.email.failed`.
> **Tests added:** `test_email_channel_appointment.py` (6 cases).
> **Self-check:** all 10 rules ✅.
> Track **update-appointments-page** complete.
