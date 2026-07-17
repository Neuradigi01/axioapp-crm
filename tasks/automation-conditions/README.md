# Automation Conditions — Customer-Friendly Condition Builder

A UX + backend redesign of the automation "Only if" condition builder so **any customer** — not just a developer who knows the payload shape — can safely add conditions to any trigger. Ships alongside `tasks/automation-engine/`; does not block automations from working (v1 free-text builder stays as a fallback for power users).

## Why this track exists

The automation editor at [`APP/src/app/features/user/core/automations/editor/condition-builder.component.ts`](../../APP/src/app/features/user/core/automations/editor/condition-builder.component.ts) currently exposes a raw grid of three inputs per rule:

```
[ e.g. contact.email  ]   [ =  ▾ ]   [ value          ]
```

Customers have to know:

1. That the trigger publishes a field literally named `to_stage` (or `contact.email`, or `lead.budget`).
2. That `eq` means "equals" (the current label is a bare `=` glyph).
3. That "Won" is stored as the lowercase string `won`, not `Won` / `Booked` / `closed_won`.

Miss any one and the condition silently never matches. Zero-error, silent-fail = worst UX outcome. A false start on 2026-07-17 also proved that a hardcoded frontend-only friendly-label map **doesn't scale**: the map didn't cover the org's actual pipeline stage keys, custom field paths, or per-tenant enum values — so users still saw humanised fallbacks like "Foo bar · Baz" for any field the frontend hadn't been individually taught.

The right shape is **backend-driven per-event field metadata**: each event in `event_catalog.py` ships its own `condition_fields` list (label, type, group, enum choices) that the frontend consumes generically. New events add labels once on the backend; every UI branch benefits.

## What it does

- **Per-event `condition_fields` on the backend catalog.** Each catalog entry declares the fields a customer can filter on — path, human label, type (`enum` / `text` / `number` / `currency` / `date` / `boolean`), group (`Contact` / `Lead` / `Appointment` / …), and — for enum fields — the list of allowed values as `{value, label}` pairs.
- **Enum values pulled from live data, not hardcoded**. Pipeline stages come from `tbl_pipeline_stages` for the caller's org; lead sources come from `tbl_lead_sources`; user roles come from the RBAC registry. No stale hardcoded `new / contacted / qualified` list that breaks for orgs with custom stage keys.
- **Frontend condition builder becomes fully data-driven.** Field dropdown, op filter, and value input all read from the catalog response. Zero per-event code on the frontend.
  - Field dropdown groups by `Section · Field` (e.g. `── Contact ──` / `── Lead ──` / `── Lead transition ──`).
  - Op dropdown filtered by field type — text fields hide `>` / `<`, number fields hide `contains` / `regex`, enum fields hide `contains` / range ops.
  - Value input by type — enum → dropdown of the org's live options, currency → number input with symbol prefix, date → date picker, text → free-text.
- **Sentence preview** under the builder in plain English: `Fires when lead transition's new stage is "Won" AND lead's budget is at least ₹50,000.` Customer eyeballs intent before saving.
- **Live matched-events preview.** Below the sentence, a count: `This condition would have matched 3 events in the last 7 days.` Powered by a new `POST /triggers/preview-matches` that scans the trigger-runs history + audit log with the condition applied. Optional Phase 2 — not required for v1 correctness.
- **Backward compatible.** Existing triggers with paths the catalog doesn't declare keep working — the raw path shows as a "Custom (advanced)" option at the bottom of the field dropdown with a free-text value input. Same underlying JSON contract as today's builder.

## What this track does NOT include

- **New condition operators** beyond the 13 already supported by `core/events/conditions.py` (`eq`, `ne`, `in`, `not_in`, `contains`, `starts_with`, `ends_with`, `gt`, `gte`, `lt`, `lte`, `exists`, `not_exists`, `regex`). Adding operators is a separate concern owned by the automation-engine track.
- **Nested condition groups.** The current builder is linear (`all` OR `any` of the leaves). Drag-drop nested rules stay a polish item.
- **Multi-event triggers.** One event per trigger, same as v1.
- **Cross-event conditions** (e.g. "fire when a lead was created AND had an appointment within 7 days"). That's `tasks/workflows/` territory.
- **Custom field discovery.** The catalog only knows about system fields — an org's user-created custom fields (`tbl_custom_field_definitions`) aren't auto-added to the field dropdown. Follow-up task once the shape settles.

## Dependency on automation-engine

This track **assumes** `tasks/automation-engine/` is shipped. The condition builder is a UX layer on top of the trigger editor and its condition-JSON contract. The AST shape (`{field, op, value}` leaves, `{all: [...]}` / `{any: [...]}` branches, `{}` empty = always-match) is inherited and unchanged.

No new tables. No new migrations. The change is a schema extension of the existing `GET /automations/event-types` response and a rewrite of one frontend component.

## Multi-tenancy

- **Catalog + condition_fields are static per-deploy** (no `org_id`). Same for every tenant.
- **Enum value choices are per-org.** Pipeline stages, lead sources, user roles, tags, and custom-field enum values are looked up per-request against the caller's `org_id` via the org's own tables. Never returns cross-tenant data — RLS applies.
- **Matched-events preview counts** are org-scoped to the caller's tenant only.

## Failure modes we deliberately design around

1. **Customer picks an event whose `condition_fields` catalog is empty** → dropdown shows a friendly "This event's payload isn't catalogued yet — use Advanced mode" message + falls back to the raw free-text builder for that event.
2. **Catalog references a field the event's `sample_payload` doesn't have** (drift) → dev-mode warning in the backend logs; UI still shows the field, evaluator returns no-match at runtime.
3. **Enum value pool returns 0 items** (org hasn't seeded any pipeline stages yet) → dropdown shows a "No stages configured — set them up under Settings → Pipelines" link.
4. **Customer edits an old trigger whose stored condition references a field NOT in the catalog** (backwards-compat) → field dropdown pre-selects the raw path with a "Custom (legacy)" flag; op + value revert to free-text so the condition keeps working.

## Sub-tasks

- [step-1-catalog-schema-extension.md](step-1-catalog-schema-extension.md) — extend `CatalogEntry` with `condition_fields: list[FieldSpec]`; declare specs for every event currently in the catalog (lead, contact, appointment, invoice, quote, user, etc.).
- [step-2-live-enum-resolver.md](step-2-live-enum-resolver.md) — `POST /automations/event-types/{event}/field-values?field=<path>` returns the org's live choices for enum fields (pipeline stages, lead sources, user roles, tags, custom-field enum values).
- [step-3-frontend-builder-rewrite.md](step-3-frontend-builder-rewrite.md) — rewrite `condition-builder.component.ts` to consume the catalog + live enum resolver. Field dropdown grouped by section. Op dropdown type-filtered. Value input type-aware. Sentence preview.
- [step-4-legacy-paths-compat.md](step-4-legacy-paths-compat.md) — preserve editing of triggers whose stored condition references paths not in the catalog. "Custom (legacy)" flag + free-text fallback for value.
- [step-5-matched-events-preview.md](step-5-matched-events-preview.md) — optional Phase 2. `POST /triggers/preview-matches` returns count of past runs the condition would have matched; render as a small info line under the builder.
- [step-6-custom-field-discovery.md](step-6-custom-field-discovery.md) — auto-add the org's `tbl_custom_field_definitions` rows to the field dropdown for events whose payload carries `custom_data`.

## Sequencing

`step-1` and `step-2` block `step-3`. `step-3` blocks `step-4`. `step-5` and `step-6` are independent Phase-2 polish tasks that can ship after `step-4` in any order.

Estimated total: ~2–3 days of focused work for steps 1–4 (v1). Steps 5–6 add another 1–2 days.

## Rollback strategy

Every step ships behind a feature flag `automation_conditions.friendly_builder_enabled` (default `false` at rollout, flipped to `true` per-tenant once QA passes). Flipping the flag off reverts to the current free-text builder verbatim — the underlying JSON contract never changed, so stored triggers keep firing regardless of which builder authored them.

## Notes for the AI implementing

- **Do NOT hardcode enum values in the frontend.** Every attempted redesign that hardcodes `new / contacted / qualified / proposal / won / lost` will fail for orgs with custom pipeline stages. Fetch live from the backend.
- **Do NOT ship a partial coverage where some events have friendly labels and others don't.** Either every event in `list_catalog()` gets its `condition_fields` entry, or the feature stays behind the flag until they all do. Half-covered is worse than not-covered because users learn to distrust the picker.
- **Existing triggers keep working with no data migration.** The `conditions` JSONB column shape is unchanged. Any field path that isn't in the new catalog surfaces as a legacy option in the dropdown.
- **Existing pre-existing bug**: `automation-editor.page.ts:selectedEntry` reads `form.controls.event_type.value` inside a `computed()`. FormControl values aren't signals, so the computed doesn't re-fire when the operator picks a new event and `samplePayload()` stays `{}`. Under the current datalist-backed builder this manifests as "no autocomplete suggestions" (survivable). Under any dropdown-only redesign it manifests as "field dropdown is empty forever" (broken). **Fix as part of step-3**: route `event_type.valueChanges` through `toSignal(...)` and read the signal in the `selectedEntry` computed.
