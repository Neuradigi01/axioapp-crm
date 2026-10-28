# Step 6.2 — 2FA Settings Widget

> **Status:** COMPLETED

> **Phase 6: Security, Password & Login History**

**Prerequisites:** Step 6.1

---

**What to do:**
1. Create `lib/features/shared/widgets/tfa_settings_widget.dart` — complete 2FA management component

**2FA Settings features:**
- Shows current 2FA status (Enabled/Disabled + method)
- **If disabled:** "Enable 2FA" button → opens setup flow
- **If enabled:** "Change Method" and "Disable 2FA" buttons

**Setup flow (multi-step inline):**
1. **Choose method:** Radio buttons — Authenticator, Email OTP, SMS OTP (only available ones)
2. **For Authenticator:**
   - Call setupAuthenticator API
   - Display QR code image
   - Display secret key (copyable)
   - 6-digit verification input
3. **For Email/SMS:**
   - Call sendSetupOtp API
   - Show masked contact info
   - 6-digit verification input
   - Resend with cooldown
4. **Verify:** Enter code → call verifyAndEnable
5. Success → refresh status, show success message

**Disable flow:**
- Requires action verification first (the Dio interceptor handles this automatically — API returns 403 + 2FA_REQUIRED, interceptor shows dialog)
- After verified → call disable API
- Refresh status

**Change method flow:**
- Same as setup, but after action verification (automatic via interceptor)

**Verify:**
- [ ] Current status displays correctly
- [ ] Authenticator setup shows QR + secret
- [ ] Email/SMS OTP sending works
- [ ] Verification enables 2FA
- [ ] Disable flow with action verification works (interceptor fires automatically)
- [ ] Change method works
- [ ] All loading states handled
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
