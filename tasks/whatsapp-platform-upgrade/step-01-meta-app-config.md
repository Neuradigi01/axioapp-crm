# Step 1 — Meta App configuration & Embedded Signup prerequisites

**Goal:** Configure the existing Meta App (used today for Meta Ads OAuth) to support WhatsApp Embedded Signup. Add WhatsApp Business Platform product, create an Embedded Signup Configuration, set verification URLs, and confirm Business Verification status. **No code changes in this step** — entirely Meta App Dashboard work. Output: an `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID` value to drop into `.env`, plus a documented configuration the team can re-apply.
**Track:** WhatsApp Platform Upgrade — Phase 1 (Embedded Signup)
**Status:** Pending
**Depends on:** None. The Meta App referenced by `META_APP_ID` in [`.env`](API/.env.example) is the target. If business verification was completed for Meta Ads OAuth (likely), it carries over.

---

## Scope

In-scope:

- **Add WhatsApp Business Platform product** to the existing Meta App in [developers.facebook.com](https://developers.facebook.com) → Apps → Core CRM → Add product → WhatsApp.
- **Create an Embedded Signup Configuration** under WhatsApp → Configurations → New configuration. Pick:
  - `phone_number_selection: existing_only` → hides the virtual-number / display-name-only path the user explicitly rejected. Customers will only see "connect your already-verified business number."
  - `sessionInfoVersion: 3` (latest).
  - Whitelist Core CRM's domain in "Allowed Domains" (e.g. `app.core-crm.com`, plus your ngrok URL for dev).
- **Configure App Settings** required for App Review:
  - App Domain(s).
  - Privacy Policy URL.
  - Terms of Service URL.
  - Category: Business.
  - Display name (shown in ES popup): "Core CRM".
  - App icon: 1024×1024 PNG upload.
- **Confirm Meta Business Verification** is already complete (carries over from Meta Ads OAuth setup). If not, kick off the verification process (separate Meta workflow — takes 1-5 business days).
- **Set Webhook subscription** (app-level, not per-org): subscribe to `messages`, `message_template_status_update`, `phone_number_quality_update`, `account_review_update` events for the WhatsApp Business Account.
- **Add team members as testers / admins** in Meta App Dashboard → App Roles → Testers. This unblocks demo / dev flow before App Review approval (which only allows added users to complete ES).
- **Document the resulting Configuration ID** in this step's report. The frontend will pass it to `FB.login(...)` as `config_id`.
- **Document the chosen Graph API version** (recommend `v19.0` — matches existing Meta Ads OAuth pin).

Out of scope:

- **`whatsapp_business_management` App Review submission.** That's Step 4 (after data deletion callback is wired). Without App Review, only added testers can complete the ES flow.
- **Any code changes.** This is dashboard configuration only. Backend + frontend code is Steps 2 and 3.
- **WhatsApp Manager template moderation queue** — Meta-side, not Core CRM.

## Files to touch

| File | Action |
|---|---|
| [`API/.env.example`](API/.env.example) | Add `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID=` (empty placeholder) and `WHATSAPP_GRAPH_API_VERSION=v19.0` |
| [`API/src/app/shared/config.py`](API/src/app/shared/config.py) | Add the two new settings fields (typed via Pydantic Settings) |
| `tasks/whatsapp-platform-upgrade/step-01-meta-app-config.md` | This file — record the chosen Configuration ID + screenshots of the dashboard state at end of step |

**3 files modified. 0 created. 0 deleted.**

## Plan

1. **Open Meta App Dashboard** at developers.facebook.com using the developer account that owns the app referenced by `META_APP_ID`.
2. **Click "Add Product"** → find **WhatsApp** in the catalog → **Set Up**.
3. **In WhatsApp → Configuration** (left nav):
   - Note the existing **WhatsApp Business Account** (if one is attached for testing) and **Test Phone Number** Meta provisioned automatically. Use for dev validation in Step 3.
   - Navigate to **Embedded Signup Configurations** → **Create configuration**.
   - Pick:
     - **Name:** "Core CRM Customer Onboarding"
     - **Features:** `whatsapp_business_management`, `whatsapp_business_messaging`
     - **Phone number selection:** **Use existing only** (hides virtual / display-name-only path)
     - **Session info version:** 3
   - Save. Copy the **Configuration ID** that appears (looks like `12345678901234567`).
4. **In App Settings → Basic** (left nav):
   - Set **App Domains:** add `app.core-crm.com` (prod) + the ngrok subdomain pattern (dev).
   - Set **Privacy Policy URL:** (use the marketing-site URL — must be public).
   - Set **Terms of Service URL:** (same).
   - Set **Category:** Business and Pages.
   - Set **Display name:** "Core CRM".
   - Upload **App Icon** (1024×1024 PNG).
   - Set **Data Deletion Callback URL:** placeholder for now (will be wired in Step 4: `https://app.core-crm.com/api/v1/integrations/meta/data-deletion`).
5. **In App Roles → Roles** (left nav):
   - Add the team members who will demo / test Embedded Signup as **Testers** or **Admins** (Meta accounts, by email/UID).
6. **In WhatsApp → Webhooks** (left nav):
   - Verify webhook URL (existing — `https://<env>/api/v1/integrations/whatsapp/webhook`).
   - Subscribe to fields: `messages`, `message_template_status_update`, `phone_number_quality_update`, `account_review_update`.
7. **Confirm Business Verification:**
   - Navigate to Meta Business Manager → Business Settings → Business Info → check for **"Verified"** badge.
   - If not verified: kick off Business Verification flow (out of scope to complete in this step; just unblock by starting).
8. **Update `.env.example`:**
   ```
   # WhatsApp Embedded Signup (Step 3.5.X — added 2026-06-XX)
   # Configuration ID from Meta App Dashboard → WhatsApp → Configurations.
   # Controls which features / phone-number selection options the
   # Embedded Signup popup offers. Set to 'existing_only' so customers
   # don't see virtual / display-name-only paths.
   WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID=
   WHATSAPP_GRAPH_API_VERSION=v19.0
   ```
9. **Update `config.py`** to surface the two new settings:
   ```python
   class IntegrationsSettings(BaseSettings):
       # ... existing fields ...
       whatsapp_embedded_signup_config_id: str = ""
       whatsapp_graph_api_version: str = "v19.0"
   ```
10. **Document outcome** in this step file's "Stop & report" section: the resolved Configuration ID, dashboard screenshots, business verification status.

## DB changes / migrations

**None.** This step is configuration only — no schema changes.

## Tests

No new pytest. The change is dashboard configuration + 2 env var additions. Existing config-loading tests cover the new fields automatically.

## Smoke

After completing the dashboard work:

```
1. In Meta App Dashboard → WhatsApp → API Setup, send a "Hello world"
   message from the Meta-provisioned test number to your personal
   WhatsApp. Confirm it arrives — this validates the WhatsApp Business
   Platform product is correctly attached.

2. In your personal WhatsApp, reply to that test number with "Hi".
   Open Conversations in Core CRM (after Step 2 wires the webhook) —
   you should NOT see the reply yet (webhook hasn't been hooked up
   for incoming on the test number). This step pre-stages the
   infrastructure; full webhook flow validates in Step 3.

3. Confirm WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID env var loads correctly
   in dev:
     docker-helper.cmd exec api python -c \
       "from src.app.shared.config import settings; \
        print(settings.integrations.whatsapp_embedded_signup_config_id)"
   Should print the configured ID, not empty.

4. Visit the Meta App Dashboard → App Review → Permissions and
   Features → confirm whatsapp_business_management shows up as
   available to request (will be submitted in Step 4).

5. Confirm at least one team member (the demoer) is added as a Tester
   in App Roles → Roles. Without this, Embedded Signup popup will
   refuse to complete the flow until App Review passes.
```

## Risks

- **Business Verification not done.** If Meta Business Verification was never completed (rare given Meta Ads OAuth is wired), App Review will be rejected. Kick off verification immediately — takes 1-5 business days, parallel to coding Steps 2-3.
- **Multiple Meta apps confusion.** Some teams have separate apps for Ads vs Messaging. Confirm `META_APP_ID` in `.env` points to the **same** app being configured here. If not, decide: consolidate to one app (recommended) or fork ENV vars for WhatsApp (`WHATSAPP_META_APP_ID`).
- **Existing Meta Ads OAuth permissions** may need to be re-reviewed if scopes change. Adding WhatsApp Business Platform product **does not** affect Ads OAuth permissions, but the consolidated App Review flow may require resubmitting Ads permissions alongside.
- **Configuration ID is environment-specific.** Dev and prod can reuse the same ID **only if** the same Meta app serves both environments. If dev uses a separate test app, configure both and document.
- **ngrok URL changes on every restart** (free tier). For sustained dev, use a paid ngrok subdomain or Cloudflare Tunnel with stable hostname.

## Self-check (10 rules)

- [ ] Rule 1: No `core/` ↔ `packs/` imports (no code changes at all).
- [ ] Rule 2: No DB changes.
- [ ] Rule 3: No custom field engine work.
- [ ] Rule 4: No form changes.
- [ ] Rule 5: No sidebar registry change.
- [ ] Rule 6: No permission registry change.
- [ ] Rule 7: `pack.yaml` untouched.
- [ ] Rule 8: 3 files, ~15 lines.
- [ ] Rule 9: Stop and report.
- [ ] Rule 10: No TODOs. The "App Review submission" mentioned is explicitly deferred to Step 4 — not a TODO left in this step.

## Stop & report

```
Step 1 — Meta App configuration & Embedded Signup prerequisites

Files changed:
- API/.env.example — added WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID + WHATSAPP_GRAPH_API_VERSION
- API/src/app/shared/config.py — surfaced the two new env vars
- tasks/whatsapp-platform-upgrade/step-01-meta-app-config.md — recorded outcome

What you can verify:
- Meta App Dashboard → WhatsApp → Configurations shows the new
  "Core CRM Customer Onboarding" configuration with ID: {RESOLVED_ID}
- App Settings → Basic shows configured Privacy/TOS URLs + App Icon
- App Roles → Roles shows at least 1 Tester (the demo account)
- WhatsApp → Webhooks shows subscriptions for messages,
  message_template_status_update, phone_number_quality_update,
  account_review_update
- Business Verification status: VERIFIED (or "in progress" with start date)
- .env.example diff captured
- Core CRM API loads new config without error

Tests added: none — config-only change.

Self-check: 10 rules, all green.

Resolved values (paste back into .env / dev settings):
- WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID = {VALUE}
- WHATSAPP_GRAPH_API_VERSION = v19.0

Next: Step 2 — backend exchange endpoint that converts the ES popup's
authorization code into a long-lived system user token.

Awaiting your "proceed".
```
