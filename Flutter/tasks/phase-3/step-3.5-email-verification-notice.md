# Step 3.5 — Email Verification Notice Screen

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**

**Prerequisites:** Step 3.4

---

**What to do:**
1. Create `lib/features/auth/screens/email_verification_notice_screen.dart`

**Features:**
- Icon (email/inbox icon)
- Title: "Verify Your Email"
- Message: "A verification email has been sent to [email]. Please check your inbox."
- "Back to Login" button
- If no email in state → redirect to login

**Verify:**
- [ ] Shows correct email address
- [ ] "Back to Login" navigates correctly
- [ ] Redirects to login if accessed directly (no email in state)
- [ ] Looks good in both themes

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
