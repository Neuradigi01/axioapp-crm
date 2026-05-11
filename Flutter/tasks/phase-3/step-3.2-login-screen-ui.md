# Step 3.2 — Login Screen UI

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**

**Prerequisites:** Step 3.1

---

**What to do:**
1. Create `lib/features/auth/screens/login_screen.dart` — full login form
2. Create `lib/features/auth/widgets/auth_card_widget.dart` — styled card wrapper for auth screens (wider, well-proportioned)

**Login screen features:**
- Auth card with title "Sign In" and subtitle
- Identifier field (Username or Email) with person icon
- Password field with visibility toggle
- "Remember Me" checkbox
- **CaptchaWidget** — renders correct CAPTCHA type (image/reCAPTCHA v2/v3) based on API config. If CAPTCHA disabled, renders nothing. (Built in Step 2.5)
- "Forgot Password?" link
- "Sign In" button with loading state
- "Don't have an account? Register" link at bottom
- Proper spacing and proportions (card should be wide, not narrow)
- No User/Admin toggle (admin login is separate — per project rules)

**Layout:** Uses AuthLayout shell with centered auth card.

**Verify:**
- [ ] Login form renders with all fields
- [ ] CAPTCHA renders correctly (or hidden if disabled)
- [ ] Password toggle works
- [ ] Form validation shows errors (required fields)
- [ ] Card proportions look good (not too narrow)
- [ ] Links are clickable (navigate to register, forgot password)
- [ ] Both light and dark theme look correct
- [ ] No admin toggle visible

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
