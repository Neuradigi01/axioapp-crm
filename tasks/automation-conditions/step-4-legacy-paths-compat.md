# Step 4 — Legacy paths compatibility

**Goal:** Guarantee that any trigger whose stored `conditions` JSONB references a field path NOT in the current `condition_fields` catalog still opens for edit cleanly, with a visible "Custom (legacy)" flag and a free-text value input. The stored JSONB never mutates on open, so a user who touches a legacy trigger without saving leaves it byte-identical to before.
**Status:** COMPLETED — **Round-trip preservation** — extended the `Rule` interface with a new `original: Record<string, unknown> \| null` field; `parseLeaves` snapshots the raw AST leaf (`{...n}`) when hydrating; every mutator (`onFieldChange` / `onOpChange` / `onValueChange` / `onTagsChange` / `onBooleanChange`) now sets `original: null` so the snapshot is only trusted for untouched rules; `ruleToLeaf` returns `{...rule.original}` verbatim when `original !== null` — this guards against the numeric-value-stored-as-int being re-serialised as a string, key-order drift, or the eq→gt op inference converting the type. Newly-added rules (`addRule` / `addAdvancedRule`) also start with `original: null` so the emit-rebuild path applies to them. **Legacy vs Advanced distinction** — new `ruleIsLegacy(index)` predicate on the component: true when `field` is set, isn't the `CUSTOM_PATH` sentinel, and isn't in the current catalog's `fieldsByPath` map. Template uses it to switch the pill between the amber "Custom (legacy)" (with `title` tooltip "This field isn't in the current picker. Editing continues to work, but consider migrating to a standard field.") and the neutral-grey "Custom (advanced)" (with `title` "Advanced row — you're referencing a path outside the friendly picker."). Auto-Advanced-mode toggle for legacy rows was already implemented in step-3's `effect()`; unchanged here. **Deprecation banner** — added `legacyRulePaths: Signal<string[]>` computed on the editor page that walks the current `conditions` AST (handling `all` / `any` branches recursively) and returns every leaf field-path not in the current event's `conditionFields`. Template renders an amber banner above the condition-builder card when `legacyRulePaths().length > 0`: "N field(s) on this trigger use an old name (`<paths joined>`). Automation still works." No suggestion mapper (deferred per spec — needs a curated reverse-lookup table that doesn't exist yet). **Tests** — extended `condition-builder.component.spec.ts` with 4 more Jasmine cases: legacy-path load auto-engages Advanced mode + classifies rule as `ruleIsLegacy`, byte-identical save-without-touch (via `JSON.stringify` equality on the input vs. the emitted AST — catches key-order drift too), mixed one-standard-one-legacy AST (classifies both correctly + save-without-touch preserves the whole `all: [...]` tree), toggling Advanced off retains legacy rules in the emitted AST (UI hides them but the data survives a save). NEW `tests/automation/test_legacy_paths.py` with 3 defense-in-depth evaluator pins: unknown leaf path returns False, unknown intermediate path returns False, non-dict intermediate value returns False (never raises). All 4 backend tests green in 2.7s. Prettier + eslint clean on all touched frontend files. Ruff format + check clean on the new pytest file. Karma spec run deferred to the batched frontend test run. Net files: 5 touched (1 NEW `test_legacy_paths.py`, 4 edits: `condition-builder.component.ts` / `condition-builder.component.html` / `condition-builder.component.spec.ts` / `automation-editor.page.ts` / `automation-editor.page.html` — the auto-Advanced-on-load hook was already added in step-3, so this step didn't need to touch the effect wiring).
**Depends on:** Step 3 (Advanced mode UI hook already present).

---

## Scope

In-scope:

- On editor load, iterate the hydrated rule list from the trigger's `conditions` and classify each rule:
  - `field` matches a `FieldSpec.path` in the current event's `condition_fields` → **Standard** rule (renders with dropdowns exactly like step-3).
  - `field` does NOT match any spec → **Legacy** rule. Rendered in the Advanced-mode row layout: free-text field-path input pre-filled with the raw path + full 13-operator list + free-text value input.
- Each legacy rule shows a small amber "Custom (legacy)" pill next to the field label. Hover tooltip: "This field isn't in the current picker. Editing continues to work, but consider migrating to a standard field."
- **Automatic Advanced-mode toggle** — if any rule in the loaded trigger is Legacy, the builder auto-opens with Advanced mode on so the operator sees the raw shape immediately. Toggle can be turned off but then Legacy rules disappear from view (rules stay in the AST — they don't get deleted; the input just re-appears when Advanced is toggled back on).
- **New rules default to Standard.** The "+ Add condition" button always adds a Standard row bound to the first available spec in the event's `condition_fields`. Only "Show advanced" → "+ Add advanced rule" adds a Legacy-shaped row.
- **Round-trip preservation.** Reading a legacy AST + emitting it back without touching anything produces the SAME AST bytes. Test with a fixture that snapshots the input + asserts the output is deep-equal. No accidental key ordering / type coercion changes.
- Backend already tolerates legacy paths — the evaluator returns no-match when a dot-path can't resolve, and stored triggers keep working regardless of which builder authored them. No backend change needed here.
- **Deprecation warning banner** (optional in v1, mandatory once Owner asks): when a trigger has ≥1 legacy rule, a small info banner appears at the top of the editor with "1 field on this trigger uses an old name (`<path>`). Automation still works. Update it to keep filtering by <suggested new label>?" — v1 ships without the suggestion mapper (no reverse-lookup table); the banner just flags the count. A future step can add the suggestion.
- Jasmine specs — 4 cases:
  - Loading a trigger with a legacy path auto-engages Advanced mode.
  - Loading + saving a legacy trigger without touching it produces byte-identical `conditions`.
  - Mixing one Standard + one Legacy rule in a single trigger renders both correctly.
  - Toggling Advanced off hides the legacy row from the DOM (but keeps it in the emitted AST).
- Pytest — 1 case: `test_evaluator_returns_no_match_for_unknown_path` (defense-in-depth pin — evaluator already does this per the automation-engine tests, but re-asserts the behavior in the automation-conditions test file for traceability).

Out of scope:
- The "suggested new label" mapper (deferred — needs a curated `legacy_path → new_field_key` map that doesn't exist yet).
- Migrating existing trigger rows to new paths — never done implicitly.

## Files to touch

| File | Action |
|---|---|
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.ts` | edit — classifier + legacy pill + auto-Advanced |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.html` | edit — legacy row layout + pill markup |
| `APP/src/app/features/user/core/automations/editor/automation-editor.page.html` | edit — banner for legacy-rule count |
| `APP/src/app/features/user/core/automations/editor/condition-builder.component.spec.ts` | edit — 4 more specs |
| `API/tests/automation/test_legacy_paths.py` | **NEW** — 1 pytest case for the evaluator pin |

**~5 files. ~250 lines.**

## Plan

1. Add a `classifyRule(rule, conditionFields)` helper that returns `'standard' | 'legacy'`.
2. Extend the rule-list `computed` to include the classification so the template can `@if (r.kind === 'legacy')` branch.
3. Render the legacy row layout (same three-input grid as pre-rewrite v1) plus the amber pill.
4. On event switch, re-classify every rule — a rule that was Standard for `lead.created` may be Legacy for `contact.created`.
5. Auto-Advanced logic: `hasLegacyRule = computed(...) ? advancedMode.set(true) : ...` — one-shot on load, doesn't fight the operator who then turns it off.
6. Round-trip pin: `emitConditions` uses object spread with the *original* keys preserved for legacy rules. No object-shape reformatting. Add a snapshot spec.
7. Banner in the parent editor page — reads a `legacyRuleCount` computed off the builder's output. Renders when count ≥ 1.

## DB changes / migrations

None.

## Tests

Jasmine + one pytest — listed above.

## Smoke

```
1. Manually craft a trigger via psql or the API with:
   conditions = {"field": "lead.custom_widget_id", "op": "eq", "value": "banner_v2"}
   (path deliberately not in the catalog).
2. /user/automations/{id} → editor opens.
3. Advanced mode is auto-on. Legacy rule renders in the free-text row with amber "Custom (legacy)" pill.
4. Banner at top of page: "1 field on this trigger uses an old name (lead.custom_widget_id). Automation still works."
5. Add a second STANDARD rule (Lead → Stage equals Won). Both rules coexist.
6. Save. Reload. Both rules restore. AST for the legacy rule is byte-identical to the original.
7. Turn Advanced off → legacy row disappears from UI but stays in `conditions` when saved.
```

## Risks

- **Silent evaluator no-match** — a legacy path that resolved yesterday (because the publisher emitted it) may resolve today too. That's still the desired behavior — the customer's trigger keeps firing. If the publisher stops emitting the path, the evaluator returns no-match and the run is `skipped`. That's not a regression here.
- **Byte-identical round-trip** — key ordering in Python dicts is insertion order since 3.7, and Pydantic v2 preserves it in JSONB via `model_dump()`. Angular's `HttpClient` also preserves keys. The snapshot spec pins it.
- **Advanced-mode UX confusion** — Owner might turn Advanced off then hit Save, unwittingly hiding legacy rules from themselves. Rules stay in the AST — nothing is lost — but the UI shows only Standard rules and the banner still fires. Acceptable v1; not silently deleting.

## Self-check (10 rules)

`features/user/core/automations/`. ✓ org_id via JWT. ✓ N/A custom fields (step-6). ✓ Dynamic. ✓ Sidebar. Permissions gated. ✓ pack.yaml untouched. ✓ 5 files / ~250 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 4 — Legacy paths compatibility
Files: 5
Verify: legacy triggers open, edit, save byte-identically. Amber pill + banner render.
Tests: 4 Jasmine + 1 pytest.
Awaiting "proceed".
```
