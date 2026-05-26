# Manual: Meta Ads (Facebook + Instagram) OAuth app setup + verification

A DevOps checklist for the human who owns the Meta App. Run **in parallel** with Step 1, 4, 5 code — App Review takes 1–3 weeks externally and is the second longest-lead-time item in this track (Google is longer).

**Owner:** whoever has the Facebook account that will own the Meta App (typically the founder; should be the same person who owns the Facebook Business Manager).
**Time required:** ~3 hours of focused work today + back-and-forth with Meta review (waiting time, not active work).

---

## Stage 1 — Facebook Business Manager (today, ~30 min)

If you don't already have one, you need a **Meta Business Manager** account to claim ad accounts + pages.

1. Go to <https://business.facebook.com/> and sign in with your personal Facebook account.
2. **Create Business Account**: enter business name (use legal entity name — matters for verification), your name, business email.
3. Once created, note the **Business ID** in the URL bar — looks like `?business_id=1234567890`. Save it.
4. In **Business Settings → Accounts → Pages**: add the Facebook Page that runs your lead ads (or create one if not yet).
5. In **Business Settings → Accounts → Ad accounts**: add the ad account(s) running lead ads.
6. **Business Verification** (do this NOW even though it's not required until App Review — takes 3–7 days):
   - **Business Settings → Security Center → Verify business**.
   - Upload tax certificate / certificate of incorporation / utility bill (verifies your legal entity).
   - Verify phone number.
   - Meta reviews in 3–7 business days.

## Stage 2 — Create the Meta App (today, ~20 min)

1. Go to <https://developers.facebook.com/apps/> and click **Create App**.
2. **App type**: **Business**.
3. **App name**: **CRM** (match the visible product branding — user requested plain "CRM", not "FurniCRM").
4. **App contact email**: your support address.
5. **Business Account**: link to the Business Manager from Stage 1.
6. Click **Create App**. You're now in the App Dashboard.
7. Note the **App ID** (top of the page) and click **Settings → Basic** to grab the **App Secret** (Show button). Save both.
8. In **Settings → Basic**:
   - **Privacy Policy URL**: required for verification — put up a privacy policy page first (this blocks production launch but NOT dev).
   - **Terms of Service URL**: required for verification.
   - **App Icon**: required for production (1024×1024 PNG).
   - **Category**: pick "Business".
   - **App Domains**: add `furnicrm.app` (your production domain).
   - **Site URL**: add `https://app.furnicrm.app`.
9. Save changes.

## Stage 3 — Add required products to the App (today, ~10 min)

In the App Dashboard left sidebar, click **Add Product** and add these:

1. **Facebook Login for Business** — handles the OAuth flow.
2. **Webhooks** — receives lead notifications.
3. **Leads Ads Testing Tool** — for sending test leads without spending ad budget.

(Marketing API auto-enables when you request lead-retrieval scopes in Stage 5.)

## Stage 4 — Configure Facebook Login for Business (today, ~10 min)

1. In the App Dashboard left sidebar: **Facebook Login for Business → Settings**.
2. **Valid OAuth Redirect URIs** — add:
   - `http://localhost:8000/api/v1/integrations/meta/oauth/callback` (dev backend)
   - `https://api.furnicrm.app/api/v1/integrations/meta/oauth/callback` (production backend)
3. **Allowed Domains for the JavaScript SDK** — add:
   - `localhost`
   - `app.furnicrm.app`
4. Save.

Paste the App ID + Secret into your `.env`:
```
META_APP_ID=...
META_APP_SECRET=...
META_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/integrations/meta/oauth/callback
```
(Step 4 of this track adds these to `.env.example` formally.)

## Stage 5 — Configure the Webhook subscription (today, ~10 min)

The webhook is what receives lead notifications. Meta requires you to verify the URL responds correctly BEFORE you can subscribe.

1. **Webhooks → Add Subscription → Page**.
2. **Callback URL**: `https://api.furnicrm.app/api/v1/integrations/meta/webhook/v1` (use ngrok in dev: `https://abc123.ngrok.io/api/v1/integrations/meta/webhook/v1`)
3. **Verify Token**: generate a random string (e.g. `openssl rand -hex 32`). Paste it into your `.env`:
   ```
   META_WEBHOOK_VERIFY_TOKEN=...
   ```
4. **NOTE:** Meta will probe the URL with a GET request. If Step 5 code isn't deployed yet, this verification will fail — that's expected. Come back to this stage AFTER Step 5 ships.
5. After Step 5: click **Verify and save**. Meta sends a GET with `hub.challenge` → our endpoint echoes it back → Meta marks the webhook verified.
6. Subscribe to the `leadgen` event on Page objects.

## Stage 6 — Add Test Users (today, ~5 min)

Test users bypass App Review entirely — you can run the full OAuth + webhook flow with them today.

1. **Roles → Test Users → Add → Create Test Users**.
2. Create 2–3 test users. Save their email addresses.
3. **Roles → Roles → Add Administrators**: add your own Facebook account as Admin so YOU can also use the app in Dev mode.

In Dev mode (default until App Review approves), only roles + test users can use the app. That's fine for end-to-end testing.

## Stage 7 — Request advanced scopes via App Review (when ready for production)

Skip this entire stage during dev/testing — the App can work in Dev mode indefinitely with test users.

1. **App Review → Permissions and Features**.
2. Request these scopes (one by one):
   - **`leads_retrieval`** — fetch lead detail when a webhook fires.
   - **`pages_manage_metadata`** — subscribe Pages to the leadgen webhook on the user's behalf.
   - **`pages_read_engagement`** — read Page basic info.
   - **`pages_show_list`** — list the Pages the user owns.
   - **`ads_management`** OR **`ads_read`** — read campaign / ad / form metadata.
3. For each: click **Request Advanced Access** → fill the form:
   - **How will your app use this permission?** (1–2 sentences)
   - **Demo video**: 3-5 min screen recording showing the OAuth flow + how the scope is used. Re-use the video across scopes.
   - **Test instructions**: tell Meta reviewers exactly how to test (login URL, test credentials, what to click).
4. **Business verification** (Stage 1.6) must be complete BEFORE you can submit App Review.
5. Submit. **Meta review typically takes 1–3 weeks** of back-and-forth. They'll request changes to the video, scope justification, or test instructions.
6. Once approved: anyone can connect with these scopes. Until approved: only Admins / Developers / Test Users.

## Stage 8 — Smoke test the OAuth flow (after Step 4 code lands)

Once Step 4 code ships:

1. Make sure your Facebook account is an Admin on the Meta App (Stage 6.3).
2. Open `http://localhost:4200/user/settings/integrations` → click **Connect Meta Ads** (button ships in Step 7).
3. You should be redirected to Facebook's OAuth consent screen showing the requested permissions.
4. Click **Allow** → redirected back to the Settings page → card shows "Connected as <your name>".
5. Inspect the `integrations` table:
   ```sql
   SELECT org_id, provider, account_id, account_label, status, scopes, connected_at
   FROM integrations WHERE provider='meta_ads';
   ```
   Confirm a row exists with your name in `account_label` and status `connected`.
6. Behind the scenes, Step 4 will auto-subscribe your Pages to the leadgen webhook (this is what `pages_manage_metadata` enables — Meta does this for us, unlike Google where the user does it in the Ads UI).

## Stage 9 — Send a test lead (after Step 5 code lands)

1. In your Meta App Dashboard: **Leads Ads Testing Tool**.
2. Pick the Page + a lead form that's live on your ad account.
3. Click **Create lead** → fill in test data → Submit.
4. Meta fires a `leadgen` webhook to our endpoint within seconds.
5. Confirm a lead appears in `/user/leads` with source badge "Meta Ads" and the form fields populated.

---

## What you DON'T need today (Step 1)

Step 1 is pure backend table + crypto. None of these external steps are required to ship Step 1. You can start them in parallel — by the time Steps 4 + 5 land, you'll have:
- Business Manager set up (Stage 1)
- Business Verification submitted (Stage 1.6) — 3–7 day wait, kick off today
- Meta App created with App ID + Secret (Stages 2 + 4)
- Test users ready (Stage 6)

## Tracking your progress

| Stage | Started | Approved/done | Notes |
|---|---|---|---|
| 1. Business Manager | | | |
| 1.6. Business Verification | | | Meta takes 3–7 days |
| 2. Meta App created | | | |
| 3. Required products added | | | |
| 4. Facebook Login configured | | | |
| 5. Webhook configured | | | After Step 5 code |
| 6. Test users added | | | |
| 7. App Review submitted | | | Wait until production launch |
| 8. Smoke OAuth flow | | | After Step 4 code |
| 9. Test lead through ad form | | | After Step 5 code |

Update this file as you complete each stage so the code team knows where you are.

---

## Gotchas specific to Meta

- **Webhook verification is one-shot at config time**: Meta probes the URL once when you click Verify. If our endpoint is down at that moment, you'll have to retry — Meta doesn't auto-re-verify later. Make sure ngrok / production is up before clicking Verify.
- **Test users can't ALSO be Admins of the same app**: keep them separate accounts.
- **Pages have to be CLAIMED in Business Manager** before you can subscribe them to webhooks. If your Page is owned by a personal Facebook account, transfer ownership to the Business Manager first.
- **Instagram leads share the same `leads_retrieval` scope** as Facebook lead ads — one App Review submission covers both. You don't need a separate Instagram app.
