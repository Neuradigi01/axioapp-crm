"""Render notification payloads into SMTP-ready email parts.

`render_email(notif)` returns `(subject, html_body, text_body)` for the
appointment.* family. Unknown types return `None` so the caller skips
email entirely without raising.

Plain text + inline HTML — minimum viable. When we cross ~5 templates,
move to Jinja2 partials under `core/notifications/email_templates/`.
"""

from __future__ import annotations

from typing import Any

from src.app.core.notifications.schemas import NotificationOut


def render_email(notif: NotificationOut) -> tuple[str, str, str] | None:
    """Return `(subject, html, text)` or None for unsupported types.

    ``task.assigned`` and ``task.completed`` intentionally return None:
    email delivery for both events is owned by the seeded "Task
    Assigned" / "Task Completed" preset workflows (send.email nodes
    addressed to ``assignee.email``). Routing them through here as
    well would deliver two copies of the same email to the assignee.
    The in-app bell + WebSocket push still fire via
    ``notifications.notify`` — only the SMTP path is short-circuited
    for these types.
    """
    if notif.type == "appointment.assigned":
        return _render_appointment_assigned(notif)
    if notif.type == "appointment.rescheduled":
        return _render_appointment_rescheduled(notif)
    if notif.type == "appointment.cancelled":
        return _render_appointment_cancelled(notif)
    if notif.type == "appointment.completed":
        return _render_appointment_completed(notif)
    return None


def _p(notif: NotificationOut) -> dict[str, Any]:
    return notif.payload or {}


def _fmt(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def _render_appointment_assigned(notif: NotificationOut) -> tuple[str, str, str]:
    p = _p(notif)
    title = _fmt(p.get("title"), "Untitled")
    subject = f"New appointment: {title}"
    text = (
        "Hi,\n\n"
        "You've been assigned a new appointment:\n\n"
        f"  Title:    {title}\n"
        f"  Contact:  {_fmt(p.get('contact_name'))}\n"
        f"  When:     {_fmt(p.get('scheduled_at'))}\n"
        f"  Location: {_fmt(p.get('location'))}\n\n"
        "Open the dashboard to see details.\n"
    )
    html = (
        "<p>Hi,</p>"
        "<p>You've been assigned a new appointment:</p>"
        "<ul>"
        f"<li><b>Title:</b> {title}</li>"
        f"<li><b>Contact:</b> {_fmt(p.get('contact_name'))}</li>"
        f"<li><b>When:</b> {_fmt(p.get('scheduled_at'))}</li>"
        f"<li><b>Location:</b> {_fmt(p.get('location'))}</li>"
        "</ul>"
        "<p>Open the dashboard to see details.</p>"
    )
    return subject, html, text


def _render_appointment_rescheduled(notif: NotificationOut) -> tuple[str, str, str]:
    p = _p(notif)
    title = _fmt(p.get("title"), "Untitled")
    subject = f"Appointment rescheduled: {title}"
    text = (
        "Hi,\n\n"
        "An appointment you own has been rescheduled:\n\n"
        f"  Title:   {title}\n"
        f"  Contact: {_fmt(p.get('contact_name'))}\n"
        f"  Moved to: {_fmt(p.get('scheduled_at'))}\n\n"
        "Open the dashboard to see details.\n"
    )
    html = (
        "<p>Hi,</p>"
        "<p>An appointment you own has been rescheduled:</p>"
        "<ul>"
        f"<li><b>Title:</b> {title}</li>"
        f"<li><b>Contact:</b> {_fmt(p.get('contact_name'))}</li>"
        f"<li><b>Moved to:</b> {_fmt(p.get('scheduled_at'))}</li>"
        "</ul>"
        "<p>Open the dashboard to see details.</p>"
    )
    return subject, html, text


def _render_appointment_cancelled(notif: NotificationOut) -> tuple[str, str, str]:
    p = _p(notif)
    title = _fmt(p.get("title"), "Untitled")
    subject = f"Appointment cancelled: {title}"
    text = (
        "Hi,\n\n"
        "An appointment you own has been cancelled:\n\n"
        f"  Title:   {title}\n"
        f"  Contact: {_fmt(p.get('contact_name'))}\n"
        f"  When:    {_fmt(p.get('scheduled_at'))}\n\n"
        "No further action needed.\n"
    )
    html = (
        "<p>Hi,</p>"
        "<p>An appointment you own has been cancelled:</p>"
        "<ul>"
        f"<li><b>Title:</b> {title}</li>"
        f"<li><b>Contact:</b> {_fmt(p.get('contact_name'))}</li>"
        f"<li><b>When:</b> {_fmt(p.get('scheduled_at'))}</li>"
        "</ul>"
        "<p>No further action needed.</p>"
    )
    return subject, html, text


def _render_appointment_completed(notif: NotificationOut) -> tuple[str, str, str]:
    p = _p(notif)
    title = _fmt(p.get("title"), "Untitled")
    subject = f"Appointment completed: {title}"
    text = (
        "Hi,\n\n"
        "An appointment you own has been marked complete:\n\n"
        f"  Title:   {title}\n"
        f"  Contact: {_fmt(p.get('contact_name'))}\n"
        f"  When:    {_fmt(p.get('scheduled_at'))}\n\n"
        "No further action needed.\n"
    )
    html = (
        "<p>Hi,</p>"
        "<p>An appointment you own has been marked complete:</p>"
        "<ul>"
        f"<li><b>Title:</b> {title}</li>"
        f"<li><b>Contact:</b> {_fmt(p.get('contact_name'))}</li>"
        f"<li><b>When:</b> {_fmt(p.get('scheduled_at'))}</li>"
        "</ul>"
        "<p>No further action needed.</p>"
    )
    return subject, html, text


__all__ = ["render_email"]
