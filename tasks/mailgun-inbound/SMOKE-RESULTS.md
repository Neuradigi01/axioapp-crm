# Mailgun Inbound — Sandbox Smoke Results

**Status:** PENDING — awaiting Mailgun API key + signing key in SOPS.

**Environment**
- Sandbox domain: `sandbox3f4add564a974bc6a2c07ebf6d1fad9a.mailgun.org`
- Webhook URL: `https://crm-api.neuradigi.com/api/v1/webhooks/mailgun/inbound`
- Target org: Ajay's Workspace (`41f9ede9-41b3-44ce-b489-3004566d4068`)
- Route id: _(populated after `mailgun_route_setup.py` run)_

---

## Prerequisites (operator)

- [ ] `MAILGUN_API_KEY` set via `run.cmd secrets-edit`
- [ ] `MAILGUN_SIGNING_KEY` set via `run.cmd secrets-edit`
- [ ] `MAILGUN_SIGNING_KEY_PREVIOUS` empty (rotation-drill only)
- [ ] `run.cmd restart` — new secrets loaded into API + Celery containers
- [ ] Route created — `python -m src.app.scripts.mailgun_route_setup` succeeded
- [ ] Authorized recipients added in Mailgun dashboard (Send → Domain settings): at least the tester's own Gmail and 1 secondary address so sandbox outbound can reach them

---

## 10-item smoke checklist

Each row: PASS / FAIL + a one-line piece of evidence (Mailgun log id, CRM message id, screenshot filename, or exact error).

### 1. Outbound `Reply-To` header lands on SMTP-sent mail

**Setup:** In the CRM, compose a test email from a verified SMTP sender (Settings → Integrations → Email Sender) to your Gmail.
**Assert:** In Gmail → "Show original", header block contains
`Reply-To: in_<12-char>@sandbox3f4add564a974bc6a2c07ebf6d1fad9a.mailgun.org`.

- Result: __
- Evidence: __

---

### 2. Reply from Gmail lands as inbound in the correct conversation

**Setup:** Hit Reply in Gmail, type "smoke test 2", send.
**Assert:**
- Mailgun dashboard (Sending → Logs) shows a `stored` or `accepted` event with the same subject.
- API server logs show `POST /api/v1/webhooks/mailgun/inbound 200 OK`.
- Celery worker logs show `process_mailgun_inbound` task run.
- CRM inbox (Conversations page) shows the reply in the same conversation as the outbound from step 1.
- Database: `SELECT id, spf_result, dkim_result, channel_message_id FROM tbl_messages ORDER BY sent_at DESC LIMIT 1` — non-null `spf_result` + `channel_message_id LIKE 'mg:%'`.

- Result: __
- Evidence: Mailgun log id __ · CRM message id __

---

### 3. Attachment round-trip (PDF)

**Setup:** In Gmail reply, attach a small PDF (< 1 MB), send.
**Assert:**
- Reply appears in CRM inbox with an "N attachment(s)" indicator + a downloadable pill showing the filename + size.
- Click the download link: browser downloads the file (does NOT render inline).
- Devtools → Response Headers show `Content-Disposition: attachment` (not `inline`).
- File on disk: `./storage/<org_id>/messages/<msg_id>/<filename>` exists in the API container.

- Result: __
- Evidence: __

---

### 4. Spoofed sender + SPF fail → auto-attribution dropped

**Setup:** Send a signed POST via curl with `From: "CEO" <ceo@bigco.com>` and `X-Mailgun-Spf: fail`, where a contact with email `ceo@bigco.com` exists in the target org.

```bash
TOKEN=$(python -c "import time; print(int(time.time()))")_$(openssl rand -hex 8)
TS=$(echo "$TOKEN" | cut -d_ -f1)
TOK=$(echo "$TOKEN" | cut -d_ -f2)
SIG=$(echo -n "${TS}${TOK}" | openssl dgst -sha256 -hmac "$MAILGUN_SIGNING_KEY" | awk '{print $2}')
curl -X POST https://crm-api.neuradigi.com/api/v1/webhooks/mailgun/inbound \
  -F "timestamp=$TS" -F "token=$TOK" -F "signature=$SIG" \
  -F "recipient=in_<VALID_TOKEN>@sandbox3f4add564a974bc6a2c07ebf6d1fad9a.mailgun.org" \
  -F "sender=attacker@bad.example" \
  -F "From=\"CEO\" <ceo@bigco.com>" \
  -F "Subject=URGENT WIRE" \
  -F "Message-Id=<spoof-$(date +%s)@bad.example>" \
  -F "body-plain=Send $50k" \
  -F "X-Mailgun-Spf=fail" \
  -F "X-Mailgun-Dkim-Signature=fail"
```

**Assert:**
- Response 200.
- `SELECT payload->>'spoof_suspected', spf_result, dkim_result FROM tbl_messages ORDER BY sent_at DESC LIMIT 1`  → `true, fail, fail`.
- The persisted `Message.conversation_id`'s conversation has `contact_id != <CEO contact id>` (usually NULL).
- No `email.replied` workflow event fired (check `tbl_audit_log` for `mailgun.inbound.sender_auth_failed`).

- Result: __
- Evidence: __

---

### 5. Replay drop within 10-min window

**Setup:** Repeat the exact same curl command from #4 (same TS, same TOK, same SIG) within 10 minutes.
**Assert:** Response 401 with `{"error": "replay"}`. Only one message persisted (from the first call).

- Result: __
- Evidence: __

---

### 6. Auto-responder header → workflow event suppressed

**Setup:** Signed POST like #4 but with `Auto-Submitted: auto-replied`, `X-Mailgun-Spf: pass`, non-spoofed From.
**Assert:**
- Message persists with `payload->>'auto_generated' = 'true'`.
- No `email.replied` / `email.message_received` workflow event published.

- Result: __
- Evidence: __

---

### 7. Redis outage during signature/replay → fail-CLOSED

**Setup:** `docker compose stop redis`. Send a signed POST.
**Assert:** Response 401 with `{"error": "replay"}` (fail-CLOSED path). Restart Redis: `docker compose start redis`. Send again with a new (TS, TOK). Response 200 + message persists.

- Result: __
- Evidence: __

---

### 8. Broker down at delivery time → sweeper re-enqueues

**Setup:** `docker compose stop celery`. Send a signed POST.
**Assert:**
- Response 200 (broker down doesn't fail the webhook).
- `./storage/pending-inbound/<uuid>/payload.json` exists on disk.
- Restart Celery: `docker compose start celery`. Wait 5–6 min for the sweeper beat.
- Message persists in `tbl_messages`; pending-inbound dir removed.

- Result: __
- Evidence: __

---

### 9. Exhausted-retry ingest → DLQ row

**Setup:** Break the ingest deliberately by sending a payload with no `Message-Id` header (which the task treats as a DLQ path). Signed correctly, but the ingest can't proceed.
**Assert:**
- `GET /api/v1/admin/email-inbound-dlq` (as Owner) returns a row.
- Row's `error_reason == "missing_mailgun_delivery_id"`.
- Admin (non-Owner) role → 403 on the same endpoint.

- Result: __
- Evidence: __

---

### 10. Orphan sweeper cleans stale staging dir

**Setup:** In the API container, `mkdir -p ./storage/<org_id>/staging/$(uuidgen)` and `touch -d '2 hours ago' ./storage/<org_id>/staging/<uuid>`. Trigger the sweeper manually: `docker compose exec celery celery -A src.celery.worker call src.app.core.email.mailgun.orphan_cleanup.sweep_staging_orphans`.
**Assert:** The dir is gone.

- Result: __
- Evidence: __

---

## Post-smoke wrap-up

- [ ] All 10 items PASS
- [ ] Signing-key rotation drill documented in `mailgun-setup-runbook.md` (Step 8)
- [ ] Ready to add `reply.neuradigi.com` in Mailgun → Domains → Add new domain (Step 8)
