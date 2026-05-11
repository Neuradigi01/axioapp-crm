# Step 3.6 — Email Verification Screen (Token-Based)

> **Status:** COMPLETED

> **Phase 3: Authentication — Login, 2FA & Email Verification**

**Prerequisites:** Step 3.5

---

**What to do:**
1. Create `lib/features/auth/screens/verify_email_screen.dart`

**Features:**
- Receives verification token from URL/deep link query parameter
- On load: calls `authApiService.verifyEmail(token)`
- Shows loading spinner during verification
- Success: shows success message + "Go to Login" button
- Failure: shows error message + "Back to Login" button

**Verify:**
- [ ] Token extracted from route parameters
- [ ] API called on screen load
- [ ] Success/error states display correctly
- [ ] Navigation to login works

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
