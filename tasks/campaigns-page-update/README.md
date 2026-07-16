# Campaigns Page Update — v1 (WhatsApp + Email)

Track for finishing the Campaigns page into an industry-standard, ship-ready v1 covering **WhatsApp** and **Email** only. SMS / Voice / Messenger / Instagram / Web / Push are explicitly out of scope for this track.

The mockup for this track — every screen this delta touches — is at [`preview.html`](preview.html). Open it in a browser before working any step so you can see what "done" looks like.

## Why this track exists

- **WhatsApp already sends**, but the campaign template picker doesn't surface Meta's approval status inline — users don't know why a template can't be selected and have to open Business Manager to find rejection reasons.
- **Email doesn't send at all today.** The campaigns dispatch calls the generic `adapter.send()` which the Email adapter rejects with `EmailUseSendEmailEndpoint`. Every Email campaign fails.
- **Compliance is missing.** No unsubscribe footer auto-injection at the campaign layer, no `email_opt_in_status` on Contact, no sender-readiness or bounce pre-flight.

Track finishes when both channels work end-to-end and pass a real customer send.

## Build order + ship gates

| # | Step | Track | Screens affected | Status |
|---|---|---|---|---|
| 01 | [WA picker badges](step-01-wa-picker-badges.md) — approval + category + language in campaign template picker | WhatsApp | New Campaign wizard | COMPLETED |
| 02 | [WA rejection reason tooltip](step-02-wa-rejection-tooltip.md) — library list + picker | WhatsApp | WA Templates list · New Campaign wizard | COMPLETED |
| 03 | [Email sender identity](step-03-email-sender-identity.md) — mailbox + reply-to + subject + preheader on Campaign | Email | Create Email Template · New Campaign wizard | Pending |
| 04 | [Email HTML composer](step-04-email-html-composer.md) — `body_html` column + rich editor + merge-tag inserter + inbox preview | Email | Create Email Template | Pending |
| 05 | [Email dispatch wiring](step-05-email-dispatch-wiring.md) — call `adapter.send_email()` + funnel columns + tracking | Email | Campaign Report | Pending |
| 06 | [Email unsubscribe + opt-out](step-06-email-unsubscribe-optout.md) — auto-appended footer + `email_opt_in_status` on Contact | Email | Contact detail · Wizard exclusions · public `/unsubscribe/{token}` | Pending |
| 07 | [Email Sender Setup page](step-07-email-sender-setup-page.md) — SPF/DKIM/DMARC verification + bounce suppression pre-flight | Email | New Sender Setup page · Wizard pre-flight | Pending |

**Ship gates:**

- **After Step 02** — WhatsApp v1 UX complete. Users see approval status inline and understand rejection reasons without leaving the CRM.
- **After Step 05** — Email happy path works. Templates → campaign start → dispatch → funnel visible.
- **After Step 07** — Campaigns v1 ready for real customers. Sender verification, compliance footer, bounce suppression, opt-out enforcement all in place.

## Out of scope for this track

- SMS · Voice · Facebook Messenger · Instagram · Web push · Mobile push
- Multi-channel fallback chains ("WhatsApp then SMS")
- Journey / drip campaigns (workflows already covers multi-step flowcharts — separate track)
- Wallet debit / per-message cost estimator
- Plan gating per channel
- Channel-readiness dashboard (aggregate view across channels)
- Contact preferred-channel routing

These are future work — do not slip them into any step file here.

## Locked scope decisions

Recorded in project memory:

- Campaigns v1 = **WhatsApp + Email only** (2026-07-16 manager decision).
- Template approval status must render **inside the CRM UI**, not hidden behind Meta Business Manager.
- Industry-standard practices (dedup, rate limiting, opt-out enforcement, audit log) are baseline — not "gaps." Bake them in.

## Rules that apply to every step in this track

Straight from [`CLAUDE.md`](../../CLAUDE.md). Do not skip:

1. Every table has `org_id` and follows `tbl_<snake>` naming (`tbl_fp_` for pack — not applicable here). RLS filter enforced.
2. Backend layered architecture: `router.py` → `service.py` → `data_access.py`. Only `service.py` touches transactions.
3. Custom fields via layered JSONB `custom_data` + `custom_field_definitions.source` when a step needs them (none of these steps do).
4. No N+1: pre-load related data with `selectinload` / `joinedload`; audience iteration must not query per-row.
5. Reuse before create — check existing helpers before adding new ones (especially `template-status-badge.component.ts`, `EmailAccount`, `EmailBounce`, `dkim_spf_check.py`, and the existing WhatsApp send-guard pattern).
6. Prettier + eslint on any `app/**` file touched. Ruff on any `api/**` file. Pre-commit hook enforces.
7. Migrations run through `API/docker-helper.cmd` — the encrypted `.env` blocks host-side alembic.
8. Update the step file's `**Status:** Pending` → `**Status:** COMPLETED` and flip this README's row when a step lands. Do it before the stop-and-report.

## Testing discipline

Full pytest run takes ~12 minutes in this repo. Batch all code work for a step, then stop and ask before starting tests. Never run two pytest processes against the shared test DB concurrently.

## Verification target

- **Smoke tests** run against **Ajay's Workspace** (org `41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`) — NOT the Demo seed orgs.
- Every step's Verification section lists what to click / observe in the browser tab at that org.
