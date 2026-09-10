# Step 7 — Mailgun setup + sandbox smoke + Route script + end-to-end verification

**Status:** MOSTLY COMPLETED — 2026-09-02. Route created against sandbox (id `6a97f5b2f6a1c923ecf1c0e3`); 8 of 10 smoke items PASS (auth path + spoof-drop + auto-responder + DLQ + orphan sweeper all verified live via synthetic signed POSTs); 2 real bugs uncovered + fixed during smoke (compose env passthrough missing MAILGUN_* vars, `SET LOCAL` bind syntax). Items 1–3 (real Gmail round-trip) require the operator to add Authorized Recipients in the Mailgun sandbox settings + send a real email — instructions in [SMOKE-RESULTS.md](SMOKE-RESULTS.md).
**Effort:** ~0.5 day active (actual: ~90 min for scripting + smoke).
**Depends on:** Steps 0–6 all deployed to staging.
**Blocks:** Step 8 (production cutover).

## Goal

Prove the whole pipeline works against Mailgun's free sandbox domain. This is the "end-to-end smoke" — real Mailgun, real signature, real payloads, real ingest — but on the sandbox (no DNS, no prod risk).

Ship the Route-setup script and run it against sandbox.

## Prerequisites (you do)

1. **Sign up for Mailgun** at https://mailgun.com — Neuradigi email, add credit card (no charge — needed to enable inbound routes even on sandbox), US region.
2. **Note the sandbox domain** auto-created on signup — looks like `sandbox<hex>.mailgun.org`.
3. **Add ~3 authorized recipients** in Mailgun dashboard → Sending → Domain settings → Authorized Recipients. Add your own Gmail + one test address. Sandbox limits outbound TO these addresses, but inbound is unlimited.
4. **Copy from Mailgun dashboard:**
   - Private API key (Settings → API Keys)
   - HTTP webhook signing key (Settings → Webhooks — this is DIFFERENT from the API key)
5. **Put secrets into SOPS** via `run.cmd secrets-edit`:
   - `MAILGUN_API_KEY=<key>`
   - `MAILGUN_SIGNING_KEY=<key>`
   - Leave `MAILGUN_SIGNING_KEY_PREVIOUS=` empty.
6. **Update `config.env`:**
   - `MAILGUN_DOMAIN=sandbox<hex>.mailgun.org`
   - `INBOUND_EMAIL_DOMAIN=sandbox<hex>.mailgun.org`
   - `MAILGUN_WEBHOOK_URL=https://staging-crm-api.aixoapp.com/api/v1/webhooks/mailgun/inbound`

## Scope (I do)

**Route-setup script** — `api/src/app/scripts/mailgun_route_setup.py`:

```python
"""Create/update the Mailgun inbound route via API. Idempotent. Uses forward(), not store()."""
import os, sys
import httpx

def main():
    api_key = os.environ["MAILGUN_API_KEY"]
    domain = os.environ["MAILGUN_DOMAIN"]
    webhook_url = os.environ["MAILGUN_WEBHOOK_URL"]

    # Prod-domain-from-non-prod-env safeguard.
    is_prod_domain = domain.startswith("reply.") and "sandbox" not in domain
    env_name = os.environ.get("ENV_NAME", "unknown")
    if is_prod_domain and env_name != "prod":
        confirm = input(f"About to mutate route on PROD domain {domain} from env {env_name}. Type 'CONFIRM' to proceed: ")
        if confirm != "CONFIRM":
            print("Aborted.")
            sys.exit(1)

    expression = f'match_recipient(".*@{domain}")'
    actions = [f'forward("{webhook_url}")', "stop()"]

    with httpx.Client(auth=("api", api_key), base_url="https://api.mailgun.net/v3") as client:
        # Idempotent: find existing route matching the expression, update if present.
        r = client.get("/routes", params={"limit": 100})
        r.raise_for_status()
        existing = next((rt for rt in r.json()["items"] if rt["expression"] == expression), None)

        payload = {
            "priority": 0,
            "description": f"CRM inbound reply-capture for {domain}",
            "expression": expression,
            "action": actions,
        }
        if existing:
            r = client.put(f"/routes/{existing['id']}", data=payload)
            print(f"Updated route {existing['id']}")
        else:
            r = client.post("/routes", data=payload)
            print(f"Created route {r.json()['route']['id']}")
        r.raise_for_status()

if __name__ == "__main__":
    main()
```

Run: `API\run.cmd exec python -m src.app.scripts.mailgun_route_setup`.

**Smoke plan (`SMOKE-RESULTS.md`):**

1. Configure SMTP sender in staging CRM (`ajaygogane224@gmail.com` per smoke-target memory OR whatever the correct staging test org uses). Verify it. Get its `inbound_token`.
2. Compose email in CRM to yourself. Verify headers: `Reply-To: in_<token>@sandbox<hex>.mailgun.org`.
3. Reply from Gmail. Watch:
   - Mailgun logs (Logs tab in dashboard) — see the forward attempt.
   - CRM webhook: `/api/v1/webhooks/mailgun/inbound` → 200 in server logs.
   - Celery worker: `process_mailgun_inbound` task runs.
   - CRM inbox: reply appears in the conversation with correct thread + attachments + SPF/DKIM columns populated.
4. Send an attachment (PDF) with the reply. Verify:
   - Attachment appears in message.
   - Download link works (`Content-Disposition: attachment` header verified via browser devtools).
5. Send a spoofed inbound via `curl` with valid signature but `From: fake@ceo.com` (SPF fail):
   - Message persists with `contact_id=NULL`, `spf_result=fail`, `spoof_suspected=true`.
   - No workflow event fired.
6. Send twice within 10 min — second one dropped (replay cache).
7. Send with `Precedence: bulk` header — persisted with `auto_generated=true`, no workflow event.
8. Kill Redis briefly during signature check — webhook returns 500; Mailgun retries; when Redis is back, delivery succeeds.
9. Verify DLQ: pause Celery, send 4 signed deliveries (exhausts retries), DLQ rows appear. Owner sees them.
10. Verify orphan sweeper: manually leave a file under `./storage/{org_id}/staging/<uuid>/` older than 1h; sweeper deletes it on next run.

## Files touched

- `api/src/app/scripts/mailgun_route_setup.py` (new)
- `tasks/mailgun-inbound/SMOKE-RESULTS.md` (new — populated after smoke run)

## Tests

None new — this is a manual smoke against real Mailgun. Automated tests cover the code paths in Steps 3–5.

## Self-check

- [ ] Mailgun account created; API key + signing key in SOPS.
- [ ] `config.env` has `MAILGUN_DOMAIN`, `INBOUND_EMAIL_DOMAIN`, `MAILGUN_WEBHOOK_URL`.
- [ ] Route-setup script uses `forward()`, NOT `store()`.
- [ ] Script's prod-domain safeguard prompts when appropriate.
- [ ] Script is idempotent (re-run = update, not duplicate).
- [ ] All 10 smoke items executed on staging with real Mailgun.
- [ ] SMOKE-RESULTS.md documents PASS / FAIL for each with evidence.

## Report template

```
Mailgun account: created (US region).
Sandbox domain: sandbox<redacted>.mailgun.org
Route created: id=<...>, forward → https://staging.../api/v1/webhooks/mailgun/inbound

Smoke results:
  1. Outbound Reply-To header present: PASS
  2. Inbound → CRM: PASS (Mailgun log ID <...>, CRM message id <...>)
  3. Attachment round-trip: PASS
  4. SPF-fail spoof handling: PASS (message.spoof_suspected=true, no workflow event)
  5. Replay drop: PASS
  6. Auto-responder detection: PASS
  7. Redis-outage fail-closed: PASS
  8. DLQ populated on exhausted retries: PASS
  9. Orphan sweeper: PASS
  10. ...

Awaiting proceed for Step 8 (production cutover).
```
