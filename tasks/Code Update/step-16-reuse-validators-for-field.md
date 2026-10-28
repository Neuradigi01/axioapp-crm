# Step 16 — Reuse `validatorsForField()` everywhere

**Goal:** Form modals currently hardcode `Validators.email / Validators.required / Validators.maxLength(32)` despite `shared/dynamic-form/validators.ts:11-61` already exposing `validatorsForField()`. Wire them through.
**Track:** Code Update — Frontend Polish
**Depends on:** Step 14 (modals refactored — easier to touch validators consistently)
**Status:** Not started

## Scope
**In-scope:**
- Replace inlined `Validators.email / Validators.required / Validators.maxLength(32)` with `validatorsForField(stdFieldDef)` in form modals.
- For non-dynamic form controls, expose a small `commonValidators` helper in `core/shared/validators/` for email/phone/required/GSTIN/PIN.

**Out of scope:**
- Re-writing the dynamic-form renderer.
- Custom validators that genuinely differ per entity.

## Files to touch
- `core/shared/validators/index.ts` (create — re-exports + common patterns)
- `core/contacts/contact-form-modal.component.ts` (`:122-129, 160-189`)
- `core/leads/lead-form-modal.component.ts`
- `core/tasks/task-form-modal.component.ts`
- `core/appointments/book-appointment-modal.component.ts`

## Plan
1. Audit `validatorsForField()` signature; ensure it covers the cases modals currently hardcode.
2. For each modal, fetch the standard-field def (already loaded by `refreshStdFields()` in Step 14) and call `validatorsForField(def)`.
3. For controls that aren't dynamic (custom controls), use `commonValidators.email`, `commonValidators.phone`, etc.

## DB changes / migrations
None.

## Tests to add
- Spec: form rejects invalid email with the same message as the dynamic-form renderer.

## Verification checklist
- Browser smoke: type invalid email/phone into contact form → see consistent error message.

## Self-check (10 rules)
- [ ] No `Validators.email` literal in modal files (use `commonValidators.email` or `validatorsForField`).

## Stop & report
Files changed · LOC removed · "Awaiting your 'proceed'".
