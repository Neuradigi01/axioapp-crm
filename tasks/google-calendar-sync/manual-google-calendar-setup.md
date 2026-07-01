# Manual Google Cloud Console setup for Calendar sync

**Do this ONCE per environment (dev / staging / prod) before any
employee tries to connect their calendar.** ~10 minutes.

We're reusing the same OAuth client the Google Ads integration uses,
so most of the plumbing already exists — we only need to enable the
Calendar API + add the calendar scope.

---

## Prerequisite

You already have a Google Cloud project + OAuth client from the Google
Ads setup (see `tasks/ad-integrations/manual-google-oauth-setup.md`).

Confirm you know which project + OAuth client the CRM uses by opening
`API/config.env` (or the SOPS-encrypted secrets) and finding:

```
GOOGLE_CLIENT_ID=xxxxxxxxxx.apps.googleusercontent.com
```

The `.apps.googleusercontent.com` domain tells you it's a Google
OAuth 2.0 client. Note the ID.

---

## Step-by-step

### 1. Open the Google Cloud Console

- Go to https://console.cloud.google.com/
- Top-left project picker → select the project that owns the OAuth
  client above (probably named "Core CRM" or similar)

### 2. Enable the Google Calendar API

- Left sidebar → **APIs & Services** → **Library**
- Search box → type "Google Calendar API"
- Click the result → click the blue **Enable** button
- Wait ~5s for enablement to propagate

### 3. Add the calendar scope to the OAuth consent screen

- Left sidebar → **APIs & Services** → **OAuth consent screen**
- Click **Edit App** (or "Update" — button label depends on Cloud
  Console version)
- Skip the App Information screen (nothing changes)
- On the **Scopes** page, click **Add or Remove Scopes**
- In the filter box paste:
  ```
  https://www.googleapis.com/auth/calendar.events
  ```
- Tick the checkbox next to it → **Update**
- Save + finish the wizard

### 4. Verify the redirect URI is registered

- Left sidebar → **APIs & Services** → **Credentials**
- Click the OAuth 2.0 Client ID row (matches `GOOGLE_CLIENT_ID` from
  your secrets)
- Under **Authorized redirect URIs** the following MUST be present:

  - Dev:      `http://localhost:30007/api/v1/integrations/google-calendar/callback`
  - Staging:  `https://staging.yourdomain.com/api/v1/integrations/google-calendar/callback`
  - Prod:     `https://app.yourdomain.com/api/v1/integrations/google-calendar/callback`

  If any are missing, click **Add URI**, paste, click **Save**.

### 5. (If OAuth consent screen is in "Testing" mode) Add test users

- Left sidebar → **APIs & Services** → **OAuth consent screen**
- Under **Test users** → **Add users**
- Add every email address of employees who need to test the Calendar
  connect flow (Google won't let unlisted accounts complete the OAuth
  in Testing mode)
- Save
- **This is temporary.** Before rolling out to real production users,
  submit the app for Google verification (adds a few days but removes
  the test-user requirement).

### 6. (Optional but recommended) Publish the app

Once you've verified the flow works end-to-end for one or two test
users:

- **APIs & Services** → **OAuth consent screen** → **Publish App**
- Google will flag any scopes that need verification. The
  `calendar.events` scope IS classified as "sensitive" so verification
  is required for production — plan ~7 business days.

---

## Verify the setup

After Steps 2-3 land in code (backend OAuth flow), run this smoke:

1. Log into the CRM as a test user (e.g. `ajaygogane224@gmail.com`
   already added as a Google test user in Step 5)
2. Navigate to `/user/integrations`
3. Click **Connect** on the Google Calendar card
4. Google's consent screen should list "Google Calendar" as one of the
   things the app wants access to
5. Grant → land back on the CRM with the card showing "Connected"

If you see "This app isn't verified" — that's expected for Testing
mode. Click Advanced → Continue.

If you see "access_denied: The scope is not allowed" — Step 3 didn't
save. Re-check the consent screen.

If you see "redirect_uri_mismatch" — the redirect URI in Step 4 doesn't
match what the CRM sent. Copy the exact URI Google shows in the error
into the Credentials page.

---

## Quota / rate limits

Default Calendar API quota: **1,000,000 requests/day per project.**
That covers ~30k appointments / day / org at 3-4 API calls each. Plenty
for early operators.

If you hit limits → **APIs & Services → Enabled APIs → Google Calendar
API → Quotas** → request an increase (Google usually approves within a
day for legitimate use).

---

## What happens if I skip this?

- The CRM's Connect button will show Google's consent screen but
  Google will refuse the OAuth code exchange with `invalid_scope` or
  `access_denied`
- The CRM logs the failure to `last_error` on the token row
- The integrations card shows "Reconnect needed" with the Google error
  surfaced verbatim

No CRM data loss — just no calendar sync until Cloud Console is set up.
