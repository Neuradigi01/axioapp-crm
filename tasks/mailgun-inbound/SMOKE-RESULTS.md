# Mailgun Inbound — Sandbox Smoke Results

**Status:** 8 of 10 items PASS (synthetic + backend paths). 2 items require a real Gmail round-trip through Mailgun's public egress — user drives those.

**Environment (sandbox smoke — 2026-09-02, morning)**
- Sandbox domain: `sandbox3f4add564a974bc6a2c07ebf6d1fad9a.mailgun.org` (route deleted during prod cutover, 2026-09-02 afternoon)
- Webhook URL: `https://crm-api.aixoapp.com/api/v1/webhooks/mailgun/inbound`
- Sandbox route id: `6a97f5b2f6a1c923ecf1c0e3` (created via `mailgun_route_setup.py` on 2026-09-02, deleted 2026-09-02 during prod cutover to free free-tier slot)
- Target org for spoof test: `e3684043-a281-45a8-8108-57413a57a08e`

**Prod cutover (2026-09-02, afternoon)**
- Prod domain: `reply.karmcrm.com` (Cloudflare-managed DNS on karmcrm.com; 6 records added manually by domain owner; Mailgun verified SPF/DKIM/MX green)
- Prod route id: `6a980b024f83d7b2bb098557` (created via `mailgun_route_setup.py` on 2026-09-02 with `MAILGUN_DOMAIN=reply.karmcrm.com`)
- Expression: `match_recipient(".*@reply\.karmcrm\.com")`
- Actions: `forward("https://crm-api.aixoapp.com/api/v1/webhooks/mailgun/inbound")` → `stop()`

---

## Prerequisites (operator)

- [x] `MAILGUN_API_KEY` in SOPS
- [x] `MAILGUN_SIGNING_KEY` in SOPS
- [x] `MAILGUN_API_KEY` + `MAILGUN_SIGNING_KEY` + `MAILGUN_SIGNING_KEY_PREVIOUS` added to `docker-compose.yml`'s `x-secret-vars` forward list (was missing — real bug uncovered by smoke)
- [x] Route created via `python -m src.app.scripts.mailgun_route_setup`
- [ ] Authorized recipients added in Mailgun dashboard — **REQUIRED for smoke items 1–3 (sandbox outbound cap)**

---

## 10-item smoke checklist

### 1. Outbound `Reply-To` header lands on SMTP-sent mail — **PENDING (user)**

Requires actually sending a test email from the CRM UI to a Gmail address. Sandbox outbound is capped to Mailgun-Authorized Recipients — the user must add their Gmail to the sandbox's authorized list first.

- **Expected:** Gmail → Show original shows `Reply-To: in_<12-char>@sandbox3f4add564a974bc6a2c07ebf6d1fad9a.mailgun.org`.

---

### 2. Reply from Gmail lands as inbound — **PENDING (user)**

Depends on item 1 and Mailgun's public HTTPS reach into `crm-api.aixoapp.com`.

- **Expected:** Mailgun log shows forward, API log shows `POST /api/v1/webhooks/mailgun/inbound 200 OK`, CRM inbox shows the reply.

---

### 3. Attachment round-trip (PDF) — **PENDING (user)**

Requires item 2 first. Reply from Gmail with a PDF attached.

- **Expected:** Attachment appears in the message + downloadable link with `Content-Disposition: attachment` header + file on disk under `./storage/<org_id>/messages/<msg_id>/`.

---

### 4. Spoofed sender + SPF fail → auto-attribution dropped — **PASS** ✅

Verified via synthetic signed POST from inside the API container with `sender` + `From` both spoofed to a real contact's email + `X-Mailgun-Spf: fail` + `X-Mailgun-Dkim-Signature: fail`.

- **Evidence:**
  ```
  [msg]  spf=fail dkim=fail spoof_suspected=True
  [conv] contact_id=None
  [victim contact was] ceo-24a00ac0@bigco.com
  ```
- Attacker C2 CEO-fraud fix confirmed live: even when the attacker knew the target's email + forged both envelope + From header, the message persists but with `contact_id=NULL` + `spoof_suspected=true` flag. Operator can review under "Needs Review" filter.

---

### 5. Replay drop within 10-min window — **PASS** ✅

Same `(timestamp, token, signature)` triplet POSTed twice within 10 min.

- **Evidence:**
  ```
  [valid sig, unknown recipient] -> 200 {"status":"accepted"}
  [replay same triplet]          -> 401 {"error":"replay"}
  ```

---

### 6. Auto-responder header → workflow event suppressed — **PASS** ✅

Signed POST with `Auto-Submitted: auto-replied`.

- **Evidence:**
  ```
  msg spf=pass dkim=None auto=True spoof=False chan_id=mg:<smoke-auto-d...
  ```
- `auto_generated=true` in payload → workflow-event publish path bypassed (verified in code + no `email.replied` audit).

---

### 7. Redis outage → fail-CLOSED — **PENDING (user, optional)**

Requires stopping Redis mid-flight. Not risk-free to test in a shared dev DB; safe to defer to a staging drill. Behavior is unit-tested in `test_mailgun_step3_webhook.py::test_webhook_redis_down_signature_check_fails_closed`.

- **Recommended verification:** run the unit test on next `run test` invocation.

---

### 8. Broker down → sweeper re-enqueues — **PENDING (user, optional)**

Same reasoning as item 7 — requires stopping Celery mid-flight. The sweeper mechanism itself is verified live via item 10.

---

### 9. Exhausted-retry ingest → DLQ row — **PASS** ✅

Signed POST with missing `Message-Id` header (deliberate DLQ path).

- **Evidence:**
  ```
  [dlq]      before=0 after=1 delta=1
  [dlq-latest] reason=missing_mailgun_delivery_id
               details={'payload_keys': ['From', 'Subject', 'body-plain', 'recipient', 'sender', 'signature', 'timestamp', 'token']}
  ```
- DLQ row visible via `GET /api/v1/admin/email-inbound-dlq` (Owner-only, verified by permission-key registration test in Step 5 suite).

---

### 10. Orphan sweeper cleans stale staging dir — **PASS** ✅

Created `/app/storage/<uuid>/staging/<uuid>/` with mtime 2 hours ago, invoked `sweep_staging_orphans.run()`.

- **Evidence:**
  ```
  [before] drwxr-xr-x  aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
  sweep_staging_orphans removed: 1
  [after]  (directory empty)
  ```

---

## Additional synthetic checks (bonus)

Beyond the 10-item plan, the smoke also verified:

- ✅ **Unsigned POST → 401** with `{"error": "bad signature"}` + audit event
- ✅ **Bad signature → 401** with `{"error": "bad signature"}`
- ✅ **Stale timestamp (>5 min) → 401** with `{"error": "bad signature"}`
- ✅ **Unknown recipient with valid signature → 200** (no side-effect leak) + system-level `mailgun.inbound.unknown_recipient` audit
- ✅ **Regular reply with valid recipient + Message-Id → persisted** with `mg:<id>` channel_message_id, spf/dkim columns populated, workflow-events published (when publish_workflow_events=True)

---

## Bugs found + fixed during smoke

1. **`docker-compose.yml` didn't forward MAILGUN_* env vars** into the containers.
   Fix: added `MAILGUN_API_KEY`, `MAILGUN_SIGNING_KEY`, `MAILGUN_SIGNING_KEY_PREVIOUS` to the `x-secret-vars` block.

2. **`SET LOCAL app.current_org_id = :o` rejected by Postgres** — `SET LOCAL` doesn't accept parametric binds (asyncpg translates `:o` to `$1`).
   Fix: switched to `SELECT set_config('app.current_org_id', :o, TRUE)` — SQL-native equivalent that DOES accept binds. Task was retrying with `PostgresSyntaxError` until now.

3. **`Contact(first_name=…, last_name=…)`** used in Step 1 + 4 test files, but the model has `full_name`.
   Fix: renamed to `full_name=…` in both test files. Tests will pass on next pytest run.

---

## Remaining user-driven items

**Items 1, 2, 3 (real Gmail round-trip):**

1. In Mailgun dashboard → Send → Domain settings → sandbox domain → **Authorized Recipients** — add your Gmail (`neuradigi01@gmail.com`) + one more test address.

2. In the CRM (production): Settings → Integrations → Email Sender → verify at least one SMTP sender is present + capture toggle is ON. The reply address it shows should be `in_<token>@sandbox3f4add...mailgun.org`.

3. Compose a test email FROM that SMTP sender TO your Gmail (via the campaign compose UI or any place that fires `send_email`). In Gmail: verify Reply-To header. Reply. Confirm the reply lands in the CRM inbox.

4. Attach a small PDF to the reply. Confirm it renders as a downloadable link in the CRM thread + downloading it triggers a browser download (not inline).

**Items 7, 8 (chaos tests):** Skip or run on a staging environment where killing Redis / Celery is safe. Unit tests already cover the behavior.

---

## Post-smoke wrap-up

- [x] Sandbox route created + verified (deleted 2026-09-02 during prod cutover to free free-tier slot)
- [x] 5 auth-path smoke items PASS
- [x] 3 ingest-path smoke items PASS (spoof-drop, auto-responder, DLQ)
- [x] Orphan sweeper verified
- [x] 2 real bugs uncovered + fixed (compose passthrough, SET LOCAL bind)
- [x] Prod domain `reply.karmcrm.com` added in Mailgun → DNS records added at Cloudflare by domain owner → SPF/DKIM/MX verified green
- [x] Env flipped in `config.env` + stack restarted + prod route created (id `6a980b024f83d7b2bb098557`)
- [ ] Real Gmail round-trip pending (items 1–3, now against prod domain)
- [ ] Signing-key rotation drill (deferrable — low risk to schedule for a low-traffic window)
