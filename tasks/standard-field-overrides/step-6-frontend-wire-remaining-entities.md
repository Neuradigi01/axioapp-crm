# Step 6 — Frontend: wire overrides into remaining form modals

**Goal:** Apply the same render-and-bind pattern proven in Step 5 to the remaining form modals — Walk-ins, Tasks, Appointments, Catalog, plus the furniture pack modals (Custom Orders, Field Ops). After this step, every form in the app respects the org's standard-field overrides.
**Track:** Standard Field Overrides
**Status:** Pending
**Depends on:** Step 5 (Leads + Contacts wiring as the proven pattern), Step 1's registry covers every modal touched here.

---

## Scope

In-scope: apply Step 5's pattern to:

| Modal | Entity key | File pair |
|---|---|---|
| Register walk-in | `walk_in` | `core/walk-ins/register-walkin-modal.component.{ts,html}` |
| Task create/edit | `task` | `core/tasks/task-form-modal.component.{ts,html}` |
| Book appointment | `appointment` | `core/appointments/book-appointment-modal.component.{ts,html}` |
| Add catalog item | `catalog_item` | `core/catalog/add-item-modal.component.{ts,html}` |
| Custom order create/edit | `custom_order` (pack) | `packs/furniture/custom-orders/custom-order-form-modal.component.{ts,html}` |
| Schedule field visit | `field_visit` (pack) | `packs/furniture/field-ops/schedule-visit-modal.component.{ts,html}` |

For each modal: fetch `render(entity)` on init, bind label/placeholder/help/min/max/step from the result, wrap each std-field block with `@if (!isHidden(key))`, apply dynamic validators based on `is_required` + `min_value` + `max_value`, subscribe to `StandardFieldsSignalsService` for hot refresh.

Out of scope:

- Modals **not** in the list above. Specifically excluded:
  - `core/calls/log-call-modal` — call outcomes are pack-driven (`pack.yaml`), already org-customisable through a different surface.
  - `core/campaigns/create-campaign-modal` — fields are computed from segmentation rules, not "standard CRM fields".
  - `core/reviews/reply-modal` — single textarea, nothing to override.
  - `packs/furniture/inventory/add-product-modal` — pack adds custom fields via its own registry; revisit only if a customer asks.
  - Pipeline editors (`add-stage-popover`, `stage-editor-popover`, `delete-stage-confirm`) — stage management has its own UI.
- No backend changes. Registry from Step 1 already covers these entities (pack entities registered by the furniture pack's installer).
- Pack-entity registrations (`custom_order`, `field_visit`) — if the furniture pack hasn't registered them yet, this step **adds the pack registrations** in `api/src/app/packs/furniture/installer.py` as a small addition. Rule 1 compliant — pack calls `core.standard_fields.register(...)`.

## Files to touch

| File | Action |
|---|---|
| `app/src/app/features/user/core/walk-ins/register-walkin-modal.component.ts` | modified |
| `app/src/app/features/user/core/walk-ins/register-walkin-modal.component.html` | modified |
| `app/src/app/features/user/core/tasks/task-form-modal.component.ts` | modified |
| `app/src/app/features/user/core/tasks/task-form-modal.component.html` | modified |
| `app/src/app/features/user/core/appointments/book-appointment-modal.component.ts` | modified |
| `app/src/app/features/user/core/appointments/book-appointment-modal.component.html` | modified |
| `app/src/app/features/user/core/catalog/add-item-modal.component.ts` | modified |
| `app/src/app/features/user/core/catalog/add-item-modal.component.html` | modified |
| `app/src/app/features/user/packs/furniture/custom-orders/custom-order-form-modal.component.ts` | modified |
| `app/src/app/features/user/packs/furniture/custom-orders/custom-order-form-modal.component.html` | modified |
| `app/src/app/features/user/packs/furniture/field-ops/schedule-visit-modal.component.ts` | modified |
| `app/src/app/features/user/packs/furniture/field-ops/schedule-visit-modal.component.html` | modified |
| `api/src/app/packs/furniture/installer.py` | modified (small) — register `custom_order` and `field_visit` entities' standard fields via the registry. **Skip if already done in Step 1** (decision documented in Step 1 by whoever lands it). |

**12 frontend modified + 1 optional backend modified = up to 13 file deltas.** This is over the rule-8 "split it" ceiling by design — the changes are mechanical mirror-image edits of Step 5. If during implementation the diff feels noisy, split into **6a** (core entities: walk-in, task, appointment, catalog) and **6b** (pack entities: custom-order, field-visit) and stop-and-report between them. The README budget already anticipates this.

## Plan

1. For each pair of `(modal-ts, modal-html)`:
   - Mirror the diff from Step 5's lead modal:
     - Inject `StandardFieldsApiService` + `StandardFieldsSignalsService`.
     - Add `stdFields = signal<Record<string, StandardFieldRendered>>({})`, `stdField(key)`, `isHidden(key)`.
     - Fetch `render(entity)` in `ngOnInit`; apply validators after fetch.
     - Add the `effect()` that re-fetches on signal bumps.
     - Replace label / placeholder / min / max / step literals with bindings; wrap each std-field block in `@if`.
2. After every pair, smoke-test it in the browser before moving to the next (mini stop-and-report internal to this step).
3. (If needed) update `packs/furniture/installer.py` to register the pack-entity standard fields. The registrations themselves declare which knobs are overridable per field; mirror Step 1's core registrations for shape.

## Per-entity standard fields to bind

Best-effort enumeration; actual list comes from the registry. Implementer confirms against Step 1's `register(...)` calls.

| Entity | Std fields the modal currently renders | Notes |
|---|---|---|
| `walk_in` | `customer_name`, `phone`, `email`, `assigned_to`, `interest_category`, `notes` | NOT-NULL on `customer_name` — keep `hidden` locked. |
| `task` | `title`, `due_at`, `priority`, `description`, `related_entity` | `priority` is a fixed enum — `select` knobs only (label, help, display_order). |
| `appointment` | `contact_id`, `scheduled_at`, `duration_minutes`, `assigned_to`, `notes` | `contact_id` locked. |
| `catalog_item` | `sku`, `name`, `category`, `price`, `is_active` | `sku` locked on edit (already enforced via `form.controls.sku.disable()`); registry should reflect with `hidden` locked too. |
| `custom_order` | `customer`, `description`, `estimated_price`, `delivery_date`, `assigned_to` | Pack entity; register in pack installer. |
| `field_visit` | `customer`, `address`, `scheduled_at`, `assigned_to`, `purpose` | Pack entity; register in pack installer. |

## Smoke (browser)

For **each** of the six modals:

```
# Per modal:
1. As Owner, Settings → Standard fields → pick this entity.
2. Edit one field's label → Save.
3. Open the modal in the app → label reflects override.
4. Edit another field → mark Hidden → Save.
5. Re-open the modal → that field is gone.
6. Edit a numeric field's min (if applicable) → Save → modal blocks below-threshold submissions.
7. Reset all overrides → modal reverts to defaults.
```

Also do one cross-entity sanity check:

```
8. As Owner, push 3 overrides across Leads, Contacts, and Walk-ins concurrently
   (via 3 saves in succession). All three corresponding modals reflect the
   correct overrides — no cross-entity leakage.

9. As Employee (no `settings.standard_fields.manage`), open each modal.
   Overrides are applied (employee uses /render, which is open). The Settings
   tab is not visible.

10. Cross-tenant: spin up a second org via signup (per RBAC track Step 1).
    Customise a Lead label in that org. Switch back to core-demo. Confirm the
    core-demo Lead label is unaffected. RLS gate is honoured.
```

## Risks

- **Per-entity bespoke modal layouts:** Walk-ins and Appointments have two-column grids; Custom Orders is a multi-step wizard. The `@if (!isHidden(key))` wrappers may shift grid alignment if the hidden field was in the middle of a row. Acceptable for v1 — orgs hiding mid-row fields accept a minor layout shift. If it becomes a complaint, follow-on work uses CSS grid `display: contents` shims.
- **Custom Orders wizard step counts:** if an Owner hides every field in one step, the wizard's step navigation should still skip that step (or show an "all fields hidden — skipping" notice). Implementer makes the call at edit time; if it gets non-trivial, file a follow-on issue and ship the simpler "hidden fields disappear but step remains" behaviour.
- **Pack-installer registration ordering:** the pack registers `custom_order` / `field_visit` standard fields during pack install (which only runs on first install of the pack against an org). On orgs where the pack is **already installed** before this step ships, the registrations need to run on app startup too. Mitigation: the pack's startup hook registers the field defs (idempotent — registry is a dict; same key overwrites with same value), independent of the per-org install side effects. Step 1's main.py-import pattern carries over.
- **File count near rule-8 ceiling:** if implementation diff grows past ~400 LOC or the diff feels rushed, split into 6a/6b at the natural seam (core vs pack). Spelled out in Files-to-touch note above.
- **One modal not having a standard section:** `custom-order-form-modal` is a wizard — confirm during implementation that its standard fields all live in a single `<section>` block. If they're scattered across wizard steps, mirror the pattern per step (each step has its own subset of the `stdFields` map filtered to relevant keys).

## Rollback

Revert the touched modal files. The Settings page (Step 4) and the backend remain functional for Leads + Contacts (Step 5). Override rows in the DB stay; modals just stop reading them. Pack-installer changes (if made) revert with the file.
