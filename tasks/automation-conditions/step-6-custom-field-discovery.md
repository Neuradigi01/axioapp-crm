# Step 6 — Custom field discovery (v1)

**Goal:** When the caller org has custom fields defined on an entity (e.g. an operator created "Deal Size Tier" as a `select` custom field on `lead`), those fields appear in the condition builder's field dropdown automatically for every event whose payload carries the entity's `custom_data`. `select` / `multiselect` custom fields become live-enum dropdowns backed by their stored `options`. Zero-config from the operator's side — they add a custom field under Settings once, it shows up in every relevant automation trigger.
**Status:** Pending (v1 — promoted from Phase-2; no standard CRM ships a filter builder without custom fields in it).
**Depends on:** Step 1 (`FieldSpec` shape) + Step 2 (resolver registry).

---

## Scope

In-scope:

- **Extend `/api/v1/automations/event-types` handler** so that for every entry whose `sample_payload` carries a `custom_data` key on one or more entity dicts (e.g. `lead.custom_data`, `contact.custom_data`), the handler *appends* the org's matching `CustomFieldDefinition` rows to that entry's `condition_fields` at response time.
  - Entity-type mapping is explicit — a small const map inside `event_catalog.py` says which payload paths carry custom_data for which entity_type:
    ```
    _CUSTOM_DATA_MOUNTS = {
        "lead.created": [("lead", "lead.custom_data")],
        "lead.assigned": [("lead", "lead.custom_data")],
        "lead.status_changed": [("lead", "lead.custom_data")],
        "contact.created": [("contact", "contact.custom_data")],
        "contact.birthday": [("contact", "contact.custom_data")],
        "appointment.booked": [("appointment", "appointment.custom_data"), ("contact", "contact.custom_data")],
        ...
    }
    ```
  - The map ships as a code const, not a table (same rationale as the base catalog).
  - Handler flow: for each catalog entry the caller org sees, look up the mount list, query `CustomFieldDefinition` for `(org_id, entity_type in mount_entity_types, is_hidden=false)`, translate each row into a `FieldSpec`, append to the response entry's `condition_fields`.
- **Custom field → FieldSpec translation** (`core/automation/custom_field_bridge.py` — NEW):
  - Path becomes `<mount_path>.<field_key>` (e.g. `lead.custom_data.deal_size_tier`).
  - Label is the definition's `field_label`.
  - Group is `"Lead custom fields"` / `"Contact custom fields"` / etc. — grouped separately so system fields and custom fields render under their own headers, matching HubSpot / Salesforce behavior.
  - Type mapping from `FieldType` enum:
    - `text` / `email` / `phone` → `"text"` (op set includes contains / starts_with / regex).
    - `number` → `"number"`.
    - `currency` → `"currency"`.
    - `date` → `"date"`.
    - `datetime` → `"datetime"`.
    - `boolean` → `"boolean"`.
    - `select` → `"enum"`, `enum_resolver = f"custom_field_options:{entity_type}:{field_key}"`.
    - `multiselect` → `"enum"`, same resolver key (multi-select handled by op choice `in` / `not_in`).
- **Dynamic resolver factory for custom-field option sets** (extends step-2's registry):
  - Register a *catch-all* resolver key prefix `custom_field_options:*` that the registry dispatches to a generic handler:
    - Parses the key → `entity_type`, `field_key`.
    - Looks up the definition row for `(org_id, entity_type, field_key)`.
    - Returns `[EnumOption(value=v, label=l) for v, l in definition.options.get("choices", [])]` — mirrors the wire shape the Settings → Custom Fields editor writes.
  - `EnumResolver` protocol extended with `wildcard: bool` flag so `register_resolver("custom_field_options:*", ..., wildcard=True)` matches any key starting with that prefix.
  - Zero-rows case: a `select` custom field created without options yet → `[]` → frontend renders the same "no options configured" hint as pipeline-stages-empty.
- **Feature flag** — same `automation_conditions.friendly_builder_enabled` gates the customer-field append; when off, the handler returns only the code-declared `condition_fields`.
- **RLS** — the `CustomFieldDefinition` query filters by `org_id` (existing TenantScoped mixin already does this); the resolver query does the same. Two-org fixture test locks it in.
- **Evaluator support** — `conditions.evaluate(...)` already resolves `custom_data.foo` correctly via dot-path (verified in the automation-engine test suite). No engine change needed. One added pin: `test_evaluator_matches_custom_field_value` in this step's test file to prove it end-to-end.
- **Perf** — the handler batches: one `SELECT ... WHERE org_id = :org AND entity_type IN (:types)` reads every needed custom-field row for the whole catalog response in a single trip. Aim for ≤2 DB round-trips added by this step: one for `_CUSTOM_DATA_MOUNTS` entity types + one for any resolver invocations (which happen per field-select, not per catalog-read).
- Pytest — 7 cases (below).

Out of scope:
- Rendering system-and-pack-provided custom fields differently — the catalog already treats them uniformly at this layer; the `source` column distinction stays a Settings-page concern.
- Read/write of custom-field definitions — that's the existing `core/custom_fields/` module.
- Field-values *validation* on save — a customer picking a value that later gets removed from the definition's `options` still saves fine (evaluator returns no-match at runtime; not this step's problem to police).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/automation/custom_field_bridge.py` | **NEW** — translation + `_CUSTOM_DATA_MOUNTS` + handler helper |
| `API/src/app/core/automation/enum_resolvers.py` | edit — wildcard resolver support + `custom_field_options:*` handler |
| `API/src/app/core/automation/service.py` | edit — `list_event_types_service(...)` reads mounts + queries defs + appends specs |
| `API/src/app/core/automation/data_access.py` | edit — `list_custom_fields_for_entities(db, org_id, entity_types)` (batch read) |
| `API/tests/automation/test_custom_field_discovery.py` | **NEW** — 7 pytest cases |

**~5 files. ~350 lines.**

## Plan

1. Bridge module first — pure translation + the mount map. Zero DB.
2. DAL: single-query batch read of the definitions.
3. Wildcard resolver: extend the registry to support prefix matching. Add a step-2-style test that a same-prefix + different callable raises.
4. Service: after the base catalog is assembled, iterate `_CUSTOM_DATA_MOUNTS`, query, translate, append.
5. Verify no N+1 — one SQL log line per full catalog response.
6. Tests + smoke.

## DB changes / migrations

None — reads `tbl_custom_field_definitions`.

## Tests

- `test_catalog_appends_lead_custom_fields_to_lead_created`.
- `test_catalog_hidden_custom_fields_are_excluded`.
- `test_catalog_isolates_org_a_custom_fields_from_org_b`.
- `test_select_custom_field_resolver_returns_stored_options`.
- `test_select_custom_field_with_no_options_returns_empty_list`.
- `test_wildcard_resolver_conflict_raises` — registering two wildcards with same prefix + different callables.
- `test_evaluator_matches_custom_field_value` — end-to-end pin.

## Smoke

```
1. In Ajay's org (Settings → Custom Fields → Lead), create a select field
   "Deal Size Tier" with options ["small", "medium", "large"].
2. Reload /user/automations/new.
3. Event = "Lead created" → Field dropdown has a new "── Lead custom fields ──"
   section with "Deal Size Tier" in it.
4. Pick Deal Size Tier → op dropdown is enum ops.
   Value dropdown fetches → shows [small, medium, large].
5. Pick "large" → save trigger.
6. Manually create a lead with custom_data.deal_size_tier = "large" via API.
7. Publish lead.created via the dev endpoint → automation dispatches. Publish with
   deal_size_tier = "small" → automation does NOT fire.
```

## Risks

- **Custom_data path drift.** If a domain module publishes an event with the entity dict but no `custom_data` key (never happens today for lead/contact/appointment — the ORM always serializes the column), the mount would show fields that resolve to `_MISSING` and never match. Mitigated by a snapshot pin-test that every event listed in `_CUSTOM_DATA_MOUNTS` actually carries the expected `custom_data` key in its `sample_payload`.
- **Custom-field label collision.** An operator names a custom field "Email" on Lead → the dropdown has both "Contact → Email" (system) and "Lead custom fields → Email" (custom). Group separation makes this readable, but the sentence preview shows just the field label — Owner may want to disambiguate. Deferred (label the sentence with the group prefix when there's a collision — post-v1 polish).
- **Perf on orgs with 100+ custom fields.** The response payload grows. Still fine at 100 — each spec is ~200 bytes. If an org somehow crosses 1000, we throw a warning banner "Consider hiding unused custom fields to keep the picker responsive" — but no such org exists today, so this is a note, not code.

## Self-check (10 rules)

`core/automation/`. ✓ org_id scoped. ✓ **Rule 3 satisfied — this IS the custom-fields integration for automation triggers.** ✓ Dynamic form (via catalog). ✓ N/A sidebar. Permissions gated. ✓ pack.yaml untouched (pack custom fields flow through the same table + are picked up here for free). ✓ 5 files / ~350 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 6 — Custom field discovery
Files: 5
Verify: org's custom fields auto-appear in the picker + evaluator matches.
Tests: 7 pytest cases + manual smoke against Ajay's org custom field.
Awaiting "proceed".
```
