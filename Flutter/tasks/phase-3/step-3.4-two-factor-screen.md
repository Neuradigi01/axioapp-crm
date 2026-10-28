# Step 3.4 — Two-Factor Authentication Screen

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**

**Prerequisites:** Step 3.3

---

**What to do:**
1. Create `lib/features/auth/screens/two_factor_screen.dart` — 2FA verification page

**2FA screen features:**
- Title: "Two-Factor Authentication"
- Shows current method (Authenticator / Email / SMS)
- For email/SMS: shows masked contact info
- Uses `OtpInputWidget` (6 digits, auto-focus, paste support) — built in Step 2.3
- "Verify" button with loading state
- "Try another way" link → shows method selection
- Method selection: radio buttons for available methods (only enabled ones)
- Switching method sends new OTP (for email/SMS)
- Expiry countdown timer (5 minutes)
- Resend OTP button with 30-second cooldown
- Back to login link

**Data received from login:**
- `tempToken` — temporary token for 2FA verification
- `availableMethods` — list of available methods
- `preferredMethod` — default selected method
- `email` (masked), `mobile` (masked)

**Flow:**
1. Enter 6-digit code
2. Call login API again with `twoFactorCode`
3. Success → save token, navigate to dashboard
4. Failure → show error, allow retry
5. "Try another way" → call `tryAnotherWay2fa` API, switch method

**Verify:**
- [ ] OTP input works (auto-advance, paste, arrow keys)
- [ ] Countdown timer shows remaining time
- [ ] Resend button disabled during cooldown
- [ ] Method switching works
- [ ] Successful verification navigates to dashboard
- [ ] Failed verification shows error
- [ ] Back to login clears temp state

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
