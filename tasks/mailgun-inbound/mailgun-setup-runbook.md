# Mailgun Inbound — Operator Runbook

Reference for anyone operating the SMTP reply-capture pipeline.
Not a design doc — the design lives in [`README.md`](README.md).
This is *"how do I fix / rotate / debug the thing in prod"*.

Scope: the Mailgun inbound-only integration for SMTP senders. Gmail
and Microsoft OAuth mailboxes are handled by their own sync — nothing
in this file touches them.

---

## 1. First-time production setup

Sandbox (Steps 0–7) is assumed already live. This section walks the
promotion to `reply.neuradigi.com`.

### 1.1 Add the production domain in Mailgun

1. Log in at [https://app.mailgun.com](https://app.mailgun.com).
2. **Send → Domains → Add new domain**.
3. Domain: `reply.neuradigi.com`. Region: **US** (must match sandbox).
4. On the confirmation page, Mailgun lists the DNS records to publish.
   Keep this page open — we'll copy from it next.

### 1.2 Publish DNS records at the `neuradigi.com` registrar

Add records for **subdomain `reply`** — typically:

| Type  | Name             | Value                                              |
|-------|------------------|----------------------------------------------------|
| MX    | reply            | `10 mxa.mailgun.org`                               |
| MX    | reply            | `10 mxb.mailgun.org`                               |
| TXT   | reply            | `v=spf1 include:mailgun.org ~all`                  |
| TXT   | `smtp._domainkey.reply` | (long DKIM public key — Mailgun-supplied)   |
| TXT   | `_dmarc.reply`   | `v=DMARC1; p=none; rua=mailto:dmarc@neuradigi.com` (recommended, not required) |

**Copy the exact values from Mailgun's dashboard, not this table.**
Mailgun may rotate its DKIM key format; only their live page is
authoritative.

**Common registrar gotcha:** the DKIM TXT value is often longer than
255 characters. Some registrars require splitting into multiple
255-char strings inside the same TXT record — usually done by wrapping
each 255-char chunk in double quotes and concatenating (registrar
UI varies). If Mailgun still shows the DKIM as red after propagation,
this is almost always the reason.

### 1.3 Wait for Mailgun verification

- Click **Verify DNS settings** in the Mailgun dashboard.
- Propagation is 15 min – a few hours depending on registrar TTL.
- Rows flip from red ✗ to green ✓ as records go live.
- **All 4 must be green (DMARC optional) before proceeding.**

### 1.4 Flip production env vars

In `API/config.env` (or however prod env is delivered on your deploy):

```
MAILGUN_DOMAIN=reply.neuradigi.com
INBOUND_EMAIL_DOMAIN=reply.neuradigi.com
MAILGUN_WEBHOOK_URL=https://crm-api.neuradigi.com/api/v1/webhooks/mailgun/inbound
```

Restart the API + Celery containers so the new env is loaded:

```
run.cmd restart
```

Confirm in a container:

```
docker compose exec api sh -c 'echo $MAILGUN_DOMAIN; echo $INBOUND_EMAIL_DOMAIN'
```

Both should print `reply.neuradigi.com`.

### 1.5 Re-run the route setup script against prod

```
run.cmd shell api
python -m src.app.scripts.mailgun_route_setup
```

The script's **prod-domain safeguard** prompts:

```
[mailgun-route-setup] SAFEGUARD: about to mutate route on
prod-looking domain 'reply.neuradigi.com' from env '<env_name>'.
[mailgun-route-setup] Type CONFIRM (uppercase) to proceed, anything
else to abort.
```

Type `CONFIRM` (uppercase, exact). Expected output:

```
[mailgun-route-setup] Route created: id=6...
```

**If the sandbox route is still present**, that's fine — routes are
matched by expression, so the prod route just adds another (different
recipient pattern). To remove the old sandbox route, delete it in the
Mailgun dashboard (Send → Receiving → Routes).

### 1.6 Prod smoke (short version)

- In the CRM, send a test email through a verified SMTP sender.
- Confirm `Reply-To: in_<token>@reply.neuradigi.com` in the outbound
  headers (Gmail → Show original).
- Reply from Gmail. Watch API server logs for
  `POST /api/v1/webhooks/mailgun/inbound 200 OK`.
- Confirm the reply appears in the same CRM conversation.

Full 10-item smoke is documented in
[`SMOKE-RESULTS.md`](SMOKE-RESULTS.md).

---

## 2. Signing-key rotation

Mailgun signing keys don't expire, but rotate them at least yearly or
immediately on suspected compromise. Zero-inbound-loss cutover.

### 2.1 Generate a new signing key

Mailgun dashboard → **Send → Webhooks → HTTP webhook signing key →
Reset**. Copy the NEW value. The OLD key is still valid until you
delete it.

### 2.2 Promote current → previous, install new current

```
run.cmd secrets-edit
```

Update:

```
MAILGUN_SIGNING_KEY=<the NEW value>
MAILGUN_SIGNING_KEY_PREVIOUS=<the OLD value>
```

Save (SOPS auto-re-encrypts), then:

```
run.cmd restart
```

### 2.3 Verify both keys work

- Signed with NEW key → 200.
- Signed with OLD key → 200 (fallback works).
- Random signature → 401.

You can trigger a real inbound during this window (send a reply from
Gmail); if it lands, rotation is working.

### 2.4 Retire the old key

After ~10 min (long enough that any in-flight Mailgun retry has drained):

- Mailgun dashboard: nothing to do — Mailgun uses whatever key is
  active on the account. Once you saved the new key at step 2.1, the
  old key is already invalidated on Mailgun's side. The fallback in
  our code is defense-in-depth for in-flight deliveries only.
- Clear `MAILGUN_SIGNING_KEY_PREVIOUS` in SOPS:

```
run.cmd secrets-edit
# Set: MAILGUN_SIGNING_KEY_PREVIOUS=
run.cmd restart
```

Rotation complete.

---

## 3. DLQ inspection + reprocess

The DLQ (dead-letter queue) holds Mailgun deliveries whose ingest
Celery task exhausted its retry budget. Owner-only.

### 3.1 List DLQ rows

```
GET /api/v1/admin/email-inbound-dlq?limit=50
Authorization: Bearer <owner-jwt>
```

Response is an array of:

```json
{
  "id": "…",
  "org_id": "…" | null,
  "mailgun_delivery_id": "…" | null,
  "error_reason": "worker_exhausted" | "missing_mailgun_delivery_id" | "payload_json_parse_error",
  "retry_count": 0,
  "created_at": "…",
  "resolved_at": null | "…"
}
```

`pending_inbound_path` and `error_details` are deliberately NOT in the
response — the on-disk path is a server-side detail and `error_details`
can contain PII from spoofed inbound. Fetch them via a DB query if you
need forensic detail:

```sql
SELECT * FROM tbl_email_inbound_dlq WHERE id = '…';
```

### 3.2 Reprocess a DLQ row

```
POST /api/v1/admin/email-inbound-dlq/{id}/reprocess
Authorization: Bearer <owner-jwt>
```

Response:

```json
{"id": "…", "reprocessed": true}
```

The row's `resolved_at` is stamped on kickoff. A subsequent successful
ingest doesn't retroactively un-resolve; a subsequent failure writes
a fresh DLQ row.

**410 Gone** on reprocess means the pending-inbound directory was
already cleaned up (typically because a sweeper or manual `rm -rf` ran
against it). No recovery — the payload is gone.

**403 Forbidden** on system-level DLQ rows (`org_id IS NULL`) — these
represent unknown-recipient or malformed-payload failures where no
tenant was resolved. They're visible in the list but can't be
reprocessed via the tenant admin path; a platform admin needs to
handle them via direct DB + queue access.

---

## 4. "No inbounds are landing" checklist

Walk this top-to-bottom when a customer reports "I replied to a CRM
email and it disappeared."

1. **Mailgun receiving?** Dashboard → Send → Logs. Filter to the last
   1 hour. Any `stored` / `accepted` events? If NO → Mailgun didn't
   receive the mail (customer's Reply may have gone somewhere else,
   or DNS reverted). If YES → continue.

2. **Route configured?** Dashboard → Send → Receiving → Routes.
   Confirm one route exists with expression
   `match_recipient(".*@reply.neuradigi.com")` and action containing
   `forward("https://crm-api.neuradigi.com/api/v1/webhooks/mailgun/inbound")`.
   If missing → run `python -m src.app.scripts.mailgun_route_setup`.

3. **Webhook receiving?** API server logs from the same window. Search
   for `POST /api/v1/webhooks/mailgun/inbound`. Response codes:
   - **200** → webhook OK, continue to step 4.
   - **401** → signature mismatch (usually `MAILGUN_SIGNING_KEY`
     stale after a rotation). Compare env to Mailgun dashboard.
   - **500** → disk full or Redis outage. Check container health.
   - **No log entries at all** → route's forward URL is wrong, or
     Mailgun can't reach us (firewall / DNS at our end).

4. **Celery worker running?** `docker compose ps` — is the `celery`
   container Up? Any recent restarts? Check `docker compose logs
   celery --tail 100` for exceptions from `process_mailgun_inbound`.

5. **DLQ populated?** `GET /api/v1/admin/email-inbound-dlq` — recent
   rows? A `worker_exhausted` reason means the task retried 3× and
   gave up. `missing_mailgun_delivery_id` means Mailgun's payload was
   missing the Message-Id field (rare — usually indicates malformed
   test traffic).

6. **Pending-inbound stuck on disk?** `docker compose exec api ls
   ./storage/pending-inbound/`. Directories older than 5 min mean the
   sweeper isn't running or the broker is down. Check `celery-beat`
   container health.

7. **Message actually persisted but not shown in inbox?** Check the
   DB directly:
   ```sql
   SELECT id, direction, spf_result, dkim_result, payload
   FROM tbl_messages
   WHERE payload->>'provider' = 'mailgun'
   ORDER BY sent_at DESC LIMIT 20;
   ```
   If rows exist but with `contact_id=NULL`, the sender email didn't
   match any contact in that org — check the conversation list for
   "Needs review" or unassigned conversations.

---

## 5. Emergency disable

If Mailgun inbound is broadly broken or being abused (unlikely at v1
scale, but the exit exists):

### 5.1 Stop Reply-To rewriting (surgical — new outbound only)

```
run.cmd secrets-edit
# Set: INBOUND_EMAIL_DOMAIN=
```

Or in `config.env` — same effect. Save + `run.cmd restart`.

**Effect:** new outbound from SMTP senders won't get a Reply-To header
rewritten to `in_<token>@…`. Customers replying to already-sent mail
still see the old Reply-To and their replies still land at Mailgun —
those will be dropped or DLQ'd depending on what else you disable.

### 5.2 Stop accepting inbound entirely (nuclear)

Two options:

a) **Delete the route in Mailgun dashboard** (Send → Receiving →
   Routes). Mailgun accepts the mail but has no forward target and
   eventually bounces to the sender. Reversible: re-run the route
   setup script.

b) **Return 4xx from the webhook.** Comment out the router
   registration in `main.py`:

```python
# app.include_router(mailgun_inbound_router, prefix="/api/v1/webhooks")
```

Redeploy. Mailgun retries for ~8 hours then dead-letters. Reversible:
uncomment + redeploy.

**Do not use (b) as the routine "pause" switch** — Mailgun's retry
storm during the outage window can rack up a lot of DLQ noise.

---

## 6. Common failures

### "All webhooks 401 after key rotation"

Check `MAILGUN_SIGNING_KEY_PREVIOUS` is populated with the OLD key
value during the rotation window (see §2). Restart if needed.

### "Sandbox test emails fail with 550: Recipient not on authorized list"

Sandbox domains cap **outbound** to a whitelist of ~5 addresses added
in **Send → Domain settings → Authorized Recipients**. Add the
recipient (any Gmail / test address) and retry. Inbound is unlimited
on sandbox.

### "DKIM record shows red in Mailgun even after propagation"

- DKIM TXT value is often > 255 chars. Split into multiple 255-char
  strings, all inside the same TXT record (registrar-specific syntax
  — some use quoted concatenation, others provide a UI toggle).
- Wait 1–2 hours. DNS caches at Mailgun's resolvers can lag.
- Confirm you added `smtp._domainkey.reply` (with the `.reply` suffix)
  and not `smtp._domainkey` at the apex.

### "Emails send but Reply-To is a Gmail address, not Mailgun"

The sender's `capture_replies_in_crm` toggle is OFF. Owner can flip
it back on in Settings → Integrations → Email Sender → the sender row
→ "Capture replies in CRM" toggle.

### "One org's inbound suddenly stops but others still work"

Their SMTP sender was likely deleted or the token rotated. Check:

```sql
SELECT id, from_address, inbound_token, capture_replies_in_crm,
       verified_at
FROM tbl_email_smtp_senders
WHERE org_id = '<their-org-id>';
```

If the row is gone, the token → sender lookup misses → replies land
as `unknown_recipient` audit events at the system level. Rebuilding
the sender generates a new token — replies to their PREVIOUSLY-sent
mail continue to hit the old token and fail (no way around this;
mail already in the wild carries the old address).

### "Same customer keeps getting a mail loop after replying"

Their mail server is sending an auto-response that lacks the
`Auto-Submitted` / `Precedence: bulk` headers our detector reads (see
[`service.py` `detect_auto_responder`](../../API/src/app/core/email/mailgun/service.py)).
Options: add the specific header their server uses to the detector's
allowlist (code change); or disable the specific workflow that's
auto-replying.

---

## 7. Custom customer domains (future work — NOT in v1)

The current design uses a single central domain (`reply.neuradigi.com`)
for every CRM tenant. A future v2 feature would let each customer add
their own `reply.customer.com`. That involves:

- Per-org Mailgun domain (Mailgun charges per additional domain past
  the free tier).
- Per-org DNS-verification state machine (customer adds MX/SPF/DKIM
  at their registrar; we poll Mailgun until green).
- Per-org receiving-domain column on `tbl_organizations` or a new
  `tbl_email_receiving_domains` table.
- Route-setup script extended to create one route per domain.
- The existing `INBOUND_EMAIL_DOMAIN` env var stays as the default
  (fallback for orgs that haven't added a custom domain).

None of the current schema locks us out — the token is stored per
sender, and the sender-detail response is already prepared to expose
a per-sender `inbound_reply_address`. Adding custom domains is
additive.

---

## 8. Off-runbook fixes: audit everything

Any change you make outside this runbook (deleting a DLQ row by hand,
`rm -rf`'ing a pending-inbound dir, manually editing
`tbl_email_smtp_senders.inbound_token`, etc.) — write a note in
[`SMOKE-RESULTS.md`](SMOKE-RESULTS.md) or a fresh ops log so the next
operator sees what happened. The audit log (`tbl_audit_logs`) captures
API-mediated changes only; direct DB or filesystem edits are
invisible without your note.
