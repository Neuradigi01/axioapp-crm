# Step 11 — Quote and invoice triggers

**Goal:** Publish quote / invoice lifecycle events + seed default triggers so the operator gets a working "send quote → customer receives professional email" flow out of the box.
**Status:** Pending
**Depends on:** Step 10 (event-publish pattern). `core/billing/` or whichever module owns quotes + invoices.

---

## Scope

In-scope:
- `core/events/event_catalog.py` — add five events:
  - `quote.sent` — when operator clicks "Send to customer" on a quote. Payload: `{quote_id, org_id, contact_id, contact_snapshot, quote_pdf_url, total_amount, currency}`.
  - `quote.accepted` — when customer accepts (signature flow / portal action). Payload: same + `accepted_at`.
  - `invoice.sent` — when an invoice is dispatched. Payload: `{invoice_id, org_id, contact_id, contact_snapshot, invoice_pdf_url, total_amount, currency, due_date}`.
  - `invoice.paid` — payment recorded. Payload: same + `paid_at`, `payment_method`.
  - `invoice.overdue_7d` — fires 7 days past due_date for unpaid invoices.
- Publish calls in the relevant module's services (quote-sent endpoint, quote-acceptance webhook, invoice-create endpoint, payment-recorded endpoint).
- Celery beat task `invoices.scan_for_overdue` runs daily at the configured time (default 9am org tz) — scans unpaid invoices past `due_date + 7 days` and publishes `invoice.overdue_7d` (idempotent via event_id).
- `core/automation/seeds.py` extension:
  - `seed_quote_sent_*` (channel=email; uses `{{contact.first_name}}`, `{{quote.total_amount}}` variables).
  - `seed_quote_accepted_*` (channel=email; thank-you message).
  - `seed_invoice_sent_*` (channel=email; invoice PDF attached via the central template attachments).
  - `seed_invoice_paid_*` (channel=email; receipt).
  - `seed_invoice_overdue_*` (channel=email + WhatsApp; payment reminder).
- Variable engine extension in `core/templates/variables.py`: adds `{{quote.*}}` and `{{invoice.*}}` namespaces. Per-channel registry update so the editor's variable picker shows them.
- Backfill migration for existing orgs.

Out of scope:
- Quote rejection event (defer).
- Multi-currency invoice formatting beyond INR/USD/AED (existing currencies module covers what's needed).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/events/event_catalog.py` | edit — register five events |
| `API/src/app/core/billing/quotes_service.py` | edit — publish quote.sent + quote.accepted |
| `API/src/app/core/billing/invoices_service.py` | edit — publish invoice.sent + invoice.paid |
| `API/src/app/core/billing/tasks.py` | edit — overdue scanner |
| `API/src/app/core/templates/variables.py` | edit — add quote.* and invoice.* namespaces |
| `API/src/app/core/automation/seeds.py` | edit — five new seeders |
| `API/src/app/core/tenants/service.py` | edit — call new seeders on org create |
| `API/alembic/versions/<ts>_seed_quote_invoice_triggers_existing_orgs.py` | **NEW** |
| `API/tests/automation/test_quote_invoice_triggers.py` | **NEW** |

**~9 files. ~550 lines.**

## Plan

1. Catalog entries.
2. Publish calls in each business service after commit.
3. Beat task for overdue invoices.
4. Seeders for templates + triggers.
5. Variable engine extension.
6. Backfill migration.
7. Tests: each event publishes; seeded triggers fire; overdue scanner picks up old unpaid invoices.

## DB changes / migrations

One backfill migration only.

## Tests

8 pytest cases — one per event + scanner + idempotency.

## Smoke

```
1. POST /quotes/{id}/send → customer email arrives with the quote.
2. POST /quotes/{id}/accept → thank-you email arrives.
3. POST /invoices → invoice email arrives with PDF.
4. POST /invoices/{id}/payments → receipt email arrives.
5. Create an invoice with due_date 8 days ago, status=unpaid.
6. Run the daily beat task manually → invoice.overdue_7d publishes → reminder email + WhatsApp arrive.
```

## Risks

- Currency formatting in `{{invoice.total_amount}}` must be locale-aware. The variables module formats per org locale at resolve time.
- Invoice PDF attachment exceeds email provider limits (~20MB). Existing email send path handles this with a "view in browser" link fallback — confirm the seeded template uses the link, not a direct attach, for invoices over 5MB.

## Self-check (10 rules)

`core/billing/` + `core/automation/seeds.py` + `core/templates/variables.py`. ✓ org_id propagated. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions already registered. ✓ pack.yaml untouched. ✓ 9 files / ~550 lines. ✓ Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 11 — Quote and invoice triggers
Files: 9
Verify: five events publishing; five seeded triggers active per org; daily overdue scan fires reminders.
Tests: 8 pytest cases.
Awaiting "proceed".
```
