# Step 8.7 — Final Polish & QA Checklist

> **Status:** PENDING

> **Phase 8: Notifications, Popups & Final Polish**

**Prerequisites:** Step 8.6

---

**What to do:**
1. Review all screens in both light and dark theme
2. Test all navigation flows (login → dashboard → profile → security → tickets → logout)
3. Test responsive behavior (mobile, tablet, desktop widths)
4. Verify all loading/error/empty states
5. Verify all form validations
6. Check for hardcoded colors, strings, routes
7. Run `flutter analyze` — fix all lint issues
8. Run `flutter build apk` (Android) to verify build succeeds
9. Remove any placeholder/TODO code
10. Verify all providers are properly disposed (autoDispose where appropriate)

**QA Checklist:**
- [ ] Login → 2FA → Dashboard flow works
- [ ] CAPTCHA renders correctly for all 3 types
- [ ] Registration with OTP + CAPTCHA works
- [ ] Forgot → Reset password flow works
- [ ] Dashboard tiles show correct data
- [ ] Profile view and edit works
- [ ] Profile image upload and remove works
- [ ] Change password works
- [ ] 2FA enable/disable/change works
- [ ] Action verification (reusable 2FA) fires automatically on protected endpoints
- [ ] Login history shows and logout session works
- [ ] Ticket list with filters works
- [ ] Compose ticket with attachments works
- [ ] View ticket with reply works
- [ ] Notifications bell shows count
- [ ] Popup displays on dashboard
- [ ] News feed displays
- [ ] Dynamic menu from API routes works
- [ ] Theme toggle persists
- [ ] Logout clears everything
- [ ] 401 auto-logout works
- [ ] No lint errors
- [ ] Build succeeds
- [ ] Both themes look correct on all screens

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
