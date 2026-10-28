"""Email template renderers for the six billing notifications.

Each template is a pure Python function that takes a `context` dict
and returns `(subject, html_body, text_body)`. We do not use Jinja2
because the project does not currently ship it; the inline pattern
mirrors `core/notifications/email_renderer.py` which renders the
appointment.* family the same way.

Templates are deliberately simple HTML (inline styles, table-free
where possible) because billing emails MUST render in Gmail web,
Apple Mail, and Outlook — adventurous CSS would silently break in
one of them. The plain-text variants are non-optional so SPAM
classifiers see balanced content.

When `plans.yaml` adds new emails, both the function below and the
`BillingEmailKey` literal in `notifications.py` must extend.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Branding constant. Per the `feedback_branding_crm_not_furnicrm`
# memory the customer-facing copy reads "CRM" — internal module names
# and API contracts keep the existing furniturecrm namespace.
_PRODUCT_NAME = "CRM"

# Single source of truth for support contact in customer copy. Kept
# here (rather than on the env / config) because emails are reviewed
# by marketing — having the address in one obvious place reduces the
# blast radius of a copy change.
_SUPPORT_EMAIL = "support@yourcrm.com"


def _greeting(context: dict[str, Any]) -> str:
    name = context.get("owner_first_name")
    if isinstance(name, str) and name.strip():
        return f"Hi {name.strip()},"
    return "Hi there,"


def _org_line(context: dict[str, Any]) -> str:
    org = context.get("org_name")
    if isinstance(org, str) and org.strip():
        return f"  ({org.strip()})"
    return ""


def _shell(title: str, body_html: str) -> str:
    """Wrap a per-template HTML fragment in the shared layout.

    Inline styles only — see the module-level docstring for the
    rationale. Width=560 is the historical safe ceiling for Gmail's
    mobile view.
    """
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="width:100%;background:#f5f5f5;padding:24px 0;">'
        '<tr><td align="center">'
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="width:560px;max-width:560px;background:#ffffff;'
        "border:1px solid #e5e7eb;border-radius:12px;"
        "font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,"
        'Helvetica,Arial,sans-serif;color:#111827;">'
        '<tr><td style="padding:24px 28px 8px;">'
        f'<h1 style="margin:0 0 4px;font-size:20px;line-height:28px;'
        'font-weight:600;">'
        f"{title}"
        "</h1>"
        "</td></tr>"
        f'<tr><td style="padding:8px 28px 24px;font-size:14px;'
        f'line-height:22px;color:#374151;">{body_html}</td></tr>'
        '<tr><td style="padding:16px 28px 24px;font-size:12px;'
        'line-height:18px;color:#9ca3af;border-top:1px solid #f3f4f6;">'
        f'Questions? Reach us at <a href="mailto:{_SUPPORT_EMAIL}" '
        f'style="color:#3b82f6;text-decoration:none;">{_SUPPORT_EMAIL}</a>.'
        "</td></tr>"
        "</table></td></tr></table>"
    )


def _button(label: str, url: str) -> str:
    return (
        f'<p style="margin:20px 0;"><a href="{url}" '
        'style="display:inline-block;background:#2563eb;color:#ffffff;'
        "padding:10px 18px;border-radius:8px;text-decoration:none;"
        f'font-weight:600;font-size:14px;">{label}</a></p>'
    )


# ---------------------------------------------------------------------------
# Per-template renderers
# ---------------------------------------------------------------------------


def _render_trial_ending_soon(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    days = context.get("days_remaining", 3)
    upgrade_url = context.get("upgrade_url", "")
    org_line = _org_line(context)
    subject = f"Your {_PRODUCT_NAME} trial ends in {days} days"
    body_html = _shell(
        f"Your trial ends in {days} days",
        f"<p>{_greeting(context)}</p>"
        f"<p>Your free 14-day {_PRODUCT_NAME} trial{org_line} ends in "
        f"<strong>{days} days</strong>. Upgrade now to keep your team's "
        "data, automations, and integrations active.</p>"
        + _button(f"Upgrade {_PRODUCT_NAME}", upgrade_url),
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"Your free 14-day {_PRODUCT_NAME} trial{org_line} ends in {days} days.\n"
        "Upgrade to keep your team's data, automations, and integrations active.\n\n"
        f"Upgrade: {upgrade_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_trial_expired(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    upgrade_url = context.get("upgrade_url", "")
    subject = f"Your {_PRODUCT_NAME} trial has ended"
    body_html = _shell(
        "Your trial has ended",
        f"<p>{_greeting(context)}</p>"
        f"<p>Your {_PRODUCT_NAME} trial period has ended. Your data is "
        "safe and your team can continue to <em>view</em> it, but new "
        "records and edits are paused until you upgrade.</p>"
        + _button(f"Upgrade {_PRODUCT_NAME}", upgrade_url),
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"Your {_PRODUCT_NAME} trial has ended. Your team can still view "
        "data, but new records and edits are paused until you upgrade.\n\n"
        f"Upgrade: {upgrade_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_payment_succeeded(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    amount = context.get("amount_paid_usd", 0)
    invoice_url = context.get("invoice_pdf_url", "")
    billing_url = context.get("billing_url", "")
    subject = "Payment received — thanks!"
    invoice_block = _button("Download invoice", invoice_url) if invoice_url else ""
    body_html = _shell(
        "Payment received",
        f"<p>{_greeting(context)}</p>"
        f"<p>Thanks — we received your payment of "
        f"<strong>${amount}</strong>. Your {_PRODUCT_NAME} subscription "
        "is active and your invoice is attached below.</p>"
        + invoice_block
        + f'<p style="font-size:13px;color:#6b7280;">'
        f"You can review billing history any time at "
        f'<a href="{billing_url}" style="color:#3b82f6;'
        'text-decoration:none;">your billing settings</a>.'
        "</p>",
    )
    invoice_text_line = f"Download invoice: {invoice_url}\n" if invoice_url else ""
    body_text = (
        f"{_greeting(context)}\n\n"
        f"We received your payment of ${amount}. Your {_PRODUCT_NAME} "
        "subscription is active.\n\n"
        f"{invoice_text_line}"
        f"Billing settings: {billing_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_payment_failed(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    billing_url = context.get("billing_url", "")
    subject = "We couldn't charge your card"
    body_html = _shell(
        "We couldn't charge your card",
        f"<p>{_greeting(context)}</p>"
        f"<p>Your most recent {_PRODUCT_NAME} payment didn't go through. "
        "Your subscription is temporarily in <strong>past-due</strong> "
        "mode — your data is safe, but new writes will be paused until "
        "we receive a valid payment.</p>"
        f"<p>Please update your payment method to resume normal access.</p>"
        + _button("Update payment method", billing_url),
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"Your most recent {_PRODUCT_NAME} payment didn't go through. "
        "Your subscription is in past-due mode and new writes are "
        "paused until we receive a valid payment.\n\n"
        f"Update payment method: {billing_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_seats_added(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    added = context.get("seats_added", 0)
    total = context.get("seats_total", 0)
    billing_url = context.get("billing_url", "")
    word = "seat" if added == 1 else "seats"
    subject = f"{added} {word} added to your plan"
    body_html = _shell(
        f"{added} {word} added",
        f"<p>{_greeting(context)}</p>"
        f"<p>You now have <strong>{total} seats</strong> on your "
        f"{_PRODUCT_NAME} plan ({added} added). New teammates can be "
        "invited from your Team settings.</p>" + _button("Manage seats", billing_url),
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"You now have {total} seats on your {_PRODUCT_NAME} plan "
        f"({added} added).\n\n"
        f"Manage seats: {billing_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_plan_changed(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    plan_name = context.get("plan_name", "your new plan")
    billing_url = context.get("billing_url", "")
    subject = f"Welcome to {_PRODUCT_NAME} {plan_name}"
    body_html = _shell(
        f"Welcome to {plan_name}",
        f"<p>{_greeting(context)}</p>"
        f"<p>You're now on <strong>{_PRODUCT_NAME} {plan_name}</strong>. "
        "Your new caps and feature access are live immediately.</p>"
        + _button("Open billing settings", billing_url),
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"You're now on {_PRODUCT_NAME} {plan_name}. Your new caps and "
        "feature access are live immediately.\n\n"
        f"Billing settings: {billing_url}\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


def _render_subscription_archived(
    context: dict[str, Any],
) -> tuple[str, str, str]:
    """Plain notification when an org transitions read_only → archived.

    No CTA — the next user-facing action is `org.deleted` at the
    end of the archive window, and we want the customer to reach
    out to support if they want to recover before that fires.
    """
    subject = f"Your {_PRODUCT_NAME} account has been archived"
    body_html = _shell(
        "Account archived",
        f"<p>{_greeting(context)}</p>"
        f"<p>Your {_PRODUCT_NAME} account has been archived after an "
        "extended read-only period. Your data will be retained for "
        "90 more days. Email us if you'd like to restore access.</p>",
    )
    body_text = (
        f"{_greeting(context)}\n\n"
        f"Your {_PRODUCT_NAME} account has been archived. We'll keep "
        "your data for 90 more days; reply to this email if you'd like "
        "to restore access.\n\n"
        f"Questions? Email {_SUPPORT_EMAIL}.\n"
    )
    return subject, body_html, body_text


# ---------------------------------------------------------------------------
# Dispatch table — keep in sync with `BillingEmailKey` in `notifications.py`.
# ---------------------------------------------------------------------------


Renderer = Callable[[dict[str, Any]], tuple[str, str, str]]


RENDERERS: dict[str, Renderer] = {
    "trial_ending_soon": _render_trial_ending_soon,
    "trial_expired": _render_trial_expired,
    "subscription_archived": _render_subscription_archived,
    "payment_succeeded": _render_payment_succeeded,
    "payment_failed": _render_payment_failed,
    "seats_added": _render_seats_added,
    "plan_changed": _render_plan_changed,
}


def render(
    template_key: str,
    context: dict[str, Any],
) -> tuple[str, str, str] | None:
    """Render a template; returns `(subject, html, text)` or `None`.

    Unknown keys return `None` so the caller logs and skips instead of
    raising — billing emails are best-effort by contract.
    """
    renderer = RENDERERS.get(template_key)
    if renderer is None:
        return None
    return renderer(context)
