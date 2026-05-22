# Standard Field Overrides

A focused side track that gives Owners and Admins the ability to customise the **standard** (DB-column) fields on each form — label, placeholder, help text, required-ness, hidden, and numeric bounds — per org, without code changes and without touching the existing Custom Fields system.

## Why this exists

Today each form modal renders standard fields as hardcoded HTML:

- [lead-form-modal.component.html](../../APP/src/app/features/user/core/leads/lead-form-modal.component.html) — `Budget (₹)`, `Pipeline stage`, `Expected close date`
- [contact-form-modal.component.html](../../APP/src/app/features/user/core/contacts/contact-form-modal.component.html) — `Full name`, `Phone`, `Email`, `Source`, `Tags`
- [task-form-modal.component.html](../../APP/src/app/features/user/core/tasks/task-form-modal.component.html) — `Title`, `Due`, `Priority`, etc.
- … and ten more modals across `core/` and `packs/furniture/`.

The label, required state, min/max, and visibility of these fields are locked at compile time. Custom Fields (Rule 3) covers org-defined *extra* columns via `custom_data` JSONB — it does **not** cover the canonical columns.

For a self-onboardable SaaS, an Owner shipping to an Indian furniture retailer needs to be able to:

- Rename `Budget (₹)` → `Project Budget (₹)`
- Make `Expected close date` required
- Hide `Source` (some orgs don't track lead source)
- Cap `Budget` between ₹0 and ₹50,00,000
- Move "Tags" below "Email"

…all from Settings, with no developer involvement. This track adds that surface.

| Gap | What's missing today |
|---|---|
| **Per-org label / placeholder / help text** | All copy is hardcoded in `*.component.html`. No way to localise or rebrand. |
| **Per-org required-ness** | Validators are hardcoded — `Validators.required` on `full_name`, none on `expected_close_date`. An org wanting a stricter funnel can't add a required gate. |
| **Per-org hide / show** | Every form renders every standard field. No way to hide irrelevant ones (e.g. `Source` for a referral-only business). |
| **Per-org numeric bounds** | `min`, `max`, `step` are baked in (`step="0.01"` on Budget). No way to constrain to integer rupees, or cap below a fraud threshold. |
| **Per-org reordering** | Field order is HTML structural. No way to bubble important fields to the top. |
| **Pack-defined defaults applied at install** | `pack.yaml` already drives furniture defaults for pipeline stages / custom fields / call outcomes (Rule 7). Standard field labels (e.g. relabel `Budget` → `Project Budget`) aren't part of that pipeline. |

## What this does NOT do

- **Does not allow changing a field's data type.** `Budget` stays numeric; `Expected close date` stays a date. Type is tied to the underlying DB column.
- **Does not allow renaming or removing the underlying DB column.** The override is presentational; `field_key` is locked. Removing `budget` from the form would still leave `leads.budget` on the table.
- **Does not allow disabling backend-enforced validators** that protect data integrity. Email format on `contact.email`, FK integrity on `contact_id`, NOT NULL on `lead.contact_id` — all stay enforced server-side. An Owner can hide such a field in the UI but the API will still reject creates that omit it (and the Settings UI surfaces this constraint as a warning).
- **Does not extend to custom fields.** Custom fields already have their own editor at `/user/settings/custom-fields`. This track is the *parallel* surface for standard fields.
- **Does not replace `pack.yaml` for furniture defaults.** A pack can pre-seed override rows on install (e.g. furniture pack writes `{entity: lead, field_key: budget, label: "Project Budget (₹)"}` into `standard_field_overrides` for the new org). Pack manifest stays the source of truth at install time; user edits take over from there.
- **Does not change anything in `features/admin/`** (legacy template admin panel — untouched per CLAUDE.md).
- **Does not introduce a new permission *module*.** Reuses the existing `permissions` registry (Rule 6); adds one new key.

## Acceptance criteria

A new Owner, on a fresh org, can:

1. Open `/user/settings/standard-fields` → see a list of every entity (Leads, Contacts, Walk-ins, Tasks, Appointments, Catalog, Custom Orders, Field Visits).
2. Pick "Leads" → see every standard field (`pipeline_stage`, `budget`, `expected_close_date`) listed with its current label, required state, visibility, bounds.
3. Click **Edit** on `budget` → change label to `Project Budget (₹)`, set `min` to `5000`, mark as `required` → Save.
4. Open the **New lead** modal → the budget field's label reads `Project Budget (₹) *`, refuses submission below `₹5,000`, and refuses to submit blank.
5. Hide `Source` on Contacts → New Contact modal no longer shows the Source input; the underlying DB column stays nullable.
6. An Admin (default role) can do all of the above. An Employee (default role) cannot reach the page (route guard + 403 from API).
7. Customising the furniture pack's labels via this track survives an `apply_pack` re-run — the pack only seeds defaults on **first** install, never overwrites existing override rows.
8. All of the above without restarting the API and without a redeploy.

## Steps

| # | Title | Status | Effort |
|---|-------|--------|--------|
| 1 | [Backend registry of overridable standard fields + permission key](step-1-backend-registry.md) | Done | ~½ day |
| 2 | [Backend `standard_field_overrides` table + CRUD endpoints](step-2-backend-overrides-table-endpoints.md) | Done | ~1 day |
| 3 | [Backend `/standard-fields/{entity}/render` merge endpoint](step-3-backend-render-endpoint.md) | Done | ~½ day |
| 4 | [Frontend Settings → Standard Fields tab](step-4-frontend-settings-tab.md) | Done | ~1 day |
| 5 | [Frontend: wire overrides into Leads + Contacts modals](step-5-frontend-wire-leads-contacts.md) | Done | ~1 day |
| 6 | [Frontend: wire overrides into remaining form modals](step-6-frontend-wire-remaining-entities.md) | Pending | ~1 day |

**Total: ~4–5 working days.** Each step verifiable in under 30 min per Rule 8; pause-and-report per Rule 9.

## Dependencies

- Phase 1.5 (users / roles / permissions schema) — needed for the new permission key.
- Phase 1.7 (audit logs) — Step 2 writes `standard_field_override.updated` events to it.
- Phase 1.8 (module registry) — Step 1's registry plugs into the same composable pattern.
- Phase 2.1–2.3 (custom fields engine + dynamic-form component) — the *parallel* surface; this track does not depend on it but it informs the API/UX shape.
- Phase 2.5.4 (org settings page) — Step 4 adds a new tab next to existing ones.
- Phase 4.1 (pack manifest infrastructure) — only for the *optional* seeding behaviour described in §"What this does NOT do" point 5; not blocking.

## File budget (rough estimate)

| Area | Files | Notes |
|---|---|---|
| Backend Step 1 (registry) | ~2 new + ~1 modified | `core/standard_fields/registry.py` (created), `core/standard_fields/__init__.py` (created), `core/permissions/registry.py` (modified to add `settings.standard_fields.manage`). |
| Backend Step 2 (table + endpoints) | ~5 new + 1 migration | `models.py`, `schemas.py`, `service.py`, `router.py`, `tests/test_standard_field_overrides.py`. |
| Backend Step 3 (render) | ~2 modified | Extends Step 2's `service.py` + `router.py`. |
| Frontend Step 4 (settings tab) | ~3 new + 1 modified | `standard-fields-tab.component.{ts,html}`, `standard-fields.service.ts`, `settings-page.component.html` modified to add the tab. |
| Frontend Step 5 (Leads + Contacts wiring) | ~4 modified | `lead-form-modal.component.{ts,html}`, `contact-form-modal.component.{ts,html}`. |
| Frontend Step 6 (remaining wiring) | ~12 modified | Walk-ins, Tasks, Appointments, Catalog, Custom Orders, Field Ops modals — `.ts` + `.html` pairs. |

**Total ~30 files across 6 steps.** Step 6 hits the rule-8 ceiling (~12 modified) but is mechanical: each modal does the same fetch-and-apply dance. If implementation finds it spreading, split into 6a (core entities) and 6b (pack entities).

## Invariants this track enforces

| Rule | Where enforced |
|---|---|
| `field_key` is immutable | Registry is code-defined (Rule 6 pattern). DB stores `(entity, field_key)` as part of the unique key; the registry rejects unknown `field_key` values at write time. |
| Overrides never lift backend constraints | `standard_field_overrides` only stores presentational + soft validator hints. Hard validators (e.g. `Email` regex on `contact.email`) live in Pydantic schemas and stay enforced server-side regardless of override values. Step 2's service explicitly enforces this. |
| Hiding a NOT NULL field is allowed but flagged | Settings UI shows a warning: "This field is required by the backend. Hiding it will block create/edit unless your integrations supply it." The override is still saved (some orgs may set the value via API/integration only). |
| One override row per `(org_id, entity, field_key)` | DB-level unique constraint. Service upserts via `ON CONFLICT`. |
| Pack-supplied defaults never overwrite user edits | Pack install writes override rows **only if absent** (`INSERT … ON CONFLICT DO NOTHING`). Re-running `apply_pack` against an org with existing overrides is a no-op for this table. |
| `core/` never imports `packs/` | Registry is composed: core registers core fields at startup; pack installers register their own field additions through the same registry pattern (mirrors Phase 1.8 module registry). |
| `org_id` on every row | The `standard_field_overrides` table has `org_id` and is RLS-gated like every other tenant table (Rule 2). |
| Audit log entries on every change | `settings.standard_field_override.updated` audit event on each PUT (Rule from Phase 1.7). |

## Self-check against the 10 rules

- ✅ Rule 1: `core/` never imports `packs/`. Registry is in `core/standard_fields/`; packs register their additions through the same composable function the module registry uses (no reverse imports).
- ✅ Rule 2: New `standard_field_overrides` table carries `org_id`, RLS policy attached in the same migration.
- ✅ Rule 3: Custom fields layered model unaffected; this track is the **parallel** surface for standard columns. The two never share rows.
- ✅ Rule 4: Forms still render from definitions — but a richer definition shape that merges (a) the code-defined registry and (b) per-org overrides. Step 3's `/standard-fields/{entity}/render` endpoint is the analogue of `/custom-fields/{entity}/render`.
- ✅ Rule 5: Sidebar registry unchanged. The new tab plugs into the existing Settings page tab registry.
- ✅ Rule 6: Permissions registry gets one new key (`settings.standard_fields.manage`) registered in `core/permissions/registry.py`. Default-granted to Owner + Admin templates (no change to other templates).
- ✅ Rule 7: `pack.yaml` unaffected as source-of-truth for furniture defaults. Pack installers may *optionally* seed override rows at install time, but the manifest is still the authority.
- ✅ Rule 8: Each step verifiable in under 30 min; Step 6 sits at the boundary and is splittable if needed.
- ✅ Rule 9: Stop-and-report after every step.
- ✅ Rule 10: No TODOs. The "warn when hiding NOT NULL field" UI surface ships in Step 4, not deferred.

## After this track

- Every Owner / Admin can customise every standard field on every form — without code changes.
- The CRM template becomes meaningfully **localisable** per org (label changes for regional differences, currency display, etc.) without touching `i18n` infrastructure.
- The furniture pack can express "Budget" → "Project Budget (₹)" through `pack.yaml` seeding (Phase 4.2 extension, separate small task) without owning the rendering surface.
- The architectural symmetry is clean: **custom fields** = org-defined extra columns; **standard field overrides** = org-defined display of canonical columns. Two registries, one dynamic-form renderer (extended in Step 5 to consume both).
