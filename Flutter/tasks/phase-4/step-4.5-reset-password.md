# Step 4.5 — Reset Password Screen

> **Status:** COMPLETED

> **Phase 4: Authentication — Registration & Password Reset**

**Prerequisites:** Step 4.4

---

**What to do:**
1. Create `lib/features/auth/screens/reset_password_screen.dart`

**Features:**
- Receives reset token from URL/route parameters
- Title: "Reset Password"
- New Password field (min 8 chars)
- Confirm Password field (must match)
- "Reset Password" button with loading state
- On success: show success message + navigate to login
- On failure: show error message (invalid/expired token)
- If no token in URL → redirect to login

**Verify:**
- [ ] Token extracted from route parameters
- [ ] Password validation (min 8 chars, match)
- [ ] Success navigates to login
- [ ] Error displays message
- [ ] Redirects if no token
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
