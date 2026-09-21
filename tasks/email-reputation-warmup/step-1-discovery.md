# Step 1: Discovery — Mailgun reputation + rate limits + events + `v:` docs (MANDATORY)

**Status:** Pending

## Goal

Fetch every Mailgun + ISP number that the reputation model needs. Prativani's thresholds are SES-shaped — do not lock them until Mailgun's own numbers are confirmed. Non-negotiable per DISCOVERY_RULES.md rule zero.

## Files touched

- `tasks/email-reputation-warmup/DISCOVERY-NOTES.md` — all URLs + verbatim fetched content
- `tasks/email-reputation-warmup/THRESHOLDS-LOCKED.md` — locked numeric decisions with source citations

## What this step does

- Mailgun reputation model:
  - `https://help.mailgun.com/hc/en-us/articles/360012573294-Managing-Your-Sender-Reputation`
  - Is reputation account-scope, sub-domain-scope, or per-domain? **This is the load-bearing question.**
  - Any published account-wide bounce/complaint thresholds?
- Mailgun rate limits:
  - `https://documentation.mailgun.com/en/latest/api-intro.html#rate-limiting`
  - Per-account per-hour, per-domain per-hour, burst behavior.
- Mailgun events webhook:
  - `https://documentation.mailgun.com/en/latest/user_manual.html#tracking-messages`
  - `https://documentation.mailgun.com/en/latest/api-webhooks.html`
  - Full event-type list (delivered, failed permanent, failed temporary, complained, unsubscribed, rejected).
  - Signature verification: same HMAC-SHA256 as inbound? Verify signing-key reuse.
  - Retry semantics: how many, how long?
- Mailgun `v:` custom variables:
  - `https://documentation.mailgun.com/en/latest/user_manual.html#attaching-data-to-messages`
  - Max count per send, max value length, allowed charset.
- ISP thresholds (public numbers):
  - Gmail Postmaster Tools thresholds (complaint rate, unsubscribe rate warning bands).
  - Microsoft SNDS reputation bands.
  - Yahoo Postmaster.
- Interim competitor recall (marked unsourced): SendGrid IP-warmup ladder, Mailchimp complaint policy, Klaviyo warmup wizard.
- Produce `THRESHOLDS-LOCKED.md`:
  - Warmup ladder caps (verified numbers or explicit "SES-Prativani default, revisit").
  - Complaint rate threshold (with source).
  - Bounce rate threshold (with source).
  - Event floor.
  - Rate limits (own-domain / platform-from).

## Verification checklist

- [ ] `DISCOVERY-NOTES.md` cites live URLs actually fetched this session
- [ ] `THRESHOLDS-LOCKED.md` has source per numeric value or explicit "provisional — no source"
- [ ] Reputation scope answered (account / sub-domain / per-domain)
- [ ] If web access unavailable → STOP + escalate per DISCOVERY_RULES.md

## Self-check

- DISCOVERY_RULES rule zero: pass — URLs fetched.
- Timebox: kept to 4h (extended budget for this critical step).

## Stop-and-report

Report DISCOVERY-NOTES.md content summary, THRESHOLDS-LOCKED.md numeric decisions with sources, key finding on reputation-scope question. **Awaiting your "proceed" for Step 2.**
