# Step 2.3 — Form Widgets (Validators, OTP Input, Country/State Picker)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**

**Prerequisites:** Step 2.2

---

**What to do:**
1. Create `lib/utils/validators.dart` — centralized form validators (required, email, minLength, match, mobile)
2. Create `lib/shared/widgets/otp_input_widget.dart` — 6-digit OTP input with auto-focus, paste support, arrow navigation
3. Create `lib/shared/widgets/country_state_picker.dart` — two dropdowns: Country (with search) and State (loads based on country)

**OTP Input:**
- 6 separate TextFields, each for one digit
- Auto-advance to next on input
- Auto-retreat on backspace
- Paste full 6-digit code
- Arrow key navigation
- `onCompleted(String code)` callback

**Country/State Picker:**
- Country dropdown with search/filter
- State dropdown updates when country changes
- `onCountryChanged(Country)` and `onStateChanged(State)` callbacks
- Uses LocationApiService to load data

**Verify:**
- [ ] OTP input auto-advances and handles paste
- [ ] Country picker filters as you type
- [ ] State dropdown reloads when country changes
- [ ] All validators return correct error messages
- [ ] Works in both light and dark theme

---

## Completion

This step is already completed. No action needed.


