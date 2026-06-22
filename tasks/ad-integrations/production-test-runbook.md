# Production test runbook — Google Ads integration

**Purpose:** Step-by-step checklist for validating the Google Ads → CRM
integration against real Google Ads traffic, after Basic Access lands and
before announcing the integration to paying customers.

**Audience:** Whoever owns the production rollout (typically founder or
tech lead). Read top-to-bottom; don't skip phases.

**Time:** ~3 days end-to-end (mostly waiting on Google review windows and
on-the-ad campaign delivery). Active work: ~4 hours total.

**Budget:** ~₹500-1,000 in real ad spend during Phase 4 (you control the
budget — keep it tight, the point isn't to win business, it's to fire real
form submissions).

**Pre-requisite:** Test-account validation is complete. The full loop
already works on the test MCC; this runbook validates that the same loop
works against a non-test (production) Google Ads account.

---

## Phase 0 — Pre-flight (do before anything else)

These are the gates that, if any fail, you should NOT proceed.

- [ ] **Basic Access approved** on the developer token. Check the API
      Center on your production MCC `938-729-9841`. If still pending,
      escalate the support case (`1-7463000041029`) and stop here.
- [ ] **OAuth consent screen Production-published** in Google Cloud
      Console (not "Testing"). Required for non-test users to connect.
      - CASA security assessment completed (third-party audit, ~$1k-$15k).
      - Privacy policy + Terms of Service URLs live, public, and reachable.
- [ ] **Production OAuth client** created with the production redirect URI:
      ```
      https://api.<your-prod-domain>/api/v1/integrations/google/callback
      ```
      (NOT the localhost dev one.)
- [ ] **Production config + secrets** are set for the prod server.
      Non-secret → `API/config.env` (committed plaintext):
      ```
      GOOGLE_OAUTH_CLIENT_ID=<production client id>
      GOOGLE_OAUTH_REDIRECT_URI=https://api.<your-prod-domain>/api/v1/integrations/google/callback
      GOOGLE_ADS_LOGIN_CUSTOMER_ID=9387299841
      GOOGLE_ADS_API_VERSION=v21
      ```
      Secret → `secrets.enc.env` via `./run.sh secrets-edit` (SOPS + age):
      ```
      GOOGLE_OAUTH_CLIENT_SECRET=<production secret>
      GOOGLE_ADS_DEVELOPER_TOKEN=<Basic Access token, NOT Explorer>
      INTEGRATIONS_ENCRYPTION_KEY=<a real Fernet key, NOT the dev one>
      ```
      The prod server must hold its age private key at
      `~/.config/sops/age/keys.txt` and be a recipient in `.sops.yaml`
      (`prod-server` / `prod-server2`). No MASTER_KEY — `./run.sh`
      decrypts secrets in-memory per command.
- [ ] **HTTPS** terminates correctly at `api.<your-prod-domain>` (Google
      will refuse non-HTTPS webhook URLs in production).
- [ ] **Celery worker container running** in production. Inline-fallback
      processing is fine for dev but production should use the proper
      worker. Verify with: `docker ps | grep celery` on the prod host.
- [ ] **Sentry (or equivalent)** is wired to capture
      `process_google_lead` task exceptions. The DLQ catches application
      failures; Sentry catches everything else.
- [ ] **Database backup** taken within the last 24 hours. If the
      integration writes bad data, you want a rollback target.
- [ ] **The CRM is hosted at a stable URL** — `https://app.<your-prod-domain>`.
      Don't run production tests against a preview/branch deploy.

If any checkbox above is unchecked, stop. Resolve, then re-enter at
Phase 1.

---

## Phase 1 — Production OAuth dry-run (10 min, no spend)

Goal: confirm the OAuth round-trip works in production *before* spending
any ad money.

1. Sign into the CRM in production as your Owner account.
2. Navigate to **Settings → Integrations**.
3. Click **Connect Google Ads**.
4. On Google's consent screen, sign in as a Google account that has
   **direct access to a real (non-test) Google Ads account** you control.
5. Approve the scopes.

**Verify:**
- [ ] Redirect back to `/user/settings/integrations` is clean (no 404,
      no `redirect_uri_mismatch`).
- [ ] Card shows **Connected as <your email>** + green status pill.
- [ ] No `Reconnect required` / `Error` states.
- [ ] Click **Load** under Accounts & Forms — your real Ads accounts
      appear. Test-account badges should be absent (you're on production
      accounts now).
- [ ] DB sanity check (run on prod via `docker exec`):
      ```sql
      SELECT id, org_id, account_label, status, scopes, connected_at
      FROM integrations
      WHERE provider = 'google_ads'
      ORDER BY connected_at DESC LIMIT 5;
      ```
      Confirm `status='connected'` and `scopes` includes `adwords`.

**If anything fails:** screenshot + check `docker logs --tail 200 <api-container>`
on prod. Disconnect, fix, re-try. Don't proceed.

---

## Phase 2 — Create a real Lead Form (15 min, no spend)

Goal: have a real Lead Form Extension attached to a real campaign, with
the webhook configured but the campaign still paused.

1. In Google Ads (signed in as the account from Phase 1), pick one of
   your real child accounts.
2. **Tools → Asset library → Lead form** (or the campaign-asset path if
   the library doesn't surface Lead form for that account).
3. Build a minimal Lead Form:
   - **Form name:** `Production Test - <today's date>`
   - **Business name:** your real company name
   - **Headline:** something innocuous like "Get a free quote"
   - **Privacy policy URL:** must be a real, live URL on your domain.
     Google validates this in production (unlike test mode).
   - **Questions:** Name + Email + Phone Number (minimum 3 — these are
     the standard fields, easiest to test field mapping)
4. **Lead delivery options:**
   - **Webhook URL:** copy from CRM → Settings → Integrations → Google
     card → Webhook URL field. Will look like
     `https://api.<your-prod-domain>/api/v1/integrations/google/webhook/v1/<secret>`
   - **Key:** paste just the `<secret>` portion (everything after `/v1/`)
5. Click **Send test data** in Google's UI.

**Verify:**
- [ ] Google shows green "Test data sent" inline.
- [ ] Within 5 seconds, a new lead appears in CRM `/user/leads` with
      source `google_ads`.
- [ ] Click into the lead → linked contact has the test name/email
      populated correctly (NOT the placeholder "Google Ads lead").
- [ ] Source attribution panel on the detail page shows `external_form_id`,
      `external_lead_id`, `campaign_id`.

6. **Save** the Lead Form in Google Ads.
7. Create a Search campaign that uses this form as an asset. Set:
   - **Budget:** ₹100/day max
   - **Targeting:** as narrow as possible (one zip code, your office;
     specific keyword like your brand name)
   - **Status:** PAUSED (don't enable yet)
8. Save the campaign as Paused.

---

## Phase 3 — CRM-side wiring verification (5 min, no spend)

1. In CRM → Settings → Integrations → Google card → expand the child
   account row.
2. Find the Lead Form you just created (form ID matches what Google
   showed).
3. **Subscribe** to it.
4. **Edit mapping** — map at minimum:
   - `FULL_NAME` → `contact.full_name`
   - `EMAIL` → `contact.email`
   - `PHONE_NUMBER` → `contact.phone`
5. Save mapping.

**Verify:**
- [ ] Subscribe toggle is now ON.
- [ ] DB check:
      ```sql
      SELECT external_form_id, field_mapping, enabled
      FROM integration_subscriptions
      WHERE integration_id = '<your integration UUID from Phase 1>';
      ```
      Confirm `field_mapping` has the three mappings, `enabled=true`.

---

## Phase 4 — First real ad submission (~24-48 hours, ~₹100-300 spend)

Goal: prove the full pipeline works with real ad serving, real form
rendering, real user submission.

1. **Enable** the campaign in Google Ads (was Paused in Phase 2).
2. Wait for Google's policy review (usually 1-4 hours for Search ads;
   can be up to 24h).
3. Once the campaign shows status **Eligible** (not "Under review"):
   - Open an **incognito browser window**.
   - **Different IP than where you administer the campaign** (use a
     mobile hotspot, or a colleague's network). Google sometimes
     suppresses your own ads from showing to your admin IP.
   - Google-Search the keyword you targeted.
   - Your ad should appear. If it doesn't, wait 30 min and try again.
4. Click your own ad.
5. The Lead Form opens (full-screen overlay on mobile, modal on desktop).
6. Fill it with **real-looking but disposable data**:
   - Name: `Test Submission - <timestamp>` (so you can find it later)
   - Email: a real address you control (use Gmail aliases:
     `youraddr+gads-test@gmail.com`)
   - Phone: a real number you can verify (skip if you don't want SMS)
7. Submit.

**Verify within 30 seconds:**
- [ ] Lead appears in CRM `/user/leads`.
- [ ] **Linked contact has real values**, not placeholders.
- [ ] **Attribution panel shows a real `gclid`** (long string like
      `Cj0KCQiA-...`) — this is the marker that the lead came from
      actual ad traffic, not a test button.
- [ ] **Lead source:** `google_ads`.
- [ ] **Owner assignment** worked (round-robin or default per your
      RBAC config).
- [ ] **DLQ is empty** (`/user/settings/integrations` → "1 delivery
      needs attention" should NOT be there).

**If lead doesn't arrive within 5 minutes:**
- Check Google Ads → form → "Lead delivery" → look at the delivery log
  Google maintains (shows status + retry count for each lead).
- Check CRM → Settings → Integrations → DLQ for any errored payloads.
- Check Celery worker logs on prod: `docker logs --tail 100 <celery-container>`.
- Check Sentry for any captured exceptions.

8. **Repeat steps 3-7 two more times** with different fake names to
   confirm:
   - [ ] Each submission creates a separate lead (no false dedup).
   - [ ] Each lead has a unique `external_lead_id` in attribution.
   - [ ] Round-robin owner assignment cycles through users correctly.

9. **PAUSE the campaign** once you have 3 successful end-to-end leads.
   No reason to keep spending.

---

## Phase 5 — Multi-tenant isolation (30 min, no spend)

Critical: prove that Org A's Google Ads leads cannot leak into Org B's
CRM.

1. Have a friend / second test customer set up a separate Org in the
   CRM.
2. They connect *their own* Google Ads account via the Settings page
   (same flow as Phase 1, but from their org).
3. They create their own Lead Form + paste the webhook URL the CRM
   gives THEM (which has their own org's secret).
4. They click **Send test data** on their form.

**Verify:**
- [ ] Their lead arrives in **their org's** `/user/leads`.
- [ ] It does **NOT** appear in your org's `/user/leads`.
- [ ] DB row-level check:
      ```sql
      SELECT id, org_id, source, contact_id
      FROM leads
      WHERE source = 'google_ads'
      ORDER BY created_at DESC LIMIT 20;
      ```
      Confirm `org_id` differs between your leads and theirs. NEVER
      should you see the other org's `org_id` in your CRM UI.

5. Have them disconnect → verify their webhook stops working
   (their next test data POST should 401 in the CRM logs).
6. **You disconnect** → verify your webhook stops working similarly.
   Old `external_lead_id`s from your previous tests should still be
   visible in your CRM, but new POSTs to the old URL are rejected.

---

## Phase 6 — Failure-mode tests (1 hour, no spend)

These verify graceful degradation. Run them deliberately in production
(off-peak hours).

| Test | How to trigger | What to verify |
|---|---|---|
| Webhook with wrong secret | curl your URL but flip one char in the secret | API returns 401, audit log records `unknown_webhook_key`, no lead created |
| Replay an already-processed lead | ngrok-Replay an old webhook | API returns 200, `process_google_lead` returns `status=duplicate`, no second lead |
| OAuth token expired mid-call | Wait until `token_expires_at < NOW()`, then click Load | Backend auto-refreshes via refresh_token, call succeeds. If refresh fails, integration status flips to `expired`, UI shows "Reconnect required" |
| Disconnect, then reconnect | Click Disconnect → Connect again | New secret minted; old webhook URL stops authenticating; new URL works; subscriptions persist (don't have to re-map) |
| Celery worker crash mid-task | Kill the celery container during a busy period | Future webhooks queue in Redis; restart worker → backlog processes; no leads lost |
| Mapping deleted but webhook still fires | Delete a subscription, then send test data | API receives 200, but `process_google_lead` writes to DLQ with reason `no_subscription`. Operator can re-enable + replay |

For each: record the outcome. Anything that DIDN'T match the "verify"
column is a bug — file it before going live with customers.

---

## Phase 7 — Monitoring for 1 week (passive observation)

Before announcing to customers, let the integration run with your real
ad campaign at low budget for **7 calendar days**. Each morning:

- [ ] Check `/user/settings/integrations` → DLQ count. Should be 0
      most days. If non-zero, investigate before purging.
- [ ] Spot-check a recent lead's detail page. Attribution panel should
      look the same as Phase 4's submissions.
- [ ] Check Sentry for `process_google_lead` exceptions. Triage any
      new ones.
- [ ] Quota usage in Google Cloud Console → APIs → Google Ads API →
      Quotas. You should be well under the Basic Access 15k ops/day
      ceiling.
- [ ] Lead-to-CRM latency: spot-check 5 leads. From Google's "delivered
      at" timestamp to CRM `created_at` should be < 10 seconds typically,
      < 60 seconds worst case.

Anything outside these bounds → debug before customer #1 connects.

---

## Phase 8 — Customer onboarding doc (write before customer #1)

Write a one-page guide for your first paying customer to connect their
own Google Ads account. Should cover (at minimum):

- Where to click in the CRM ("Settings → Integrations → Connect Google
  Ads")
- What Google account they sign in with (the one that admins their Ads
  account, not the one that runs the campaigns)
- What scopes they're approving and why
- How to copy the webhook URL into their existing Lead Form Extensions
- How to subscribe + map fields per form
- What to do if a form was already collecting leads via CSV — they can
  switch to webhook without losing existing leads

Save it at `docs/customer-onboarding/google-ads.md` or wherever your
public-facing docs live.

---

## Rollback procedure (if something goes wrong in production)

If at any point during Phase 4-7 you discover the integration is
mis-routing leads, leaking data across orgs, or silently dropping leads:

1. **Immediate stop:** disable webhook ingestion globally — fastest way
   is to edit the API container's env to set:
   ```
   GOOGLE_ADS_DEVELOPER_TOKEN=invalid
   ```
   and restart. The OAuth flow + Load button will fail (acceptable),
   but more importantly, anything that tries to call back to Google's
   API in `process_google_lead` will fail too. Customer's webhooks
   land in DLQ instead of being processed (no data corruption).
2. **Mark all integrations as `error`:**
   ```sql
   UPDATE integrations SET status = 'error', last_error = 'Maintenance — see status page' WHERE provider = 'google_ads';
   ```
   This flips every customer's CRM UI to "Reconnect required" — they
   can't subscribe new forms while you fix.
3. **Pause all real campaigns:** if YOUR ad campaign from Phase 4 is
   still running, pause it.
4. **Notify any affected customers** via your status page / email.
5. **Fix.** Once fixed, undo step 1 + 2, then notify customers it's
   back online.

---

## Sign-off checklist (move to "GA ready" status)

Before announcing Google Ads support to customers, every one of these
must be true:

- [ ] Phases 0-7 complete with no unresolved issues.
- [ ] At least 3 real ad-driven leads landed cleanly in CRM (Phase 4).
- [ ] Multi-tenant isolation verified (Phase 5).
- [ ] All failure modes behave as expected (Phase 6).
- [ ] 7 days of monitoring with 0 (or all-investigated) DLQ entries.
- [ ] Customer onboarding doc written and reviewed.
- [ ] Rollback procedure tested at least once (dry-run, not live).
- [ ] Sentry alerts configured for `process_google_lead` failures.
- [ ] CRM team trained on triaging DLQ entries.

When all checked: announce. Document the date — you're now in GA for
Google Ads.

---

*Owner: <whoever runs this runbook>. Update timestamps + outcomes
inline as you go through it the first time — the next person running
it will benefit from your notes.*
