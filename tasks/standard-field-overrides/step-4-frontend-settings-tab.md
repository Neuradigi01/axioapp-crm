# Step 4 — Frontend: Settings → Standard Fields tab

**Goal:** Add a new tab to `/user/settings` named "Standard fields" where Owners and Admins (anyone with `settings.standard_fields.manage`) pick an entity, see its standard fields rendered with current overrides, edit the overridable knobs per field, and reset to defaults. Surface clear warnings when hiding NOT-NULL fields or hitting locked knobs.
**Track:** Standard Field Overrides
**Status:** Pending
**Depends on:** Step 3 (render endpoint), Phase 2.5.4 (org settings page tab pattern).

---

## Scope

In-scope:

- New tab `Standard fields` registered alongside `Roles`, `Team`, `Store profile`, `Notifications`, `Integrations`, `AI`. Visible only to users with `settings.standard_fields.manage`.
- Entity selector at the top (dropdown listing the registered entities for the org — fetched from the backend's `/standard-fields/entities` listing, or hardcoded core list initially with a TODO-free fallback if the listing endpoint isn't available; see Risks).
- Per-entity table of fields: columns = `Label`, `Type`, `Required`, `Hidden`, `Min/Max/Step`, `Display order`, `Status` (`Default` vs `Overridden`), action buttons (`Edit`, `Reset`).
- Edit modal: editable inputs **only** for the keys in that field's `overridable_props`; locked knobs are shown disabled with a tooltip explaining why.
- Save → calls `PUT /standard-fields/{entity}/{field_key}` with only the changed properties; the response merges back into the table.
- Reset → calls `DELETE`, removes the override row, refreshes the row to defaults.
- After every successful save, broadcast a `standard-fields:updated` signal on a `StandardFieldsSignalsService` (Angular signal-based event bus) so open modals can refresh — wired up in Step 5/6.
- Warning banners:
  - "This field is enforced by the backend. Hiding it will block create/edit calls unless your integrations supply a value."
  - "This knob is locked by the system and cannot be overridden."

Out of scope:

- No frontend dynamic-form replacement for the existing modals — that's a separate, bigger refactor.
- No bulk-import / export of overrides — single-row editing only.
- No live "preview" of the form on the Settings page (nice-to-have; punt).
- No audit-log viewer for who changed what (audit rows still get written by Step 2; viewer comes in Phase 5.5).

## UI flow

```
/user/settings/standard-fields
┌──────────────────────────────────────────────────────────────────────────┐
│ Standard fields                                                          │
│ Customise the label, required state, visibility, and bounds of the       │
│ canonical fields on each form.                                           │
│                                                                          │
│ Entity:  [ Leads ▼ ]                                                     │
│                                                                          │
│ ┌──────────────────────┬───────────┬──────────┬────────┬──────────────┐  │
│ │ Field                │ Type      │ Required │ Hidden │ Actions      │  │
│ ├──────────────────────┼───────────┼──────────┼────────┼──────────────┤  │
│ │ Pipeline stage       │ select    │ Yes 🔒    │ No 🔒  │ [Edit]       │  │
│ │ Project Budget (₹) ●│ currency  │ Yes      │ No     │ [Edit][Reset]│  │
│ │ Expected close date  │ date      │ No       │ No     │ [Edit]       │  │
│ └──────────────────────┴───────────┴──────────┴────────┴──────────────┘  │
│                                                                          │
│  ● = overridden        🔒 = locked by registry                            │
└──────────────────────────────────────────────────────────────────────────┘
```

Edit modal example for `budget`:

```
┌─ Edit "Budget" (lead.budget) ─────────────────────────────────────────┐
│                                                                       │
│ Label *               [ Project Budget (₹) ............................. ] │
│ Placeholder           [ 0.00 ............................................. ] │
│ Help text             [ ................................................. ] │
│                                                                       │
│ ☑ Required                                                            │
│ ☐ Hidden     ⚠ This field accepts hiding but most reports rely on it. │
│                                                                       │
│ Min          [ 5000        ]   ← numeric only, from registry          │
│ Max          [             ]                                          │
│ Step         [ 1           ]                                          │
│ Display order [ 1 ]                                                   │
│                                                                       │
│           [Cancel]   [Reset to defaults]   [Save changes]             │
└───────────────────────────────────────────────────────────────────────┘
```

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/settings/tabs/standard-fields-tab.component.ts` | created — top-level tab component: entity selector, table, edit-modal trigger. |
| `app/src/app/features/user/core/settings/tabs/standard-fields-tab.component.html` | created — Tailwind table + entity dropdown. |
| `app/src/app/features/user/core/settings/tabs/standard-field-edit-modal.component.ts` | created — modal with reactive form built dynamically from `overridable_props`. |
| `app/src/app/features/user/core/settings/tabs/standard-field-edit-modal.component.html` | created — Tailwind. |
| `app/src/app/features/user/core/standard-fields/standard-fields-api.service.ts` | created — `render(entity)`, `upsert(entity, field_key, payload)`, `reset(entity, field_key)`. |
| `app/src/app/features/user/core/standard-fields/standard-fields-signals.service.ts` | created — root-provided signal/subject the modals subscribe to. |
| `app/src/app/features/user/core/standard-fields/types.ts` | created — TS interfaces matching the backend `StandardFieldRendered` shape. |
| `app/src/app/features/user/core/settings/settings-page.component.ts` | modified — register the new tab in the existing tabs array; gate via permission `settings.standard_fields.manage`. |
| `app/src/app/features/user/core/settings/settings-page.component.html` | modified — add the tab heading + outlet. |

**7 new + 2 modified = 9 frontend files.** At the rule-8 ceiling; do not stretch this step to wire form modals — Step 5 owns that.

## Plan

1. Build the API service. Types match Step 3's response. One method per backend endpoint.
2. Build the signals service. Expose a `changedAt = signal<number>(0)` that bumps on every successful save. Modals in Step 5/6 subscribe via `effect(() => this.signals.changedAt())` and refetch.
3. Build the tab component:
   - `entity = signal<string>('lead')` default.
   - `fields = signal<StandardFieldRendered[]>([])` populated by `render(entity())`.
   - `effect(() => api.render(entity()).subscribe(...))`.
   - Render the Tailwind table with `@for`. Status badge driven by `is_overridden`.
4. Build the edit modal:
   - `@Input() field!: StandardFieldRendered;`
   - Build the reactive form **dynamically** from `field.overridable_props` — only include controls for props in the whitelist. Validators come from the field type (`Validators.required` for `label` if shown; `Validators.min(0)` on numeric inputs).
   - Locked knobs render as disabled inputs with the registry-default value and a 🔒 tooltip.
   - "Reset to defaults" button calls `api.reset(...)`; shown only when `field.is_overridden`.
5. Wire into the Settings page:
   - Add tab to the tabs array with `permission: 'settings.standard_fields.manage'`.
   - Existing settings tab logic already permission-gates entries — just plug in.
6. Manual browser smoke: see below.

## Permission gating

- Tab heading hidden in [settings-page.component.html](../../APP/src/app/features/user/core/settings/settings-page.component.html) unless the user's permission set contains `settings.standard_fields.manage`. Use the same `*hasPermission` pipe / directive the rest of the settings tabs already use.
- Route guard on the tab's deep-link (`/user/settings/standard-fields`) emits the existing 403 / Access Denied flow if hit directly without permission.

## Tests

Frontend tests-per-project-policy are minimal (smoke + manual). Do add:

- A small `standard-fields-api.service.spec.ts` that asserts URL/method/payload shape against `HttpTestingController`. Mirrors the existing `contacts-api.service.spec.ts` style if such files exist; otherwise skip and rely on E2E smoke.

## Smoke (browser)

```
# Backend up, frontend up.
# Sign in as the core-demo Owner.
# Navigate to /user/settings/standard-fields.
# Pick "Leads" entity.

1. Table shows 3 fields: pipeline_stage, budget, expected_close_date.
2. budget row: status "Default". Click [Edit].
3. Change label to "Project Budget (₹)", check "Required", set min to 5000. Click Save.
4. Modal closes; table row now shows ● overridden + label "Project Budget (₹)".
5. Click [Reset]. Row reverts to "Default". Label back to "Budget (₹)".

# Permission check:
6. Log in as Employee (`employee@core-demo`). Navigate to /user/settings.
   Tab heading "Standard fields" must not appear. Visiting the URL directly
   triggers the Access Denied page.

# Locked-knob check:
7. As Owner, edit `contact.full_name`. The "Required" and "Hidden" checkboxes
   render disabled with 🔒 tooltips. Min/Max/Step inputs are absent
   (not in overridable_props for text).
```

## Risks

- **Entity list source:** the dropdown needs the list of overridable entities for the current org. Cleanest source is a small `GET /api/v1/standard-fields/entities` endpoint that lists registered entities — easy to add as a one-line addition to Step 3's router during implementation, or fold into this step if Step 3 is already done. **Decision for the implementer:** if Step 3 didn't ship that listing endpoint, add it as a small addition here rather than hardcoding the entity list in the frontend (Rule 5: registries are server-side).
- **Signal-based refresh cross-feature reach:** the `StandardFieldsSignalsService` will be subscribed to by form modals in Step 5/6. Make sure it's root-provided (`providedIn: 'root'`) so every modal sees the same instance.
- **PUT debouncing:** the Settings UI fires PUT on Save click — *not* on each keystroke. The audit-log spam concern flagged in Step 2 is averted by design.
- **Stale form-modal data:** when an Owner edits a standard field, a colleague's already-open New Lead modal in another tab won't refresh until they close-and-reopen it. Acceptable for v1; full cross-tab WebSocket invalidation is out of scope.
- **Locked-knob mis-rendering:** if the modal accidentally enables a knob outside `overridable_props`, the backend (Step 2) still rejects with 422 — defense in depth. UI bug becomes a clear error toast rather than corrupted state.

## Rollback

Delete the 7 new files. Revert the 2 modified files (remove the tab entry). Settings page returns to its previous tab set. The backend endpoints remain (orphaned but harmless).
