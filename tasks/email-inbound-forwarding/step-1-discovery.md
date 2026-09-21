# Step 1: Discovery — Mailgun Routes + provider forwarding guides + wizard benchmarks

**Status:** Pending

## Goal

Timebox 2h. Fetch verbatim provider forwarding guides for 6 mail providers + Mailgun Routes API details + HubSpot/Front/Missive wizard shapes. Lock the wizard content.

## Files touched

- `tasks/email-inbound-forwarding/DISCOVERY-NOTES.md` — URLs + provider-guide verbatim
- `tasks/email-inbound-forwarding/PROVIDER-GUIDES.md` — one section per provider (6 total)

## What this step does

- Mailgun Routes API:
  - Fetch `https://documentation.mailgun.com/en/latest/user_manual.html#routes`
  - Confirm existing catch-all `.*@in.karmcrm.com` route from mailgun-inbound track handles both `in_*` and `f-*` prefixes without additional routes.
  - Confirm route `forward()` action semantics (not `store()`).
- Provider guides (verbatim from provider docs, no paraphrasing):
  1. **Gmail personal**: `https://support.google.com/mail/answer/10957` — Settings → Forwarding and POP/IMAP → Add a forwarding address → enter `f-<token>@in.karmcrm.com` → Gmail sends verification email to that address → user copies confirmation code from CRM inbox → paste back into Gmail → enable forwarding rule.
  2. **Google Workspace**: `https://support.google.com/a/answer/4524505` — Admin console → Apps → Google Workspace → Gmail → Routing → Add setting.
  3. **Outlook.com personal**: `https://support.microsoft.com/en-us/office/turn-on-automatic-forwarding-in-outlook-com`
  4. **Outlook 365 (Exchange)**: `https://learn.microsoft.com/en-us/exchange/policy-and-compliance/mail-flow-rules/`
  5. **Zoho Mail**: Zoho help center forwarding setup.
  6. **Custom (IMAP-only server)**: Sieve rule + Return-Path guidance.
- Wizard shape benchmarks (unsourced initially; verify by screenshot request from user):
  - HubSpot Shared Inbox — 3-step: pick provider, copy address, guide + test.
  - Front — IMAP-connect-first (differs from our forwarding-first approach).
  - Missive — forwarding-first, single-guide-page.

## Verification checklist

- [ ] `DISCOVERY-NOTES.md` cites all URLs actually fetched this session
- [ ] `PROVIDER-GUIDES.md` has 6 provider sections with verbatim step lists
- [ ] Mailgun Routes API confirms no new route needed (existing catch-all handles f-* prefix)
- [ ] Wizard-shape benchmarks noted; screenshot-shopping-list flagged to user

## Self-check

- DISCOVERY_RULES rule zero: pass — URLs fetched, not recalled.
- Timebox: kept to 2h.

## Stop-and-report

Report file paths, URL count. Flag screenshot-shopping-list to user for HubSpot/Front/Missive wizards. **Awaiting your "proceed" for Step 2.**
