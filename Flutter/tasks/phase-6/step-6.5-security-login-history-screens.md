# Step 6.5 — Security Screen & Login History Screen

> **Status:** COMPLETED

> **Phase 6: Security, Password & Login History**

**Prerequisites:** Step 6.4

---

**What to do:**
1. Create `lib/features/user/screens/security_screen.dart` — combines 2FA settings + login history
2. Create `lib/features/user/screens/login_history_screen.dart` — standalone login history page

**Security screen layout:**
- Title: "Security Settings"
- Section 1: TFA Settings Widget (from Step 6.2)
- Divider
- Section 2: Recent Login History (last 5 entries, link to full history)

**Login History screen:**
- Title: "Login History"
- Full LoginHistoryTableWidget with pagination
- Standalone page accessible from security page or sidebar

**Verify:**
- [ ] Security page shows both sections
- [ ] "View All" link navigates to full login history
- [ ] Login history page shows full paginated table
- [ ] Both accessible from drawer menu
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
