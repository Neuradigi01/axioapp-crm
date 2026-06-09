# Step 13 — Stripe webhook handler + invoice records

**Goal:** A `POST /api/v1/webhooks/stripe` endpoint that receives Stripe events, verifies the signature, dedupes by event ID, and applies them to our local subscription + invoice state. Plus a `subscription_invoices` table that mirrors Stripe invoices for in-app history.
**Track:** Pricing and Billing
**Status:** Completed
**Depends on:** Step 11 (Stripe provider — `verify_webhook`), Step 12 (checkout sessions — populates `pending_checkout_session_id`).

---

## Scope

Three things:

1. **Webhook endpoint** — receives Stripe events, idempotent.
2. **Event handlers** — one per event type we care about (Checkout completed, invoice paid/failed, subscription updated, subscription cancelled).
3. **`subscription_invoices` table** — local mirror of Stripe invoices for `/user/settings/billing` to show.

This is the largest payment-side step. Internally split into clear sub-tasks for the < 400-line / < 10-file budget.

## Schema

### New table: `subscription_invoices`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `org_id` | UUID FK → organizations | indexed, RLS |
| `subscription_id` | UUID FK → subscriptions | indexed |
| `stripe_invoice_id` | TEXT UNIQUE NOT NULL | from Stripe |
| `number` | TEXT | Stripe-generated human-readable invoice number |
| `status` | TEXT NOT NULL | `paid`, `open`, `void`, `uncollectible`, `draft` |
| `amount_due_cents` | INTEGER NOT NULL | |
| `amount_paid_cents` | INTEGER NOT NULL | |
| `currency` | TEXT NOT NULL DEFAULT 'USD' | |
| `period_start` | TIMESTAMPTZ | |
| `period_end` | TIMESTAMPTZ | |
| `hosted_invoice_url` | TEXT | Stripe-hosted PDF/HTML for the customer to view |
| `pdf_url` | TEXT | direct PDF link |
| `paid_at` | TIMESTAMPTZ NULL | |
| `created_at` | TIMESTAMPTZ NOT NULL | |

Migration `00XX_subscription_invoices.py` — table + indexes + RLS.

### New table: `stripe_webhook_events` (dedup ledger)

| Column | Type | Notes |
|---|---|---|
| `stripe_event_id` | TEXT PRIMARY KEY | unique constraint = dedup |
| `event_type` | TEXT NOT NULL | e.g. `checkout.session.completed` |
| `received_at` | TIMESTAMPTZ NOT NULL | |
| `processed_at` | TIMESTAMPTZ NULL | null until handler completes |
| `payload` | JSONB NOT NULL | the raw event for replay/debug |
| `error` | TEXT NULL | populated on handler exception |

Migration `00XX_stripe_webhook_events.py`. No `org_id` (event might land before we've resolved which org); RLS off.

## Endpoint

`POST /api/v1/webhooks/stripe`

- **Unauthenticated** (Stripe signs the request body; we verify signature instead of JWT).
- Reads raw body, calls `provider.verify_webhook(payload, signature)`.
- Inserts dedup row in `stripe_webhook_events` (ON CONFLICT → return 200 silently, idempotent replay).
- Dispatches to a handler based on event type:

| Event type | Handler |
|---|---|
| `checkout.session.completed` | `on_checkout_completed` — find org via session metadata, flip subscription to `active`, set plan_code/billing_cycle/seats from metadata, link `stripe_subscription_id`, clear `pending_checkout_session_id`. Emit audit `subscription.upgraded`. |
| `invoice.paid` | `on_invoice_paid` — upsert `subscription_invoices` row with status=`paid`, paid_at set. If subscription was `past_due`, flip to `active`. Emit audit `payment.succeeded`. Queue email (Step 20). |
| `invoice.payment_failed` | `on_invoice_failed` — upsert invoice row with status=`open`, set subscription status to `past_due`. Emit audit `payment.failed`. Queue email. |
| `invoice.finalized` | `on_invoice_finalized` — upsert with status from Stripe. Used to back-fill new invoices we missed. |
| `customer.subscription.updated` | `on_subscription_updated` — apply seat/plan/cycle changes Stripe reports (covers manual changes in Stripe Dashboard). |
| `customer.subscription.deleted` | `on_subscription_cancelled` — flip our subscription to `cancelled`, set `cancelled_at`. Emit audit. |
| (any other) | log and ignore — return 200 |

- Updates `processed_at` on success; populates `error` on failure (but still returns 500 so Stripe retries).
- All handlers are **idempotent** (safe to call twice with same event).

## Implementation layout

```
api/src/app/core/billing/webhooks/
├── __init__.py
├── router.py                  # POST /webhooks/stripe — verify, dedup, dispatch
├── handlers/
│   ├── __init__.py
│   ├── checkout_completed.py
│   ├── invoice_paid.py
│   ├── invoice_failed.py
│   ├── subscription_updated.py
│   └── subscription_cancelled.py
```

## Files to touch

| File | Action |
|---|---|
| `api/alembic/versions/00XX_subscription_invoices.py` | created |
| `api/alembic/versions/00XX_stripe_webhook_events.py` | created |
| `api/src/app/core/billing/models.py` | modified — add `SubscriptionInvoice`, `StripeWebhookEvent` |
| `api/src/app/core/billing/webhooks/router.py` | created — endpoint + dispatch |
| `api/src/app/core/billing/webhooks/handlers/checkout_completed.py` | created |
| `api/src/app/core/billing/webhooks/handlers/invoice_paid.py` | created |
| `api/src/app/core/billing/webhooks/handlers/invoice_failed.py` | created |
| `api/src/app/core/billing/webhooks/handlers/subscription_updated.py` | created |
| `api/src/app/core/billing/webhooks/handlers/subscription_cancelled.py` | created |
| `api/src/app/main.py` | modified — include webhooks router |
| `api/src/app/core/billing/router.py` | modified — `GET /subscriptions/invoices` for the in-app invoice list |
| `api/tests/core/billing/test_webhook_dedup.py` | created |
| `api/tests/core/billing/test_webhook_handlers.py` | created |

**13 files + 2 migrations.** This step exceeds the < 10 files / < 400 lines rule. Per the README's note, splitting:

### Sub-step 13.a (lands first):
- 2 migrations
- `models.py` (both new tables)
- `webhooks/router.py` (endpoint + dedup, no real handlers yet — events log and return 200)
- `test_webhook_dedup.py`

### Sub-step 13.b (lands after 13.a):
- All 5 handler files
- Wire dispatch table in `router.py`
- `test_webhook_handlers.py`

### Sub-step 13.c (lands after 13.b):
- `GET /subscriptions/invoices` endpoint
- Invoice list schema
- `test_invoices_list.py`

Each sub-step is ≤ 10 files. The step file describes the full picture; the implementation is done in 3 commits. **Report after each sub-step.**

## Tests

### `test_webhook_dedup.py`:

- **Signature verification fail → 400:** POST with wrong signature → 400, no row inserted.
- **First event → 200, processed_at set:** valid signature, fresh event ID → handler runs, row written with `processed_at` not null.
- **Replay of same event → 200 idempotent:** post same event twice → second one is no-op, single row remains.
- **Handler exception → 500, error field set, NOT marked processed:** handler raises → response is 500 (Stripe retries), row has `error` populated, `processed_at` null. Next replay can process it again.

### `test_webhook_handlers.py`:

- **`checkout.session.completed` flips subscription:** seed trial sub + checkout session metadata → process event → assert `status='active'`, `plan_code` matches metadata, `stripe_subscription_id` linked.
- **`invoice.paid` upserts invoice:** process event → row in `subscription_invoices`, `status='paid'`, `paid_at` set.
- **`invoice.paid` resumes past_due:** seed past_due sub → process event → flip to active.
- **`invoice.payment_failed` flips to past_due:** seed active sub → process → status='past_due'.
- **`customer.subscription.updated` syncs seats:** Stripe says `quantity=8` → our `seats_purchased` updates.
- **`customer.subscription.deleted` cancels:** process event → `status='cancelled'`, `cancelled_at` set.
- **Unknown event type logged and ignored:** process `fake.event.type` → 200, row written with `processed_at`, no error.
- **Audit events written:** each handler emits its event to `audit_logs`.
- **Idempotency on handlers:** running the same handler twice on the same subscription does not double-bill or double-create invoices.

### `test_invoices_list.py` (sub-step 13.c):

- **GET `/subscriptions/invoices` returns paid invoices in reverse-chrono order:** 200, list of invoices with `hosted_invoice_url` and `pdf_url`.
- **RLS isolation:** auth as org A, no org B invoices visible.

## Smoke

End-to-end smoke needs Stripe CLI for webhook forwarding:

```
# 1. Install Stripe CLI (one-time): https://stripe.com/docs/stripe-cli
# 2. Run forwarder (it prints a webhook signing secret to use):
stripe listen --forward-to http://localhost:8000/api/v1/webhooks/stripe
# → outputs: whsec_xxxxxxxx — paste into .env STRIPE_WEBHOOK_SECRET, restart container.

# 3. Run pytest:
.\API\docker-helper.cmd migrate
docker exec template_api-api-1 pytest tests/core/billing/test_webhook_dedup.py -v
docker exec template_api-api-1 pytest tests/core/billing/test_webhook_handlers.py -v

# 4. Live smoke: trigger a checkout from Step 12, pay with test card.
# → Stripe CLI forwards `checkout.session.completed` to our endpoint.
# → DB check:
SELECT plan_code, status, stripe_subscription_id FROM subscriptions WHERE org_id = ...;
# → status='active', plan_code='standard' (or whichever was chosen).

# 5. List invoices:
TOKEN=...
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/subscriptions/invoices | jq
# → [{"number":"INV-001","status":"paid","amount_paid_cents":14500,"hosted_invoice_url":"...","pdf_url":"..."}]
```

## Risks

- **Webhook delivery lag.** Stripe usually delivers within seconds but SLA is "best effort." UX: the Stripe Checkout success page redirects to our `success_url` which can show "Processing..." until the webhook fires; or poll `GET /subscriptions/current` every 2s for up to 30s.
- **Webhook signing secret leak.** If leaked, an attacker can forge events and upgrade their own org to Enterprise. Mitigation: keep `STRIPE_WEBHOOK_SECRET` in env vars only, never in code or logs. Rotate quarterly.
- **Out-of-order events.** Stripe sometimes delivers `customer.subscription.updated` before `checkout.session.completed`. Handlers must be order-agnostic: each one looks up the current state and applies the event as a partial update. Idempotency tests cover this.
- **Handler exceptions hide bugs.** If a handler always raises, every event becomes a 500, Stripe retries forever, and our `stripe_webhook_events` table fills with error rows. Mitigation: alert on `stripe_webhook_events.error IS NOT NULL` count > threshold. Out of scope for v1; document the alert as future-work.
- **Stripe event payload schema drift.** Stripe occasionally adds fields. Handlers parse only the fields they need, ignoring the rest — defensive against added fields. They use `.get()` not `[]` for optional fields.
- **`subscription_invoices` row created by webhook before `subscription_id` is known.** If `invoice.paid` arrives before `checkout.session.completed`, the invoice has no subscription to point at. Mitigation: queue the invoice event for retry (re-process every webhook event whose handler errored) — practical implementation is the existing retry from Stripe itself; we return 500 if subscription not found.

## Rollback

Revert the 13 files + downgrade both migrations. Any past webhook events processed remain reflected in the subscription rows (no harm). Future events will 404 the endpoint → Stripe retries indefinitely until you re-enable. Manual ops via Stripe Dashboard while rolled back.
