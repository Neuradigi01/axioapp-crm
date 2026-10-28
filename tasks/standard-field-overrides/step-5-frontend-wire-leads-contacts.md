# Step 5 — Frontend: wire overrides into Leads + Contacts modals

**Goal:** Make `lead-form-modal` and `contact-form-modal` consume the `/standard-fields/{entity}/render` endpoint on open. Apply label, placeholder, help text, required validator, hidden flag, and min/max/step bindings dynamically. Prove the end-to-end loop: an Owner edits Budget's label in Settings → re-opens the New Lead modal → sees the new label.
**Track:** Standard Field Overrides
**Status:** COMPLETED — both modals now consume `/standard-fields/{entity}/render` on open and re-fetch when the `StandardFieldsSignalsService.changedAt` signal bumps (Settings page save/reset). Each binds `label`, `placeholder`, `help_text`, `min/max/step`, and a required asterisk from the rendered defs; HTML5 numeric attrs `[attr.min/max/step]` reflect overrides on Budget. Validators are layered: static shape validators (`Validators.email`, `Validators.maxLength`) stay always-on; `Validators.required` + `Validators.min` + `Validators.max` are reconstructed per fetch off `is_required` / `min_value` / `max_value`. Hidden fields are wrapped in `@if (!isHidden(key))` — the FormControl stays put (cleanest interaction with existing `getRawValue()` paths and `nullableTrim` already handles empty/undefined). Inline error messages added for `required` / `min` / `max` errors on Budget. Implementation deviation from spec: kept FormControls always present rather than removing them when hidden — both behave identically on the wire (empty payload key) and keeping the control simplifies hidden→visible toggling. `tsc --noEmit` clean; `ng build --configuration development` clean.
**Depends on:** Step 3 (render endpoint), Step 4 (Settings tab + signals service).

---

## Scope

In-scope:

- Lead form modal: replace hardcoded `<label>` text, `placeholder`, `required`/`min`/`max`/`step` attributes on the **standard** section (`pipeline_stage`, `budget`, `expected_close_date`) with bindings driven by the rendered defs.
- Contact form modal: same for `full_name`, `phone`, `email`, `source`, `tags`.
- Each modal fetches its entity's render on open via the API service from Step 4. Subscribes to the `StandardFieldsSignalsService.changedAt` signal — if it bumps while the modal is open, refetch and re-apply bindings (rare but the UX is correct).
- Validators are reconstructed when override state changes: for `is_required: true` add `Validators.required`; for numeric fields add `Validators.min(min_value)` / `Validators.max(max_value)` if non-null.
- Hidden fields disappear from the modal entirely (the corresponding FormControl is removed from the FormGroup so submit payloads exclude the key). Defensive: server still enforces NOT NULL where applicable.
- Field order: respect `display_order` from the rendered defs. The existing two-column grid layout is preserved.
- Help text: rendered as a small text below the input when `help_text` is non-null.

Out of scope:

- Walk-ins, Tasks, Appointments, Catalog, Custom Orders, Field Ops — Step 6.
- Replacing the whole modal with a dynamic-form renderer (still keep the HTML structure; just bind the labels/attrs).
- Submission payload changes — the same `LeadCreate` / `ContactCreate` shape goes to the API; the backend continues to accept the same keys (overrides are presentational only, per the README's "What this does NOT do").

## Behavioural contract

Per modal, on `ngOnInit`:

1. Call `standardFieldsApi.render('lead')` (or `'contact'`).
2. Store the rendered defs in a signal `stdFields = signal<Record<string, StandardFieldRendered>>({})`, keyed by `field_key`.
3. Update the FormGroup:
   - For each registered standard field, if `is_hidden=true`, **remove** the control from the FormGroup (if present); otherwise ensure the control exists with the right validators.
   - Validators: `is_required ? Validators.required : null`, plus type-specific (`Validators.email` stays hardcoded on `email`; the backend enforces it regardless), plus `Validators.min(min_value)` / `Validators.max(max_value)` for numeric fields.
4. Subscribe via `effect(() => { this.signals.changedAt(); this.refreshStdFields(); })` so an Owner saving from Settings updates the open modal.
5. Template binds: `[textContent]` on labels, `[attr.placeholder]`, `[attr.min]`, `[attr.max]`, `[attr.step]`, plus `@if (!stdField('budget').is_hidden) { … }` wrappers around each standard-field block.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/leads/lead-form-modal.component.ts` | modified — add `stdFields` signal, fetch on init, dynamic validators, signals subscription. |
| `app/src/app/features/user/core/leads/lead-form-modal.component.html` | modified — replace static label/placeholder/min/etc. with bindings; wrap each std-field block in `@if (!isHidden('budget'))`. |
| `app/src/app/features/user/core/contacts/contact-form-modal.component.ts` | modified — same pattern. |
| `app/src/app/features/user/core/contacts/contact-form-modal.component.html` | modified — same pattern. |

**4 modified files. No new files.**

## Plan

1. In `lead-form-modal.component.ts`:
   - Inject `StandardFieldsApiService` + `StandardFieldsSignalsService` (from Step 4).
   - Add `protected readonly stdFields = signal<Record<string, StandardFieldRendered>>({});`.
   - Add a helper `stdField(key): StandardFieldRendered | undefined => stdFields()[key]`.
   - Add `protected isHidden(key: string): boolean { return !!stdField(key)?.is_hidden; }`.
   - In `ngOnInit`, after the existing custom-fields and pipeline fetches, add:
     ```ts
     this.stdApi.render('lead').pipe(takeUntilDestroyed(this.destroyRef)).subscribe(resp => {
       const map = Object.fromEntries(resp.items.map(f => [f.field_key, f]));
       this.stdFields.set(map);
       this.applyValidators(map);
     });
     effect(() => {
       this.signals.changedAt();
       this.stdApi.render('lead').subscribe(resp => { /* same as above */ });
     });
     ```
   - Add `applyValidators(map)`: for each `(key, def)` in the registered std fields, set validators on `this.standard.controls[key]` based on `is_required` + `min_value` + `max_value`. Re-runs on signal bumps.
2. In `lead-form-modal.component.html`:
   - For each standard field block, wrap with `@if (!isHidden('budget')) { ... }`.
   - Bind label: `{{ stdField('budget')?.label ?? 'Budget (₹)' }}` (the registry default `'Budget (₹)'` is a sane fallback during the brief moment between page open and the render fetch resolving).
   - Bind input attrs: `[attr.placeholder]="stdField('budget')?.placeholder"`, `[attr.min]="stdField('budget')?.min_value"`, `[attr.max]="stdField('budget')?.max_value"`, `[attr.step]="stdField('budget')?.step_value ?? 0.01"`.
   - Render help text under the input: `@if (stdField('budget')?.help_text; as help) { <p class="mt-1 text-xs text-zinc-500">{{ help }}</p> }`.
3. Mirror all of the above for `contact-form-modal`.
4. Manual smoke: see below.

## Smoke (browser)

```
# Backend + frontend up. Sign in as Owner of core-demo.

# A) End-to-end loop — Leads
1. Open /user/settings/standard-fields → Leads → edit Budget
   → label "Project Budget (₹)", required: true, min: 5000 → Save.
2. Navigate to /user/leads → click "+ New lead".
3. Verify: label reads "Project Budget (₹) *", placeholder/min/step honour the override.
4. Try submitting with budget = 100 → form blocks; error message shows.
5. Try submitting with budget = 6000 → form submits cleanly.

# B) Hidden field
6. Settings → Contacts → edit `source` → check Hidden → Save.
7. Navigate to /user/contacts → click "+ New contact".
8. Source input is gone. Submit → succeeds. The created contact has source=null.

# C) Hot refresh while modal open
9. Open New Lead modal.
10. In another tab as the same Owner, edit Budget label to "Total Budget" → Save.
11. Return to first tab — open modal — Budget label is now "Total Budget" (signal fired,
    refetch ran, binding updated).

# D) Permission isolation
12. Sign in as Employee — open New Lead modal — overrides for the org still apply
    (employee called `/render`, which is open to authenticated users).
13. /user/settings/standard-fields not in the sidebar; direct URL → Access Denied.

# E) Reset
14. Settings → Leads → click Reset on Budget → row reverts to Default.
15. Re-open New Lead — label back to "Budget (₹)".
```

## Risks

- **Race on first open:** the render fetch is async. Until it resolves the modal shows registry defaults inlined as the `?? 'Budget (₹)'` fallbacks. That's acceptable (and matches the current hardcoded behaviour). Make sure the validator block runs *after* the fetch — if the user typed something invalid before validators arrived, marking-as-touched on the deferred validator application will surface the error correctly. Briefly tested in smoke step (A.4).
- **FormGroup churn on hidden→shown:** toggling `is_hidden` on a control mid-session removes and later re-adds the control. The current FormGroup `getRawValue()` paths handle missing keys gracefully because `nullableTrim` already guards `null|undefined`. Pin this in smoke step (B.8).
- **Email validator clash:** if an Owner sets `is_required=false` on Contact.email but the schema's `Validators.email` stays applied, an empty string still passes `email` validator (Angular's `Validators.email` treats empty as valid). No conflict.
- **Submission payload shape:** the backend's `ContactCreate` / `LeadCreate` schemas don't change. Hidden fields produce `null`/`undefined` keys in the payload, which the backend already accepts (existing code path).
- **CD strategy:** components are `ChangeDetectionStrategy.OnPush`. Signal-based reads (`stdField('budget')?.label`) re-render correctly because reading a signal in a template registers a dependency. No `markForCheck()` needed.

## Rollback

Revert the 4 modified files. The two modals revert to their hardcoded standard-field block. The backend endpoints and the Settings UI remain in place but no longer feed the modals. The override rows in `standard_field_overrides` remain in the DB harmlessly.
