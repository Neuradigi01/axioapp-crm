# Step 4.3 — Register Functionality (with OTP Pre-Verification)

> **Status:** COMPLETED

> **Phase 4: Authentication — Registration & Password Reset**

**Prerequisites:** Step 4.2

---

**What to do:**
1. Add `register(RegisterRequest)` method to AuthApiService
2. Add `sendRegistrationOtp(SendOtpRequest)` method to AuthApiService
3. Wire register screen to API
4. Implement OTP pre-verification flow (if enabled by app config)

**Registration flow:**
1. User fills form, clicks Register
2. If pre-registration email verification enabled (from AppConfig):
   - Send OTP to email
   - Show OTP input widget inline
   - User enters OTP
3. If pre-registration SMS verification enabled (from AppConfig):
   - Send OTP to mobile
   - Show OTP input widget inline
   - User enters SMS OTP
4. If CAPTCHA active: call `captchaWidget.execute()` to get token
5. Submit registration with verified OTPs + captcha data
6. Success → show "Registration successful" with user ID, navigate to login
7. Failure → show error message, refresh CAPTCHA

**OTP section (inline):**
- "Verify Email" button sends OTP
- Shows countdown timer
- OTP input appears after sending
- "Resend" with cooldown
- Same pattern for SMS if enabled

**Verify:**
- [ ] Registration without OTP works (when verification disabled)
- [ ] Email OTP flow works (send, input, verify)
- [ ] SMS OTP flow works (send, input, verify)
- [ ] CAPTCHA included in submission
- [ ] Success shows user ID and navigates to login
- [ ] Error messages display correctly
- [ ] Loading states on all buttons

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
