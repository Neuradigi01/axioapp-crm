# Step 3 — Frontend condition-builder rewrite (data-driven UI)

**Goal:** Replace the three raw text inputs in `condition-builder.component.ts` with a fully data-driven builder — grouped Field dropdown fed by `condition_fields`, type-filtered Op dropdown, type-aware Value input backed by the live enum resolver for `enum` fields. Adds a plain-English sentence preview under the rule list. Fixes the pre-existing `selectedEntry` signal-tracking bug in `automation-editor.page.ts` — otherwise the field dropdown stays empty when the customer picks a new event.
**Status:** COMPLETED — REWROTE `condition-builder.component.{ts,html}`: new `conditionFields: input<FieldSpec[]>` and `eventType: input<string>` inputs, `computed(groupedFields)` produces `<optgroup>` sections keyed by `FieldSpec.group` in stable GROUP_ORDER (Contact → Lead → Transition → Appointment → Invoice → Order → Quote → User → Org → alphabetical), 14 op choices in a single OP_CATALOG with customer-friendly labels ("Equals" / "Is not" / "Is any of" / "At least" / "At most" / "Is empty" / …), OPS_BY_TYPE map filters the operator dropdown per FieldSpec.type. Type-aware Value input branches — enum + single-select op → `<select>` populated by lazy `POST /field-values` fetch, enum + multi-select op (`in` / `not_in`) → chip tag-picker with resolved labels shown as pills + a dropdown to append tokens, `currency` → `<input type="number">` with a `₹` prefix, `boolean` → Yes/No toggle-button pair, `date` / `datetime` → native pickers, `number` → number input, `text` → text input. Ops that don't need a value (`exists` / `not_exists`) hide the value input. `valuePools` in-session cache keyed by `${eventType}:${fieldPath}` (map signal), `inflightFetches` Set dedupes concurrent requests for the same key, `effect()` on `eventType` clears the cache on event switch. `sentencePreview` computed renders "Fires when <Group>'s <Label> <op sentence> \"<value label>\" AND/OR …" using resolved enum labels (never raw values); currency prepends ₹; number uses `en-IN` locale; boolean uses "Yes" / "No"; zero rules renders "Fires on every matching event." AST emit shape unchanged (`{}` / `{field, op, value}` / `{all:[]}` / `{any:[]}` — locked by the backend evaluator); numeric/currency ops coerce to `Number` before emit, multi-select ops emit `string[]`, boolean coerces to `true`/`false`. "Show advanced" toggle + `addAdvancedRule` for the Advanced-mode fallback (custom field path input + full op list); loaded triggers with a path not in the current catalog auto-engage Advanced mode via an `effect()` hook (step-4 hooks legacy-trigger detection here — the wiring lands in step-3 so the fallback works today for any drift). Empty-catalog fallback renders "This event's payload isn't catalogued yet" panel + "Use Advanced mode" button when `conditionFields` is empty. **FIXED the pre-existing `selectedEntry` signal-tracking bug** in `automation-editor.page.ts` — routed `form.controls.event_type.valueChanges` through `toSignal(...)` with `initialValue: this.form.controls.event_type.value`, then `selectedEntry` computed reads that signal. Also added `conditionFields = computed(() => selectedEntry()?.condition_fields ?? [])` piped into `<app-condition-builder>` alongside the existing `[samplePayload]` (retained for Advanced-mode legacy datalist). Extended `automations-api.service.ts` with `FieldSpecType` union / `FieldSpec` interface / `EnumOption` interface, `EventCatalogEntry` gained `condition_fields: FieldSpec[]`, and `listFieldValues(eventType, field)` fires `POST /event-types/{event}/field-values` (URL-encoded event key). One new lucide icon registered in `app.config.ts`: `ChevronsUpDown` (all others — `AlertTriangle` / `Check` / `Plus` / `X` — already in the pick list; audit clean). NEW `condition-builder.component.spec.ts` — 6 Jasmine cases: grouped `<optgroup>` order, lazy value-fetch fires exactly once, cache-hit deduplication, event-switch cache clear, op filtering by field type (parameterised text/currency/enum), sentence preview with enum labels + AND joiner + ₹ prefix. Extended `automation-editor.page.spec.ts` with 2 more cases pinning the `toSignal` fix (conditionFields updates when event_type changes; selectedEntry re-fires). Prettier `--write` + eslint clean on all 8 touched frontend files; tsc `--noEmit` clean (only pre-existing unrelated `vitest/globals` warning). Currency symbol hardcoded to `₹` — matches every existing India-first CRM default in the app (no OrgSettingsService exists yet for a per-org lookup; documented as a future polish). Karma test run deferred per project convention (batched, matches feedback_pause_before_pytest.md pattern for frontend specs). Net files: 8 touched (1 NEW `condition-builder.component.spec.ts`, 7 edits: `condition-builder.component.ts` (rewrite) / `condition-builder.component.html` (rewrite) / `automation-editor.page.ts` / `automation-editor.page.html` / `automation-editor.page.spec.ts` / `automations-api.service.ts` / `app.config.ts`).
**Depends on:** Step 1 (catalog carries `condition_fields`) + Step 2 (`field-values` endpoint live). Steps 6 + 7 make the picker richer (custom fields + pack events) but the frontend is generic and consumes whatever the backend serves — step-3 ships functional without them.

---

## Scope

In-scope:

- **Rewrite `condition-builder.component.{ts,html}`.** Same public API surface (two-way `conditions` model, `disabled` input), same output AST shape (`{}` / `{field, op, value}` / `{all: [...]}` / `{any: [...]}` — locked by the backend evaluator). Everything else changes:
  - New required input `conditionFields: input<FieldSpec[]>([])` — the catalog's specs for the selected event. Replaces `samplePayload` as the source of truth for the field dropdown. `samplePayload` stays as a fallback ONLY when `conditionFields` is empty (Advanced mode).
  - Field dropdown renders as `<optgroup>` sections keyed by `FieldSpec.group`. Options sorted alphabetically within a group; groups appear in a stable order (`Contact` → `Lead` → `Transition` → `Appointment` → `Invoice` → `Order` → `Quote` → `User` → `Org` → everything else). Each option's label is the `FieldSpec.label` (never the raw path). A `data-path` attribute stores the actual path so the change handler still writes `{field: <path>, ...}` to the AST.
  - **Custom (advanced)** option appears at the bottom of the field dropdown ONLY when Advanced mode is toggled by the operator (a small "Show advanced" link under the last rule). Picking it swaps the row into a free-text field-path + operator + value — the same UI as v1. Reserved for power users and legacy triggers; step-4 hooks legacy-trigger loads into this mode automatically.
  - Op dropdown filtered by `FieldSpec.type`:
    - `text` / `email` / `phone` — `eq, ne, contains, starts_with, ends_with, exists, not_exists, regex, in, not_in`.
    - `number` / `currency` — `eq, ne, gt, gte, lt, lte, exists, not_exists, in, not_in`.
    - `date` / `datetime` — `eq, ne, gt, gte, lt, lte, exists, not_exists`.
    - `boolean` — `eq, ne, exists, not_exists`.
    - `enum` — `eq, ne, in, not_in, exists, not_exists`.
    - Op labels are the customer-friendly strings (`Equals`, `Is not`, `Contains`, `Starts with`, `At least`, `At most`, `Greater than`, `Less than`, `Is any of`, `Is not any of`, `Is empty`, `Is not empty`, `Matches regex`). Internal AST keys unchanged.
  - Value input by type:
    - `enum` (single-select ops — `eq`, `ne`) → single-select `<select>` populated by a lazy fetch from `POST /event-types/{event}/field-values` on first focus / render. In-session cache (see below). Empty pool → placeholder text "No <label>s configured yet — set them up under Settings → …" with a router link.
    - `enum` (multi-select ops — `in`, `not_in`) → tag-picker component (comma-separated tokens rendered as chips) backed by the same value pool. Emits `value: [<v1>, <v2>, ...]`.
    - `boolean` → toggle (`Yes` / `No`).
    - `number` → `<input type="number">`.
    - `currency` → `<input type="number">` with the org's currency symbol prefix (read from `orgSettings.currency` — already exposed by the app-config service).
    - `date` → `<input type="date">`.
    - `datetime` → `<input type="datetime-local">`.
    - `text` / `email` / `phone` → `<input type="text">`.
    - Ops that don't need a value (`exists`, `not_exists`) hide the value input, same as v1.
  - **Field-values in-session cache.** Component holds a `signal<Map<string, EnumOption[]>>()` keyed by `${event_type}:${field_path}`. First lookup fires the POST; subsequent picks of the same field read from cache. Cache cleared when the event changes (event switch → all cached pools invalid). No global cache — instance-scoped so two open editor tabs stay independent.
  - **Sentence preview** below the rule list. One line per rule, joined by "AND" or "OR" (matches the conjunction). Format:
    - `<Group>'s <field label> <op label> "<value label>"` for enum values (uses the resolved `label`, never the raw `value`).
    - `<Group>'s <field label> <op label> <value>` for text / number / currency (currency prepends the symbol).
    - `<Group>'s <field label> exists` / `is empty` for existence ops.
    - Zero rules → "Fires on every matching event."
  - AST emit: unchanged shape. Enum `in` / `not_in` values ship as arrays of the raw `value` strings (never the labels). Numeric ops cast to `Number` before emit (existing behaviour).

- **Fix `automation-editor.page.ts:selectedEntry`.** Route `form.controls.event_type.valueChanges` through `toSignal(...)`, read *that* signal in the `selectedEntry` computed. Also drive a new `conditionFields = computed(() => selectedEntry()?.condition_fields ?? [])` signal and pipe it into the builder. Fixes the "field dropdown empty forever" bug that any dropdown-only builder triggers under the current wire-up.

- **`automation-editor.page.html`** — pass `[conditionFields]="conditionFields()"` into `<app-condition-builder>`. Remove the redundant `[samplePayload]` binding once the builder no longer relies on it for the field list (still passed through for legacy Advanced mode).

- **`automations-api.service.ts`** — add `listFieldValues(event: string, field: string): Observable<EnumOption[]>`. Signal payload matches step-2's endpoint. Reuse the existing retry interceptor (documented in `feedback_http_retry_interceptor.md`).

- **Lucide icon audit** (per `feedback_lucide_icon_registry.md`) — new icons the rewrite needs: `chevrons-up-down` (dropdown chevron), `check` (multi-select tick), `hash` (numeric hint), `calendar` (date input), `toggle-right` (boolean toggle). Add missing ones to `app.config.ts` in the same PR.

- **Prettier + eslint** on every touched frontend file before commit (per `feedback_prettier_on_write.md`).

- **Jasmine specs** — 6 cases in `condition-builder.component.spec.ts`:
  - Field dropdown renders `<optgroup>` for every group present in `conditionFields`.
  - Selecting an `enum` field fires the field-values API exactly once + populates the value dropdown.
  - Cache: selecting the same field twice fires the API once.
  - Switching the event clears the cache.
  - Op dropdown filters correctly by field type (parameterised).
  - Sentence preview renders the expected string for two-rule OR of enum + number.
- 2 cases in `automation-editor.page.spec.ts` — event switch clears the builder's cache signal + repopulates `conditionFields`.

Out of scope:
- Legacy-path handling (step-4).
- Matched-events preview count (step-5).
- Custom-field auto-discovery (step-6 folds into the same catalog response; step-3 just consumes whatever the backend returns).

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.ts` | rewrite |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.html` | rewrite |
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.ts` | edit — `toSignal` fix + `conditionFields` computed |
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.html` | edit — pass `[conditionFields]` |
| `APP/src/app/features/user/core/automations/automations-api.service.ts` | edit — add `listFieldValues` |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.spec.ts` | **NEW** — 6 specs |
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.spec.ts` | edit — 2 more specs |
| `APP/src/app/app.config.ts` | edit — add missing lucide icons |

**~8 files. ~750 lines** — at Rule 8's upper bound; justified because the builder is the primary customer-facing surface of the entire track and can't be split further without shipping a half-working UI.

## Plan

1. Fix the `selectedEntry` signal bug first — smallest change, unblocks every downstream test.
2. Wire the `automations-api.service.ts` method + a typed `EnumOption` interface exported from a `shared/types.ts` (or extend the existing api-types file). This gives the rewrite a stable dependency.
3. Rewrite `condition-builder.component.ts`. Start with the field dropdown + op dropdown; get a single-rule "text `eq` foo" round-tripping the AST.
4. Add value-input branching by type. Boolean + number + date first (no API call); then `enum` (single-select with lazy fetch); then `enum` (multi-select).
5. Add the in-session field-values cache signal.
6. Add the sentence preview `computed(...)`.
7. Advanced mode: wire the "Show advanced" toggle + the raw-input row for Custom (advanced) — the legacy step-4 code path piggybacks on this.
8. Icon audit + prettier + spec suite.
9. Manual smoke against Ajay's org (per `feedback_smoke_test_target_org.md`).

## DB changes / migrations

None — pure frontend + API-consumer change.

## Tests

Jasmine specs listed in Scope. Backend pytest untouched — the endpoint contract lands in step-2.

## Smoke

```
1. Log into Ajay's org (41f9ede9-...) — flag on.
2. /user/automations/new → pick event "Lead created".
3. Field dropdown: opens with sections `── Contact ──` / `── Lead ──` / `── Org ──`.
   Lead → Stage visible.
4. Pick Lead → Stage → op dropdown shows only enum ops (Equals / Is not / Is any of / Is not any of).
5. Value dropdown lazy-fetches → shows Ajay's actual stages (New / Contacted / Showroom Visit / Quotation / Won / Lost).
6. Pick "Won" → sentence preview reads "Fires when Lead's Stage equals \"Won\"."
7. Add a second rule: Lead → Budget → At least → 50000. Preview: "... AND Lead's Budget is at least ₹50,000."
8. Toggle conjunction → preview switches to "OR".
9. Switch event to "Contact created" → builder clears cached options; Lead-only fields disappear from dropdown.
10. Save. Reload. Rules restore identically.
11. Legacy trigger with `field: "lead.some_unknown_path"` still opens for edit (Advanced mode auto-engages via step-4).
```

## Risks

- **Rule 8 file-size cap.** ~750 lines total is at the upper bound. Watchpoints: keep operator-label + group-order maps in a small const file, split the tag-picker into a sibling component if it grows past ~150 lines.
- **Signal-fix regression.** The `toSignal(valueChanges)` change touches how the editor picks up event switches. Manual smoke covers it; the two new page specs pin it.
- **Rendering a huge field dropdown.** Some pack-installed events (step-7) could push the field count past 40. Group headers + alphabetical sort + type-to-search behavior of native `<select>` handle it. A `<datalist>`-backed filter is deferred.
- **Currency symbol.** Reads from `orgSettings.currency` — falls back to `₹` if unset (already the app-config default).

## Self-check (10 rules)

`features/user/core/automations/`. ✓ org_id read from the JWT via the backend endpoints. ✓ N/A custom fields (step-6). Dynamic form ✓ (the builder IS one). ✓ Sidebar already registered. Permissions gate the parent editor page. ✓ pack.yaml untouched. ✓ 8 files / ~750 lines — at Rule 8's upper bound, justified above. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 3 — Frontend condition-builder rewrite
Files: 8
Verify: end-to-end field dropdown + type-aware value input + sentence preview against Ajay's org.
Tests: 8 Jasmine specs.
Awaiting "proceed".
```
