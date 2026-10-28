# Step 2.6 — Action Verify Dialog (Reusable 2FA)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "Action Verification — Reusable 2FA Interceptor" section.

**Prerequisites:** Step 2.5, Step 1.4 (ActionVerifyInterceptor stub)

---

**What to do:**
1. Create `lib/shared/widgets/action_verify_dialog.dart` — modal 2FA verification dialog
2. Create `lib/core/services/action_verify_service.dart` — orchestrates the dialog flow
3. Create `lib/services/action_verify_api_service.dart` — API calls for action verification
4. Wire into `ActionVerifyInterceptor` from Step 1.4

**ActionVerifyDialog features:**
- Modal dialog (non-dismissable — user must complete or cancel)
- Fetches user's 2FA status (available methods)
- Shows current method: Authenticator / Email OTP / SMS OTP
- For email/SMS: auto-sends OTP on open, shows masked contact
- 6-digit OTP input (OtpInputWidget from Step 2.3)
- "Verify" button with loading state
- "Try another way" → switch method (radio buttons)
- Resend OTP with 30-second cooldown
- "Cancel" button → returns null
- On success: calls `POST /action-verify` with code → returns action_token

**ActionVerifyService:**
- `getActionToken()` → `Future<String?>` — the main entry point called by interceptor
  1. Fetches 2FA status from `GET /2fa/status`
  2. Builds available methods list
  3. Shows ActionVerifyDialog
  4. Returns action_token string or null (if cancelled)

**API endpoints used:**
- `POST /action-verify/send-otp` — send OTP for action verification
- `POST /action-verify` — verify code, returns `{ action_token: "..." }`

**This is what makes 2FA automatic across the app.** The Dio interceptor (from Step 1.4) catches `403 + 2FA_REQUIRED`, calls this service, gets the token, and retries the original request. No screen needs to know about 2FA.

**Verify:**
- [ ] Dialog opens as modal (can't dismiss by tapping outside)
- [ ] Available methods shown based on user's 2FA config
- [ ] OTP auto-sent for email/SMS methods
- [ ] Code verification works
- [ ] Action token returned on success
- [ ] Cancel returns null
- [ ] Interceptor retries request with X-Action-Token header
- [ ] **End-to-end test:** Make an API call that triggers 2FA_REQUIRED → dialog appears → enter code → original request succeeds
- [ ] Both themes correct

---

## Completion

This step is already completed. No action needed.


