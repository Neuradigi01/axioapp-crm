# Manual: Google Ads OAuth app setup + verification

A DevOps checklist for the human who owns the Google Cloud project. Run **in parallel** with Step 1–3 code — verification takes 2–6 weeks externally and is the longest-lead-time item in this track.

**Owner:** whoever has the Google account that will own the OAuth client (typically the founder / business owner).
**Time required:** ~2 hours of focused work today + back-and-forth with Google review (waiting time, not active work).

---

## Stage 1 — Create the project + enable APIs (today, ~30 min)

1. Go to <https://console.cloud.google.com/>.
2. Create a new project (or pick an existing one): **"CRM Ad Integrations"**.
3. Note the **Project ID** (looks like `crm-ad-integrations-456789`). Save it.
4. In the left sidebar: **APIs & Services → Library**. Enable these APIs (search + click Enable for each):
   - **Google Ads API**
   - **Google People API** (needed to fetch the user's email for `account_label`)
5. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
6. If prompted to configure the OAuth consent screen, do that first (Stage 2 below).

## Stage 2 — Configure OAuth consent screen (today, ~30 min)

1. **APIs & Services → OAuth consent screen**.
2. **User Type**: pick **External** (Internal only works inside Google Workspace).
3. **App information:**
   - App name: **CRM** (match the visible product branding — user requested plain "CRM", not "FurniCRM")
   - User support email: your support address
   - App logo: optional (helps verification; you can add later)
4. **App domain:**
   - Application home page: your production URL (e.g. `https://app.furnicrm.app`)
   - Application privacy policy URL: REQUIRED for verification — put up a privacy policy page first (this blocks production launch but NOT dev)
   - Application terms of service URL: same — required for verification
5. **Authorized domains**: add your production domain (e.g. `furnicrm.app`)
6. **Developer contact information**: your email
7. **Scopes** — click "Add or Remove Scopes" and add:
   - `https://www.googleapis.com/auth/adwords` (Google Ads — access lead forms + leads)
   - `https://www.googleapis.com/auth/userinfo.email` (to populate `account_label`)
   - `openid` (standard)
8. **Test users** — add the email addresses you'll use for testing (your own Google account + anyone else who needs dev access). **Up to 100 test users.** These users bypass verification — you can test the full OAuth flow with them while production verification is pending.
9. Save.

## Stage 3 — Create the OAuth client (today, ~10 min)

1. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**.
2. **Application type**: Web application.
3. **Name**: "CRM backend".
4. **Authorized JavaScript origins** — add:
   - `http://localhost:4200` (Angular dev)
   - `https://app.furnicrm.app` (production frontend, when live)
5. **Authorized redirect URIs** — add:
   - `http://localhost:8000/api/v1/integrations/google/oauth/callback` (dev backend)
   - `https://api.furnicrm.app/api/v1/integrations/google/oauth/callback` (production backend)
6. Click **Create**.
7. **Save the client_id + client_secret immediately** — Google shows the secret once.
8. Paste both into your `.env`:
   ```
   GOOGLE_OAUTH_CLIENT_ID=...
   GOOGLE_OAUTH_CLIENT_SECRET=...
   GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/integrations/google/oauth/callback
   ```
   (Step 2 of this track adds these to `.env.example` formally.)

## Stage 4 — Google Ads developer token (today/this week, 1–5 business days for approval)

The Google Ads API needs its OWN access token (separate from OAuth) called a **Developer Token**.

1. Sign into <https://ads.google.com/> with a Google Ads MANAGER account (MCC). If you don't have one, create a new Manager Account — free, takes 5 minutes.
2. In the MCC: **Tools & Settings → Setup → API Center**.
3. Click **Apply for token**. Fill the form:
   - Why you're requesting access: "Operate a CRM that ingests Lead Form Extension submissions for furniture retail clients"
   - API user type: External tool / Built for our agency
   - List the test customer IDs you'll use
4. Submit. **Google reviews this in 1–5 business days** for Basic access (15k operations/day, enough for v1).
5. Once approved, you'll get the **Developer Token** by email. Paste into `.env`:
   ```
   GOOGLE_ADS_DEVELOPER_TOKEN=...
   ```

## Stage 5 — Submit for OAuth app verification (when ready for production launch)

You can SKIP this entire stage during dev/testing — test users bypass verification. Do it only when you want non-test-user customers to be able to connect.

1. **APIs & Services → OAuth consent screen → Edit App**.
2. Click **Publish App** → **Submit for Verification**.
3. Required uploads:
   - **App home page** (must be live + match Authorized domains)
   - **Privacy policy** (must include data-collection disclosures for Google Ads scopes)
   - **Terms of service**
   - **App demo video** (3–5 min screen recording showing the OAuth flow + why you need each scope — Google will request this)
4. **Security assessment** — Google Ads scopes are "Restricted" → triggers a CASA (Cloud Application Security Assessment) audit by a third party. Costs ~$1k–$15k depending on tier. **This is the biggest external cost in the integration.** Required for production only.
5. Google review: **typically 2–6 weeks** of back-and-forth. They'll request changes to the video, privacy policy, or scope justification.
6. Once approved: anyone can connect. Until approved: only test users can.

## Stage 6 — Smoke test the OAuth flow (after Step 2 code lands)

Once Step 2 code ships:

1. Make sure your Google account is in the "Test users" list (Stage 2.8).
2. Open `http://localhost:4200/user/settings/integrations` → click **Connect Google Ads** (button ships in Step 7).
3. You should be redirected to Google's consent screen showing the requested scopes.
4. Click **Allow** → redirected back to the Settings page → card shows "Connected as <your email>".
5. Inspect the `integrations` table:
   ```sql
   SELECT org_id, provider, account_id, account_label, status, scopes, connected_at
   FROM integrations WHERE provider='google_ads';
   ```
   Confirm a row exists with your email in `account_label` and status `connected`.

## Stage 7 — Configure a Google Ads Lead Form to deliver webhooks (after Step 3 code lands)

1. In Google Ads UI: **Tools & Settings → Bulk Actions → Assets → Lead form extensions**.
2. Create or edit a Lead Form.
3. Scroll to **Lead delivery options → Webhook integration**.
4. **Webhook URL:** `https://api.furnicrm.app/api/v1/integrations/google/webhook/v1` (use ngrok in dev: `https://abc123.ngrok.io/api/v1/integrations/google/webhook/v1`)
5. **Key:** the per-org webhook secret shown in your CRM Settings (Step 3 ships this UI).
6. Click **Send test data** → Google sends a sample lead → confirm a lead appears in `/user/leads` with source badge "Google Ads".

---

## What you DON'T need today (Step 1)

Step 1 is pure backend table + crypto. None of these external steps are required to ship Step 1. You can start them in parallel — by the time Steps 2 + 3 land, you'll have:
- OAuth client_id + client_secret (Stage 3)
- Google Ads developer token (Stage 4) — approval takes 1–5 days, kick off today

## Tracking your progress

| Stage | Started | Approved/done | Notes |
|---|---|---|---|
| 1. GCP project + APIs | | | |
| 2. OAuth consent screen | | | |
| 3. OAuth client created | | | |
| 4. Developer token | | | Google takes 1–5 days |
| 5. Verification submitted | | | Wait until production launch |
| 6. Smoke OAuth flow | | | After Step 2 code |
| 7. Lead form webhook configured | | | After Step 3 code |

Update this file as you complete each stage so the code team knows where you are.
