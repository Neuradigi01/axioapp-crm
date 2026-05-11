# Step 2.1 — Core Shared Widgets (Buttons, TextFields, Cards)

> **Status:** COMPLETED

> **Phase 2: Shared Widgets & Layouts**
> Read `Flutter/docs/COMPONENT_REFERENCE.md` — "Shared Widget Library" section.
> Read `Flutter/docs/THEMING_REFERENCE.md` — all colors/spacing must use theme tokens.

**Prerequisites:** Phase 1 complete (Step 1.7)

---

**What to do:**
1. Create `lib/shared/widgets/app_button.dart` — ElevatedButton/OutlinedButton with loading state, full-width option, icon support
2. Create `lib/shared/widgets/app_text_field.dart` — Themed TextFormField with label, prefix/suffix icon, validation error display
3. Create `lib/shared/widgets/password_field.dart` — TextFormField with visibility toggle (eye icon)
4. Create `lib/shared/widgets/app_card.dart` — Styled card container with optional title, subtitle, padding

**AppButton props:**
- `label`, `onPressed`, `isLoading`, `isOutlined`, `isFullWidth`, `icon`, `color`

**AppTextField props:**
- `controller`, `label`, `hint`, `validator`, `prefixIcon`, `suffixIcon`, `obscureText`, `keyboardType`, `maxLines`, `enabled`, `onChanged`

**PasswordField props:**
- `controller`, `label`, `validator` — internally manages visibility toggle

**AppCard props:**
- `title`, `subtitle`, `child`, `padding`, `maxWidth`

**Verify:**
- [ ] Each widget renders correctly in both light and dark theme
- [ ] AppButton shows spinner when `isLoading = true`
- [ ] PasswordField toggles between obscured/visible
- [ ] All use theme tokens (no hardcoded colors/spacing)
- [ ] All have `const` constructors

---

## Completion

This step is already completed. No action needed.


