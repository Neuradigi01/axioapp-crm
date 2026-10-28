# Step 3.3 — Login Functionality (API Integration)

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**

**Prerequisites:** Step 3.2

---

**What to do:**
1. Complete `lib/providers/auth_provider.dart` — AuthNotifier with full login logic
2. Wire login screen to AuthNotifier
3. Handle all login response scenarios:
   - Success → save token, navigate to dashboard
   - Requires 2FA → navigate to 2FA screen with temp data
   - Requires email verification → navigate to verification notice
   - Failure → show error message

**Login flow:**
1. Validate form
2. If CAPTCHA active: call `captchaWidget.execute()` to get token (+ answer for image type)
3. Set loading state
4. Call `authApiService.login()` with credentials + captcha data
5. If `success` and no 2FA → save token, save user data, navigate to `/user/dashboard`
6. If `requires2fa` → navigate to `/two-factor` with available methods and temp token
7. If `requiresEmailVerification` → navigate to `/email-verification-notice` with email
8. If failure → show error message via snackbar, **refresh CAPTCHA** (get new image/reset reCAPTCHA)

**Verify:**
- [ ] Login button shows spinner during API call
- [ ] Successful login saves token and navigates to dashboard
- [ ] Failed login shows error snackbar
- [ ] CAPTCHA refreshes on failed login
- [ ] 2FA required navigates to 2FA screen
- [ ] Email verification required navigates to notice screen
- [ ] "Remember me" persists identifier

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
