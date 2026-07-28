# Step 3 — Core entity forms (contacts, leads, walk-ins)

**Goal:** Apply the shared name / email / phone validators to the four modals that create or edit the CRM's primary records — contacts, leads, walk-ins — so invalid values are blocked at the input step before any API call.
**Track:** Application Updates — Form & CSV-Import Validation
**Status:** COMPLETED — contact / lead / lost-reason / walk-in modals all wired to shared validators. Step 1's shared-validator file extended with 4 additional helpers (`numericInRange`, `isoDateValidator`, `isoDateTimeValidator`, `dateNotPastValidator`) since Step 3 was the first consumer; `commonValidators` and the `DEFAULT_MESSAGES` map updated to expose them. Templates gained inline error branches for the new validator keys. Lost-reason modal moved from manual `computed` gating to real `Validators.required` + `withRequiredIf` pattern. tsc + eslint + prettier all clean.
**Depends on:** Step 1 (shared validators).

---

## Scope

Four modal components. Each already builds its form with `FormBuilder` + `commonValidators`; the change is an in-place upgrade to the control array, plus template error-message text.

Files:

1. `app/src/app/features/user/core/contacts/contact-form-modal.component.ts`
2. `app/src/app/features/user/core/leads/lead-form-modal.component.ts`
3. `app/src/app/features/user/core/leads/lost-reason-modal/lost-reason-modal.component.ts`
4. `app/src/app/features/user/core/walk-ins/register-walkin-modal.component.ts`

## Per-form changes

### Contact form modal

| Field | Before | After |
|---|---|---|
| `full_name` | `commonValidators.required`, `commonValidators.maxLength(255)` | `commonValidators.required`, `commonValidators.name`, `commonValidators.maxLength(255)` |
| `phone` | `commonValidators.maxLength(32)` | `commonValidators.phone`, `commonValidators.maxLength(32)` |
| `email` | `commonValidators.email` (Angular's), `commonValidators.maxLength(255)` | `commonValidators.email` (tightened via Step 1), `commonValidators.maxLength(254)` |
| `source` | `commonValidators.maxLength(64)` | unchanged |
| `tags_csv` | (none) | `commonValidators.maxLength(1000)` |

### Lead form modal

Contact-basics block (create mode only) — `full_name`, `phone`, `email`:

| Field | Before | After |
|---|---|---|
| `full_name` | `FormBuilder.control('')` | `['', [Validators.required, commonValidators.name]]` |
| `phone` | `FormBuilder.control('')` | `['', [commonValidators.phone]]` |
| `email` | `FormBuilder.control('')` | `['', [commonValidators.email, commonValidators.maxLength(254)]]` |
| `budget` (standard override) | via `withRequiredIf` | add `Validators.min(0)`, `Validators.max(1_000_000_000)` |
| `pipeline_stage` | required always | unchanged |
| `expected_close_date` | via `withRequiredIf` | add `dateNotPast` cross-field validator (defined in Step 1's frontend validators) |

### Lost reason modal

| Field | Before | After |
|---|---|---|
| `reason` | no validator (computed check) | `Validators.required` |
| `other` | no validator (conditional in code) | `commonValidators.maxLength(500)`; move the "required if reason === 'other'" logic into `withRequiredIf` |

### Register walk-in modal

| Field | Before | After |
|---|---|---|
| `phone` | `Validators.required`, `Validators.maxLength(32)` | `Validators.required`, `commonValidators.phone` |
| `full_name` | `Validators.required`, `Validators.maxLength(255)` | `Validators.required`, `commonValidators.name` |
| `email` | (none) | `commonValidators.email`, `commonValidators.maxLength(254)` |
| `party_size` | (none) | `Validators.min(1)`, `Validators.max(99)` |
| `budget` | (none) | `Validators.min(0)` |
| `wait_started_at` | (none) | ISO datetime pattern (added to Step 1 shared validators) |
| `expected_return_date` | (none) | ISO date pattern |

## Template updates

Each modal template already renders per-control errors. Extend the error-message conditional block to include the new validator keys — `nameInvalid`, `phoneInvalid`, `emailInvalid`, `min`, `max` — with reasons pulled from the `REASON` constants exported by Step 1.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/contacts/contact-form-modal.component.ts` | modified — 4 control changes |
| `app/src/app/features/user/core/contacts/contact-form-modal.component.html` | modified — error messages |
| `app/src/app/features/user/core/leads/lead-form-modal.component.ts` | modified — 5 control changes |
| `app/src/app/features/user/core/leads/lead-form-modal.component.html` | modified — error messages |
| `app/src/app/features/user/core/leads/lost-reason-modal/lost-reason-modal.component.ts` | modified — 2 control changes |
| `app/src/app/features/user/core/leads/lost-reason-modal/lost-reason-modal.component.html` | modified — error messages |
| `app/src/app/features/user/core/walk-ins/register-walkin-modal.component.ts` | modified — 7 control changes |
| `app/src/app/features/user/core/walk-ins/register-walkin-modal.component.html` | modified — error messages |

**~8 files.** Within the per-step rule.

## Tests

If specs exist for these modals, extend them with:

- Contact modal: name with digit rejected; phone with letters rejected; email `"test@"` rejected.
- Lead modal (create): same matrix on the contact-basics fields.
- Lost-reason modal: reason required; `other` bounded to 500 chars.
- Walk-in modal: party_size out of range rejected; phone `"abc"` rejected.

## Smoke

Runs against **Ajay's Workspace** (org `41f9ede9-41b3-44ce-b489-3004566d4068`, Owner `ajaygogane224@gmail.com`) per the seed-target convention:

```
# Frontend
cd app && npx ng test --include='**/contacts/**/*.spec.ts' --include='**/leads/**/*.spec.ts' --include='**/walk-ins/**/*.spec.ts' --watch=false

# Manual browser walk:
# 1. /user/contacts → "New contact" — try name "John123" / email "test@" / phone "abc" → inline errors.
# 2. /user/leads → "New lead" (create branch) → same matrix.
# 3. /user/leads/<id> → drag to Lost → reason picker opens → reason required.
# 4. /user/walk-ins → "Register walk-in" → phone with letters rejected.
# 5. Regression: valid inputs still save cleanly.
```

## Risks

- **Existing rows in DB with garbage data** (from before this step) — untouched. New rows validate; old rows remain as-is until the user edits them, at which point the modal will flag the offending field on load and block save until fixed.
- **Custom fields on the same modal** — validated by Step 1's dynamic-form change; if a custom field is type `email` or `phone`, it now validates identically.

## Rollback

Revert the 8 files.

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`.
- ✅ Rule 2: No DB changes.
- ✅ Rule 3: Custom fields on these modals continue to validate via the dynamic-form path (updated in Step 1).
- ✅ Rule 4: Dynamic-form rendering unchanged.
- ✅ Rule 5: Sidebar unchanged.
- ✅ Rule 6: Permissions unchanged.
- ✅ Rule 7: `pack.yaml` untouched.
- ✅ Rule 8: 8 files, small changes each.
- ✅ Rule 9: Stop-and-report after this step.
- ✅ Rule 10: No TODOs.
