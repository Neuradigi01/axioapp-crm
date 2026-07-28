# Step 2 — Auth pages (accounts/)

**Goal:** Apply the shared validators from Step 1 to all five accounts pages so login, registration, forgot-password, reset-password, and accept-invite enforce industry-standard name / email / phone / password rules with clear inline errors.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** COMPLETED — all 5 accounts forms wired to shared validators; central `DEFAULT_MESSAGES` in `validation-message.component.ts` picks up the new keys so no per-template error strings needed on login/register/forgot/reset; accept-invite gained per-field `<app-validation-message>` blocks (was form-level only); manual `password !== confirm_password` check removed. tsc + eslint + prettier all clean.
**Depends on:** Step 1 (shared validators).

---

## Scope

Five component files under `app/src/app/features/accounts/`. In-place edits — no new files, no logic changes, no template restructuring. Only the `FormBuilder` control definitions and (where applicable) the submit-side error paths change.

Files:

1. `app/src/app/features/accounts/login/login.component.ts`
2. `app/src/app/features/accounts/register/register.component.ts`
3. `app/src/app/features/accounts/forgot-password/forgot-password.component.ts`
4. `app/src/app/features/accounts/reset-password/reset-password.component.ts`
5. `app/src/app/features/accounts/accept-invite/accept-invite.component.ts`

## Per-form changes

### Login

| Field | Before | After |
|---|---|---|
| `identifier` | `Validators.required` | `Validators.required`, `Validators.maxLength(254)` — kept loose because the identifier can be email *or* username. |
| `password` | `Validators.required` | `Validators.required`, `Validators.maxLength(128)` — no strength check on login (existing users may have older passwords). |

### Register

| Field | Before | After |
|---|---|---|
| `first_name`, `last_name` | `Validators.required` | `Validators.required`, `commonValidators.name` |
| `email` | `Validators.required`, `Validators.email` | `Validators.required`, `commonValidators.email`, `Validators.maxLength(254)` |
| `mobile_no` | (no validators) | `commonValidators.phone` — optional at required level, but if present must match |
| `password` | `Validators.required`, `Validators.minLength(8)` | `Validators.required`, `commonValidators.password` |
| `confirm_password` | `Validators.required`, `matchFieldValidator('password')` | unchanged |

Add `matchFieldValidator` at the `FormGroup` level for `confirm_password` (it already exists on the control per the audit, but confirm during implementation).

### Forgot password

| Field | Before | After |
|---|---|---|
| `identifier` | `Validators.required` | `Validators.required`, `Validators.maxLength(254)` |

### Reset password

| Field | Before | After |
|---|---|---|
| `new_password` | `Validators.required`, `Validators.minLength(8)`, `Validators.maxLength(255)` | `Validators.required`, `commonValidators.password` |
| `confirm_password` | `Validators.required`, `matchFieldValidator('new_password')` | `Validators.required`, `Validators.maxLength(128)`, `matchFieldValidator('new_password')` |

### Accept invite

| Field | Before | After |
|---|---|---|
| `first_name` | `Validators.required`, `Validators.maxLength(128)` | `Validators.required`, `commonValidators.name` |
| `last_name` | `Validators.maxLength(128)` | `commonValidators.name` (optional at required level) |
| `phone` | (no validators) | `commonValidators.phone` |
| `password` | `Validators.required`, `Validators.minLength(8)`, `Validators.maxLength(255)` | `Validators.required`, `commonValidators.password` |
| `confirm_password` | `Validators.required` (matched in code) | `Validators.required`, `Validators.maxLength(128)`, `matchFieldValidator('password')` |

Remove the manual `password !== confirm_password` check from `accept-invite.component.ts` submit code — the validator now covers it.

## Template updates

Each form template already renders control errors via `*ngIf="control.errors && control.touched"`. Extend the error-message block to include the new validator keys (`emailInvalid`, `phoneInvalid`, `nameInvalid`, `passwordWeak`) with the reason strings exported from Step 1's `REASON` constants. Keep existing PrimeNG/Material visuals; only text messages change.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/accounts/login/login.component.ts` | modified — 2 control changes |
| `app/src/app/features/accounts/login/login.component.html` | modified — new error messages if needed |
| `app/src/app/features/accounts/register/register.component.ts` | modified — 5 control changes |
| `app/src/app/features/accounts/register/register.component.html` | modified — new error messages |
| `app/src/app/features/accounts/forgot-password/forgot-password.component.ts` | modified — 1 control change |
| `app/src/app/features/accounts/reset-password/reset-password.component.ts` | modified — 2 control changes |
| `app/src/app/features/accounts/reset-password/reset-password.component.html` | modified — error messages |
| `app/src/app/features/accounts/accept-invite/accept-invite.component.ts` | modified — 5 control changes + remove manual match check |
| `app/src/app/features/accounts/accept-invite/accept-invite.component.html` | modified — error messages |

**~9 files.** Within the per-step rule.

## Tests

Frontend specs colocated with each component (extend existing spec files if present):

- Register: submit blocked when name has digit; email `"test@"` rejected; phone `"abc"` rejected; password `"password"` rejected; password mismatch rejected.
- Reset password: weak password rejected; confirm mismatch rejected.
- Accept invite: same matrix.

## Smoke

```
# Frontend
cd app && npx ng test --include='**/features/accounts/**/*.spec.ts' --watch=false

# Manual browser walk:
# 1. /accounts/register — try to submit with:
#    - first_name "John123"       → inline error "name contains disallowed characters"
#    - email "test@"              → inline error "invalid email format"
#    - mobile_no "abc"            → inline error "phone must be 8–15 digits …"
#    - password "password"        → inline error "password must be 8–128 chars …"
#    - password mismatch          → confirm_password shows match error
# 2. /accounts/forgot-password — submit blocked when identifier > 254 chars.
# 3. /accounts/reset-password?token=... — weak password rejected.
# 4. /accounts/accept-invite?token=... — same matrix as register.
# 5. /accounts/login — regression: valid identifier + password logs in as before.
```

## Risks

- **Existing users with weak passwords** cannot log in? — **No.** Strength check runs only on password *creation* / *change*. Login validator only checks presence + max-length. Existing hashes remain valid.
- **Register uses PrimeNG / Material inputs** — validator wiring is framework-agnostic; the change is in `FormBuilder`, not the template. Visual treatment untouched.
- **Regression on captcha or 2FA flow** — those live outside the validator layer. No path touches them.

## Rollback

Revert the 9 files. No downstream code depends on this step.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. Accounts pages are outside both.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom fields not involved.
- ✅ Rule 4: Static registration form — not a custom-field-bearing entity.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 9 files, small changes each.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
