# Step 14 — Deliverability + bounce/complaint webhooks + DKIM/SPF status

**Goal:** Wire email bounce + complaint webhooks from the configured email provider (Mailgun / SendGrid / SES / Postmark) into a suppression list. Surface DKIM/SPF/DMARC status per sender domain in Settings → Email so the Owner knows when their domain is "warm" and ready. Open + click tracking pixels added to outgoing automation emails so the per-contact timeline (Step 9) shows engagement.
**Status:** Pending
**Depends on:** Step 4 (dispatcher), Step 9 (per-contact timeline), `core/email/` (existing mailbox foundation).

---

## Scope

In-scope:
- Migration `<ts>_deliverability_tables.py`:
  - `tbl_email_bounce_events` — id, org_id, email_address, bounce_type (`hard | soft | complaint | unsubscribe`), provider_event_id text unique, raw_payload JSONB, received_at. RLS + index `(org_id, email_address)`.
  - `tbl_automation_suppressions` — id, org_id, channel (`email | sms | whatsapp`), address (email/phone), reason (`hard_bounce | complaint | unsubscribe | manual`), source_event_id nullable, created_at. Unique `(org_id, channel, address)`.
- `core/email/bounce_handler.py`:
  - Provider-agnostic webhook handlers for Mailgun, SendGrid, SES, Postmark. Each parser converts the provider's specific payload into a normalized `BounceEvent`.
  - On `hard_bounce | complaint | unsubscribe`: writes a `tbl_automation_suppressions` row.
- `POST /api/v1/email/bounce-webhook/{provider}` — public endpoint (HMAC-validated per provider). One endpoint per provider plus a router that picks the right parser.
- `core/automation/send_guard.py` extension:
  - `check_suppression(template, recipient, db) → (allow, reason)` — looks up `tbl_automation_suppressions` for the recipient + channel. Suppressed = blocked.
  - Wired into the composite `evaluate(run)`.
- `core/email/dkim_spf_check.py`:
  - `check_domain(domain) → DomainAuthStatus {spf, dkim, dmarc, last_checked_at}` — DNS lookup via async resolver; cached in `tbl_organizations.email_domain_auth_status JSONB` for 6 hours.
  - `GET /api/v1/email/domain-status?domain=...` endpoint.
- Open + click tracking:
  - Email template renderer (Step 11 from `tasks/template-library/` polish OR here) adds an open-tracking pixel + rewrites links via a CRM redirect that records the click.
  - `tbl_automation_runs` extended with `opened_at`, `clicked_at` columns (one open + one first-click captured; multi-event tracking deferred).
- Settings → Email tab UI extension:
  - DKIM/SPF/DMARC status badges per configured sender domain.
  - "Test send" → triggers `check_domain` + displays results.
  - Suppression list viewer: filter by channel + reason; manual unsuppress action.

Out of scope:
- Domain warming automation (gradual send-volume ramp-up) — defer.
- A/B testing of subject lines — defer (different track).
- WhatsApp bounce equivalents — Meta reports them via the existing failure webhook (already wired in `whatsapp-platform-upgrade` Step 21's failure classifier).

## Files to touch

| File | Action |
|---|---|
| `API/alembic/versions/<ts>_deliverability_tables.py` | **NEW** |
| `API/alembic/versions/<ts>_automation_runs_engagement.py` | **NEW** — adds opened_at + clicked_at |
| `API/src/app/core/email/bounce_handler.py` | **NEW** |
| `API/src/app/core/email/dkim_spf_check.py` | **NEW** |
| `API/src/app/core/email/router.py` | edit — webhook + domain-status endpoints |
| `API/src/app/core/automation/send_guard.py` | edit — check_suppression |
| `API/src/app/core/automation/tasks.py` | edit — wire pixel + link rewriting into deliver_run |
| `API/src/app/core/automation/models.py` | edit — opened_at + clicked_at |
| `API/src/app/core/automation/tracking.py` | **NEW** — open + click endpoints |
| `APP/src/app/features/user/core/settings/email-accounts/domain-status.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/email-accounts/domain-status.component.html` | **NEW** |
| `APP/src/app/features/user/core/settings/email-accounts/suppression-list.component.ts` | **NEW** |
| `APP/src/app/features/user/core/settings/email-accounts/suppression-list.component.html` | **NEW** |
| `API/tests/automation/test_deliverability.py` | **NEW** |

**~14 files. ~700 lines** — at Rule 8 upper bound; the deliverability surface is intrinsically broad. Acceptable per the WhatsApp-track precedent (Step 8 / Step 21 sized similarly).

## Plan

1. Two migrations: tables + engagement columns.
2. Bounce handler module with per-provider parsers.
3. Webhook endpoints (HMAC-validated).
4. send_guard suppression check.
5. DKIM/SPF/DMARC resolver + cached domain status.
6. Pixel + link rewriting in deliver_run.
7. Public open/click endpoints (no auth — just the run_id; HMAC-signed token in the URL to prevent guessing).
8. Settings UI components for domain status + suppression list.
9. Tests: per-provider parser, HMAC validation, suppression check end-to-end, domain resolution.

## DB changes / migrations

Two migrations: deliverability tables + engagement columns. Reversible.

## Tests

15 pytest cases:
- Mailgun hard-bounce parser produces correct BounceEvent.
- SendGrid complaint parser.
- SES bounce parser.
- Postmark parser.
- HMAC validation rejects forged webhooks.
- Suppression list write on hard_bounce.
- Suppression list write on complaint.
- Suppression list write on unsubscribe.
- check_suppression blocks send for suppressed recipient.
- check_suppression allows send for un-suppressed.
- Manual unsuppress removes the row + allows next send.
- DKIM check returns valid/invalid/unknown for known fixtures.
- Open tracking pixel hit updates `opened_at`.
- Click tracking redirect updates `clicked_at` + 302s to target URL.
- Open/click endpoints validate HMAC token.

## Smoke

```
1. Configure Mailgun webhook URL pointing at /api/v1/email/bounce-webhook/mailgun.
2. Send an email to a known-invalid address → Mailgun fires a hard-bounce webhook → tbl_email_bounce_events row + tbl_automation_suppressions row.
3. Re-send to the same address → automation run status=skipped, error=suppressed.
4. Settings → Email Accounts → domain status shows the connected domain's DKIM/SPF/DMARC state.
5. Send an automation email + open it in test inbox → opened_at populated.
6. Click a link in the email → redirected to target; clicked_at populated.
7. Per-contact timeline tab shows the open + click on the contact's automation row.
8. Manual unsuppress action → next send to that address succeeds.
```

## Risks

- Webhook signature verification per provider — each has its own HMAC scheme; documented per parser.
- Pixel + link rewriting changes the rendered HTML; must not break email rendering in Gmail/Outlook. Test fixtures cover common clients.
- DNS resolution latency — cache aggressively; fail open (status=`unknown`) rather than blocking sends.
- Open tracking pixel privacy implications under DPDP — opt-in to marketing implies opt-in to engagement tracking, but document this in the Settings UI tooltip + Privacy Policy template (the latter is a docs task, not code).

## Self-check (10 rules)

`core/email/` + `core/automation/`. ✓ org_id propagated. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions: webhook is public + HMAC-gated; suppression list view gated on existing email settings perm. pack.yaml untouched. ✓ 14 files / ~700 lines — at Rule 8 upper bound; deliverability intrinsically wide. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 14 — Deliverability + bounce/complaint webhooks + DKIM/SPF status
Files: 14
Verify: provider webhooks update suppression list; suppression check blocks sends; DKIM/SPF/DMARC surfaced; open/click tracking populates engagement columns.
Tests: 15 pytest cases.

Track complete: 14 steps shipped. Event-trigger engine live with seeded user.signed_up + lead.created + appointment + quote/invoice + birthday/stale-lead triggers. Send-time enforcement honors DPDP + frequency cap + quiet hours + suppression. Deliverability surface complete. Per-contact timeline shows full engagement.

Combined with tasks/template-library/: the standard CRM template + automation surface is feature-complete vs HubSpot / Zoho / Salesforce baseline.

Next track (future): tasks/workflows/ — multi-step branching flowcharts + sequences relocation.

Awaiting "proceed".
```
