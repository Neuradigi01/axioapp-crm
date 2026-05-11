# Step 2.3 — Dynamic Form component (frontend)

**Goal:** Reusable `<app-dynamic-form>` Angular component that takes field definitions + values, renders inputs by type, validates per `validation` rules, emits `valueChange` and `validityChange`.
**Phase:** 2
**Depends on:** 2.1
**Status:** Pending

## Scope
**In-scope:**
- New `app/src/app/features/user/core/shared/dynamic-form/`:
  - `dynamic-form.component.ts/.html` — host that builds a typed `FormGroup` from field defs.
  - `field-renderer.component.ts/.html` — switch (`@switch`) rendering the right input per `field_type` (text, number, select, multiselect, date, datetime, boolean, phone, email, currency).
  - `validators.ts` — translates `validation` JSON into Angular validators (min, max, pattern, minLength, maxLength).
- All inputs are Tailwind-styled. No Angular Material, no PrimeNG.
- Two-way: input `(fields, value)`, outputs `(valueChange, validityChange)`. Submit handled by parent.
- Loading skeleton when fields are async.
- Component is **standalone** + signal-input + zoneless-friendly.

**Out of scope:**
- Wiring into Contacts / Leads pages — 2.5, 2.12.

## Files to touch
- `app/src/app/features/user/core/shared/dynamic-form/dynamic-form.component.ts/.html` (created)
- `app/src/app/features/user/core/shared/dynamic-form/field-renderer.component.ts/.html` (created)
- `app/src/app/features/user/core/shared/dynamic-form/validators.ts` (created)
- `app/src/app/features/user/core/shared/dynamic-form/types.ts` (created — `FieldDef`, `FormValue` interfaces)

## Plan
1. `FieldDef` type matches `CustomFieldDefinitionOut` from backend.
2. `dynamic-form.component`: input signals `fields` + `value`. Builds `FormGroup` reactively from fields.
3. `field-renderer`: switch on `field_type`. Currency uses INR formatter. Phone uses simple pattern. Date uses native `<input type="date">` for now; we can swap to a custom picker later.
4. Validation: for each `validation` rule attach the matching Angular validator. `is_required` → `Validators.required`.
5. Emit `valueChange` (debounced 50ms) and `validityChange` whenever the form value changes.
6. Keyboard accessibility (tab order, labels with `for`/`id`, error messages with `aria-describedby`).

## Tests to add
- None (skipTests). Manual smoke: create a Storybook-like demo route `/dev/dynamic-form` (gated by APP_ENV !== prod) showing all field types live.

## Verification checklist
**Frontend:**
- visit `/dev/dynamic-form` (dev demo route) → all 10 field types render and validate live.
- type into number field, leave blank with required → error shows.

## Self-check (10 rules)
- [ ] Rule 4 enforced: no field hardcoded; everything driven by `FieldDef`.
- [ ] No imports from `packs/`.
- [ ] Component standalone, signals-first.

## Stop & report
Await "proceed" before Step 2.4.
