# Step 14 — `BaseFormModalComponent<T>`

**Goal:** Extract the form-modal scaffolding (form group + field refresh + submit/error signals) duplicated across 5+ entity modals.
**Track:** Code Update — Frontend Foundation
**Depends on:** Step 12 (`BaseApiService<T>`)
**Status:** Not started

## Scope
**In-scope:**
- Create `app/src/app/features/user/core/shared/components/base-form-modal.component.ts` — abstract base providing:
  - Inputs/outputs: `entity / submitting / submitError`, `(save) / (cancel)`
  - Signals: `fieldsLoading / fieldsError / fields`
  - Methods: `refreshStdFields() / applyStandardValidators() / submit()` (template hook)
- Migrate contact, lead, task, walk-in, appointment form modals.

**Out of scope:**
- Visual restyling (Tailwind classes preserved).
- Dynamic-form (custom-fields) renderer — already its own component.

## Files to touch
- `core/shared/components/base-form-modal.component.ts` (create)
- `core/shared/components/base-form-modal.component.spec.ts` (create)
- `core/contacts/contact-form-modal.component.ts` (`:55-180+`)
- `core/leads/lead-form-modal.component.ts` (`:58-150+`)
- `core/tasks/task-form-modal.component.ts`
- `core/walk-ins/register-walkin-modal.component.ts`
- `core/appointments/book-appointment-modal.component.ts`

## Plan
1. Implement abstract component — subclasses provide `entityType: EntityType` and `buildForm()`.
2. Lifecycle: `ngOnInit` → call `refreshStdFields()` → apply validators.
3. Each modal subclass keeps its `buildForm()` (FormBuilder + Validators) and unique field controls; deletes duplicated load/error signals.
4. Confirm parent pages still bind `(save)` / `(cancel)` correctly.

## DB changes / migrations
None.

## Tests to add
- Unit: subclass with mock `buildForm()` mounts, submits, emits `save`.
- Unit: error path sets `submitError` and `submitting=false`.

## Verification checklist
- `ng test` — green.
- `ng build` — clean.
- Browser smoke: create + edit one entity of each type.

## Self-check (10 rules)
- [ ] No duplicated `fieldsLoading / fieldsError / submitError` signals.
- [ ] Each modal still owns its domain-specific validators (no leakage).

## Stop & report
Files changed · LOC removed · Tests added · "Awaiting your 'proceed'".
