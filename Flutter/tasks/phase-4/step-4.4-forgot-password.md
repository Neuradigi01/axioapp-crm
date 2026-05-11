# Step 4.4 — Forgot Password Screen

> **Status:** COMPLETED

> **Phase 4: Authentication — Registration & Password Reset**

**Prerequisites:** Step 4.3

---

**What to do:**
1. Create `lib/features/auth/screens/forgot_password_screen.dart`

**Features:**
- Title: "Forgot Password"
- Subtitle: "Enter your email or username to receive a password reset link"
- Identifier field (email or username)
- "Send Reset Link" button with loading state
- "Back to Login" link
- On success: show generic success message (prevents email enumeration)
  - "If an account exists with this identifier, a password reset link has been sent."

**Verify:**
- [ ] Form validates required field
- [ ] API call made on submit
- [ ] Generic success message shown (not revealing if account exists)
- [ ] Loading state on button
- [ ] Back to login navigation works
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
