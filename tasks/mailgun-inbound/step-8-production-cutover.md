# Step 8 — Production cutover (`reply.neuradigi.com` DNS + prod verify + runbook + rotation drill)

**Status:** PARTIAL — 2026-09-02. Operator runbook shipped (`mailgun-setup-runbook.md`) with first-time setup, key rotation, DLQ inspection, "no inbounds are landing" checklist, emergency disable, common failures, and custom-domain follow-up notes. **Blocked-on-user:** (a) verify Step 7 sandbox smoke first; (b) add `reply.neuradigi.com` in Mailgun dashboard; (c) publish DNS records at `neuradigi.com` registrar; (d) wait for green verification; (e) ping me to flip prod env + re-run route script.
**Effort:** ~0.25 day active + DNS propagation wait (~15 min to few hours).
**Depends on:** Step 7 (sandbox smoke passed).
**Blocks:** Nothing.

## Goal

Move from Mailgun sandbox to the production `reply.neuradigi.com` receiving domain. Zero code change; only env vars and Mailgun-dashboard config.

Ship the runbook so the operator can do rotation, key recovery, and DLQ inspection without asking.

## Prerequisites (you do)

1. **Add domain in Mailgun dashboard** → Sending → Domains → Add New Domain → `reply.neuradigi.com`, US region.
2. **Get the DNS records Mailgun requires** — typically:
   - **MX**: `10 mxa.mailgun.org` + `10 mxb.mailgun.org`
   - **TXT (SPF)**: `v=spf1 include:mailgun.org ~all`
   - **TXT (DKIM)**: long DKIM public key value from Mailgun
   - **TXT (DMARC, optional but recommended)**: `v=DMARC1; p=none; rua=mailto:dmarc@neuradigi.com`
3. **Add records at your DNS registrar** for `neuradigi.com` — subdomain `reply`.
4. **Wait for Mailgun verification** — Mailgun's dashboard shows green checks per record. Can take 15 min to several hours depending on DNS provider TTL.
5. **Ping me when verified** so I flip env + re-run route setup.

## Scope (I do)

**Env flip:**

- `config.env` (prod):
  - `MAILGUN_DOMAIN=reply.neuradigi.com`
  - `INBOUND_EMAIL_DOMAIN=reply.neuradigi.com`
  - `MAILGUN_WEBHOOK_URL=https://crm-api.neuradigi.com/api/v1/webhooks/mailgun/inbound`
- Restart the API + Celery workers to pick up the new env.

**Re-run route setup against prod:**

- `API\run.cmd exec python -m src.app.scripts.mailgun_route_setup` — the script's prod-domain safeguard will prompt for `CONFIRM` since we're mutating `reply.neuradigi.com`.

**Backfill outbound Reply-To for existing SMTP-sender messages:**

- Not needed — Reply-To is generated at send time from the current `INBOUND_EMAIL_DOMAIN`. Existing outbound messages already sent with sandbox addresses will bounce; new sends use `reply.neuradigi.com`. No migration.

**Prod smoke:**

- Send a test SMTP email in production. Verify `Reply-To: in_<token>@reply.neuradigi.com` on the outbound.
- Reply from Gmail. Verify CRM ingest.
- Send with attachment. Verify.

**Signing-key rotation drill:**

- Practice the rotation in prod during a low-traffic window:
  1. Generate a NEW signing key in Mailgun dashboard (creates the key; both current + new are valid).
  2. Move current key value → `MAILGUN_SIGNING_KEY_PREVIOUS` in SOPS.
  3. Put new key value → `MAILGUN_SIGNING_KEY`.
  4. Restart API + workers.
  5. Verify: signed with new key → 200. Signed with old key → still 200 (fallback). Signed with random → 401.
  6. Delete the old key in Mailgun dashboard.
  7. Clear `MAILGUN_SIGNING_KEY_PREVIOUS` in SOPS.
  8. Restart.
- Document the exact steps in the runbook.

**Runbook** — `tasks/mailgun-inbound/mailgun-setup-runbook.md`:

```markdown
# Mailgun Inbound — Operator Runbook

## First-time production setup
[full steps 1–5 above]

## Signing-key rotation
[drill steps above]

## DLQ inspection
`GET /api/v1/admin/email-inbound-dlq?limit=50` (Owner-only).
Reprocess: `POST /api/v1/admin/email-inbound-dlq/{id}/reprocess`.

## "No inbounds are landing" checklist
1. Check Mailgun dashboard → Logs → is Mailgun receiving?
2. If yes but not forwarding → check Route configuration.
3. If forwarding but 401 → check MAILGUN_SIGNING_KEY vs Mailgun's Webhooks page.
4. If 200 but no message in CRM → check Celery workers running, check DLQ.
5. If DLQ empty and messages missing → check `./storage/pending-inbound/` for stuck payloads; check pending-inbound sweeper.

## Emergency disable
Set `INBOUND_EMAIL_DOMAIN=` (empty) — Reply-To injection short-circuits, replies stop being captured. Existing outbound already in the wild will bounce silently.

## Common failures
- **All webhooks 401 after key rotation**: verify `MAILGUN_SIGNING_KEY_PREVIOUS` is populated with old key value during rotation window.
- **Sandbox test emails fail with 550**: recipient not in Mailgun sandbox's Authorized Recipients list.
- **DKIM record too long for DNS registrar**: split into multiple 255-char strings within one TXT record (registrar-specific syntax).
```

## Files touched

- `config.env` (prod deploy)
- `tasks/mailgun-inbound/mailgun-setup-runbook.md` (new)

## Tests

None new. Reuse Step 7's smoke.

## Self-check

- [ ] All DNS records verified in Mailgun dashboard (green checks).
- [ ] `MAILGUN_DOMAIN` = `reply.neuradigi.com` in prod config.
- [ ] Route re-created against prod domain (script confirmed).
- [ ] Prod smoke passed end-to-end.
- [ ] Rotation drill executed successfully once, documented.
- [ ] Runbook covers rotation, DLQ, disable, common failures.

## Report template

```
DNS records added and verified for reply.neuradigi.com:
  - MX ×2: green
  - SPF: green
  - DKIM: green
  - DMARC (optional): green

Env flipped in prod: MAILGUN_DOMAIN + INBOUND_EMAIL_DOMAIN + MAILGUN_WEBHOOK_URL.
Route re-created via script (prod-domain safeguard prompted, confirmed).

Prod smoke: PASS end-to-end (outbound Reply-To, inbound ingest, attachment round-trip).

Signing-key rotation drill: PASS (fallback verified).

Runbook committed at tasks/mailgun-inbound/mailgun-setup-runbook.md.

Track COMPLETE. Follow-ups tracked in README.md "Open items".
```
