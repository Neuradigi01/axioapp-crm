# Step 4.2 — Register Screen UI

> **Status:** COMPLETED

> **Phase 4: Authentication — Registration & Password Reset**

**Prerequisites:** Step 4.1

---

**What to do:**
1. Create `lib/features/auth/screens/register_screen.dart`
2. Create `lib/schemas/register_schema.dart` — RegisterRequest DTO

**Register form fields:**
- First Name (required)
- Last Name (required)
- Email (required, email validator)
- Mobile Number (optional, with country code from selected country)
- Password (required, min 8 chars)
- Confirm Password (required, must match)
- Country dropdown (with search) — uses CountryStatePicker from Step 2.3
- State dropdown (loads based on country)
- Referral ID (optional)
- **CaptchaWidget** — renders correct CAPTCHA type (image/reCAPTCHA v2/v3) based on API config. Same widget as login. (Built in Step 2.5)
- "Register" button with loading state
- "Already have an account? Sign In" link

**Layout:** Uses AuthLayout → AuthCard (may need to be scrollable for all fields).

**Verify:**
- [ ] All form fields render correctly
- [ ] CAPTCHA renders correctly (or hidden if disabled)
- [ ] Country picker loads countries on init
- [ ] State picker updates when country changes
- [ ] Password confirmation validates match
- [ ] Form validates all required fields
- [ ] Card is scrollable if content overflows
- [ ] Both themes look correct

---

## Completion

After completing this step and verifying everything works, update the status at the top of this file:

```diff
- > **Status:** PENDING
+ > **Status:** COMPLETED
```

This helps future AI agents quickly identify which steps are done without scanning the codebase.
