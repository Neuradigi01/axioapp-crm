# Step 20 — Email notifications for billing

**Goal:** Implement the six billing-related email templates and SMTP delivery wiring, replacing the stub introduced in Step 6. Owners receive: trial-ending-in-3-days, trial-expired, payment-succeeded, payment-failed, seat-overage-charged, plan-changed.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** `core/notifications` module (Phase 3.x) — must provide an SMTP backend with template rendering. Step 6 (lifecycle — calls into the email send function). Step 13 (webhook handlers — call into the email send for payment events).

---

## Scope

Six email templates (HTML + plain-text), one `send_billing_email` implementation that consumes them, Celery task queueing for async delivery, and tests covering each template's data binding.

## The six emails

| Template key | Trigger | To | Subject |
|---|---|---|---|
| `trial_ending_soon` | 3 days before `trial_ends_at` (Step 6 scheduled task) | Owner | "Your CRM trial ends in 3 days" |
| `trial_expired` | Trial → read_only transition (Step 6) | Owner | "Your CRM trial has ended" |
| `payment_succeeded` | `invoice.paid` webhook (Step 13) | Owner | "Payment received — thanks!" |
| `payment_failed` | `invoice.payment_failed` webhook (Step 13) | Owner | "We couldn't charge your card" |
| `seats_added` | Seat-add payment succeeded | Owner | "{N} seats added to your plan" |
| `plan_changed` | `checkout.session.completed` webhook for an existing customer (plan change) | Owner | "Welcome to CRM {plan_name}" |

(Email for "trial_ending_soon" with `1 day` remaining could be added — defer to a follow-up unless requested.)

## Template structure

`api/src/app/core/billing/email_templates/`:

```
trial_ending_soon.html
trial_ending_soon.txt
trial_expired.html
trial_expired.txt
payment_succeeded.html
payment_succeeded.txt
payment_failed.html
payment_failed.txt
seats_added.html
seats_added.txt
plan_changed.html
plan_changed.txt
```

Templates use Jinja2 (already in the stack per FastAPI convention). Common variables every template receives:

```python
context = {
    "owner_first_name": ...,
    "org_name": ...,
    "plan_name": "Basic" | "Standard" | "Enterprise" | "Trial",
    "trial_ends_at": ...,      # for trial emails
    "days_remaining": ...,
    "amount_paid_usd": ...,    # for payment emails
    "invoice_pdf_url": ...,
    "billing_url": "https://app.example.com/user/settings/billing",
    "upgrade_url": "https://app.example.com/user/settings/billing/upgrade",
    "support_email": "support@yourcrm.com",
}
```

Template-specific variables added per-email.

## Send function

`api/src/app/core/billing/notifications.py`:

```python
async def send_billing_email(
    org_id: UUID,
    template_key: str,
    context: dict,
) -> None:
    """
    Resolves the Owner of the org, renders the template, queues to Celery for delivery.
    Replaces the stub from Step 6.

    Idempotency: callers must dedupe themselves (e.g. lifecycle reminders use the
    reminders_sent JSONB or subscription_reminders table from Step 6).
    """
    owner = await user_service.get_owner(org_id)
    if owner is None:
        log.warning(f"No Owner found for org {org_id}; cannot send {template_key}")
        return

    rendered_html = render_template(f"{template_key}.html", context)
    rendered_txt = render_template(f"{template_key}.txt", context)

    notifications.send_email.delay(
        to=owner.email,
        subject=_subject_for(template_key, context),
        html=rendered_html,
        text=rendered_txt,
    )
```

`notifications.send_email` is the existing Celery task from `core/notifications` (Phase 3.x). This step does NOT introduce new SMTP infrastructure — it consumes what's already there.

## Wiring into Step 6 and Step 13

Step 6 (lifecycle) already calls `notifications.send_billing_email(...)` (the stub). This step provides the real implementation. The stub deletion is the wiring change.

Step 13 (webhook handlers) — each handler that already has an audit-event call adds a corresponding email call:

```python
# Inside on_invoice_paid handler
await send_billing_email(
    org_id=sub.org_id,
    template_key="payment_succeeded",
    context={
        "amount_paid_usd": invoice.amount_paid_cents / 100,
        "invoice_pdf_url": invoice.hosted_invoice_url,
        ...
    },
)
```

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/billing/notifications.py` | modified (was stub from Step 6) — real `send_billing_email` implementation |
| `api/src/app/core/billing/email_templates/trial_ending_soon.html` | created |
| `api/src/app/core/billing/email_templates/trial_ending_soon.txt` | created |
| `api/src/app/core/billing/email_templates/trial_expired.html` | created |
| `api/src/app/core/billing/email_templates/trial_expired.txt` | created |
| `api/src/app/core/billing/email_templates/payment_succeeded.html` | created |
| `api/src/app/core/billing/email_templates/payment_succeeded.txt` | created |
| `api/src/app/core/billing/email_templates/payment_failed.html` | created |
| `api/src/app/core/billing/email_templates/payment_failed.txt` | created |
| `api/src/app/core/billing/email_templates/seats_added.html` | created |
| `api/src/app/core/billing/email_templates/seats_added.txt` | created |
| `api/src/app/core/billing/email_templates/plan_changed.html` | created |
| `api/src/app/core/billing/email_templates/plan_changed.txt` | created |
| `api/src/app/core/billing/lifecycle.py` | modified — remove stub, ensure real calls in trial-ending-soon and trial-expired |
| `api/src/app/core/billing/webhooks/handlers/invoice_paid.py` | modified — add email call |
| `api/src/app/core/billing/webhooks/handlers/invoice_failed.py` | modified — add email call |
| `api/src/app/core/billing/webhooks/handlers/checkout_completed.py` | modified — distinguish first-payment vs plan-change and send the right email |
| `api/tests/core/billing/test_billing_emails.py` | created |

**18 files**, but 12 of them are tiny email templates. Code surface is 6 files. Within rule spirit. If reviewers want a split: 20.a (notifications.py + templates) and 20.b (wiring into lifecycle and webhooks + tests).

## Tests

`test_billing_emails.py`:

- **`send_billing_email` resolves Owner correctly:** seed org with Owner → call function → assert Celery task queued with Owner's email as `to`.
- **No-owner edge case:** seed org with no Owner (shouldn't happen post RBAC-Ownership Step 1 but defensive) → log warning, no exception, no task queued.
- **Template rendering doesn't crash on minimal context:** every template renders with the documented minimum context dict.
- **Owner first_name fallback:** if first_name is null, template uses "there" or "team."
- **Subject lines correctly populated:** assert `_subject_for("payment_succeeded", ...)` returns the right subject including org context.
- **`trial_ending_soon` runs once per trial:** dedup mechanism (from Step 6) prevents repeats; verify via the reminders_sent flag.
- **`payment_succeeded` includes link to invoice PDF:** rendered HTML contains the `hosted_invoice_url`.
- **`plan_changed` distinguishes upgrade from first-payment:** if subscription was trialing before, send `plan_changed` (not `payment_succeeded`); if already active, send `payment_succeeded` only.
- **Failure in email delivery does not break the parent action:** monkey-patch Celery delay to raise → trial transition still succeeds; warning logged.

## Smoke

```
# Ensure SMTP is configured in .env (from Phase 3.x notifications setup).
# .\API\docker-helper.cmd up

docker exec template_api-api-1 pytest tests/core/billing/test_billing_emails.py -v

# End-to-end:
# 1. Force trial to be 3 days from expiry on Ajay's Workspace.
# 2. Trigger the lifecycle scan:
docker exec template_api-api-1 celery -A app.shared.celery_app call \
  app.core.billing.tasks.advance_trial_lifecycle

# 3. Check Ajay's inbox (or the captured-email log if using a local SMTP catcher like Mailpit).
# → "Your CRM trial ends in 3 days" email received.

# 4. Force trial to be expired:
# UPDATE subscriptions SET trial_ends_at=now() - interval '1h' WHERE org_id=...
docker exec template_api-api-1 celery -A app.shared.celery_app call \
  app.core.billing.tasks.advance_trial_lifecycle
# → "Your CRM trial has ended" email received.

# 5. Complete a real Stripe checkout (Steps 12 + 13).
# → "Welcome to CRM Standard" email received.

# 6. Use a card that fails (4000 0000 0000 0341) on a subsequent renewal.
# → "We couldn't charge your card" email received.
```

## Risks

- **Email deliverability.** SPF / DKIM / DMARC on the sending domain is Phase 3.x's concern. If those are misconfigured, billing emails land in spam — and these are exactly the emails customers can't afford to miss. Verify on staging before prod.
- **Template HTML rendering across mail clients.** Use simple HTML; tables for layout (still 2026's email reality). Test in Gmail web, Apple Mail, Outlook web. No CSS-in-head reliance — use inline styles for important things.
- **Sensitive data in emails.** Don't include credit card last-4 unless absolutely needed (and never the full PAN, which we don't have anyway). Don't include subscription IDs that are useful to anyone but support.
- **Locale / translation.** All copy is in English. INR users / non-English Owners get English emails. Acceptable for v1; flag for i18n when expanding internationally.
- **Per memory `feedback_branding_crm_not_furnicrm`:** emails say "CRM" not "FurniCRM."

## Rollback

Revert the 18 files. The stub from Step 6 must be restored (or replaced with a noop). Lifecycle transitions continue (audit events fire) but no emails go out. Communicate so customers aren't surprised by missing notifications.

---

## Track conclusion

Step 20 closes the Pricing and Billing track. With all 20 steps landed, the Core CRM is **fully self-served**:

- A visitor can land at `/pricing`, sign up for a free 14-day trial.
- Their org is automatically created with a trialing subscription.
- They use the product. The banner reminds them of the countdown.
- They get an email 3 days before expiry.
- They upgrade through the in-app modal → Stripe Checkout → webhook updates state.
- They receive a welcome email + future invoices.
- They can manage seats, downgrade, cancel — all without our intervention.
- If they don't upgrade, they're gently moved to read-only, then archived, then deleted.

The next track to layer on top is **Furniture Pack pricing**, which composes onto this Core foundation by adding `furniture-*` plan codes to `plans.yaml` (or `packs/furniture/pricing.yaml`).
