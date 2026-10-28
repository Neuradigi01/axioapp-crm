# Step 6.4 — Change Password Page

> **Status:** COMPLETED

> **Phase 6: Security, Password & Login History**

**Prerequisites:** Step 6.3

---

**What to do:**
1. Create `lib/services/change_password_api_service.dart` — change password API
2. Create `lib/features/shared/widgets/change_password_form_widget.dart` — reusable form
3. Create `lib/features/user/screens/change_password_screen.dart` — user's change password page

**Change Password Form widget (shared — reusable):**
- Old Password field
- New Password field (min 8 chars)
- Confirm Password field (must match)
- "Change Password" button with loading state
- `onSubmit(oldPassword, newPassword)` callback
- Success: show success message, clear form
- Error: show error message

**Screen:** Wraps the form in AppFormCard with title "Change Password"

**Verify:**
- [ ] Old password required
- [ ] New password validates min length
- [ ] Confirm password validates match
- [ ] API call on submit
- [ ] Success clears form and shows snackbar
- [ ] Error shows message
- [ ] Both themes correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
