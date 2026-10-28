# Step 8.6 — Logout & Session Management

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.5

---

**What to do:**
1. Ensure logout flow is complete:
   - Call logout API (clears server session + device token)
   - Clear local token + user data
   - Unregister FCM device token
   - Navigate to login screen
   - Clear navigation stack
2. Handle token expiry (401 from interceptor):
   - Clear auth state
   - Navigate to login
   - Show "Session expired" snackbar
3. Handle app resume:
   - On app resume from background, verify token is still valid (optional)

**Verify:**
- [ ] Logout clears everything and navigates to login
- [ ] 401 response auto-logs out with message
- [ ] Cannot navigate back after logout (stack cleared)
- [ ] FCM token unregistered on logout

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
