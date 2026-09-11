# Step 5 — `{{event.*}}` handling + pack-event visibility filter

**Goal:** when `event=<name>` is passed to `/variables`, append an `event` group containing ONLY trigger-specific fields not already on entities (transition fields like `event.from_stage_id`, custom-event payload keys). Apply `event_catalog.is_visible_to()` to hide pack events from non-installer orgs.
**Phase:** Variables Unification track — step 5/13
**Depends on:** Step 4
**Status:** Pending

## Scope

**In-scope:**
- `core/variables/service.list_variables()` extended: when `event` param present, compute `event_group_variables`:
  - Read `core/automation/event_catalog._CATALOG[event]`.
  - Filter: entity-payload keys (already surfaced under `contact.*`, `lead.*`, etc.) are OMITTED from `event.*` group — no double-definition.
  - Include: transition-only keys (identified by `event_catalog.condition_fields` entries with `group == 'transition'`), keys not present in any known entity's variable set.
  - For custom events (Track B): read `tbl_custom_events.payload_schema` (once Track B ships; here we add a stub that returns empty for non-catalog events without failing).
- Apply `event_catalog.is_visible_to(entry, caller_org.template_id)` — if False, silently drop event group (log at INFO, not warn); other groups still returned.
- Unknown event names → INFO log + omit event group (don't 400).
- Populate `is_resolvable_here` per path per surface: initial implementation is conservative — chatbot channel returns `is_resolvable_here=false` for `lead.*` and `event.*` (chatbots don't have event context); templates/workflows return `true` for all.

**Out of scope:**
- Custom-events schema lookup (stub only here; real integration in Track B Step 8).
- Frontend rendering of the badge (Step 10a).

## Files to touch
- `api/src/app/core/variables/service.py` (modified — event handling).
- `api/src/app/core/variables/utils.py` (modified — helper `is_entity_payload_key(key, entities)`).
- Tests.

## Plan
1. Read `event_catalog._CATALOG[event]` (if exists). Get `sample_payload` keys.
2. For each key: if key matches any entity's known variable path (`contact.first_name` etc.), skip. Otherwise wrap as `event.<key>` → append to event group.
3. If event is pack-scoped and caller_org.template_id doesn't match, return empty event group + INFO log.
4. If event is unknown to catalog, check custom-events (stub returns empty), then empty event group + INFO log.
5. Compute `is_resolvable_here`: hardcode initial matrix `RESOLVABLE = {("chatbot_runtime", "*"): {contact.*, run.*}, ("*", "*"): {contact.*, lead.*, appointment.*, invoice.*, quote.*, org.*, sender.*, user.*}}`. Refined as follow-up.

## DB changes / migrations
None.

## Tests to add
- `test_variables_endpoint_event_group_omits_entity_payload_duplicates` — `event=lead.status_changed` doesn't duplicate `contact.first_name` under `event.*`.
- `test_variables_endpoint_event_group_contains_transition_fields` — `event.from_stage_id`, `event.to_stage_id` present for `lead.status_changed`.
- `test_variables_endpoint_pack_event_hidden_for_non_installer_org` — org without `template_id='furniture'` calling `event=furniture.custom_order.stage_changed` gets no event group.
- `test_variables_endpoint_pack_event_visible_for_installer_org`.
- `test_variables_endpoint_unknown_event_silently_omits_group` — no 400.
- `test_variables_endpoint_is_resolvable_here_false_for_chatbot_lead_scope`.

## Verification checklist
- Backend: all named tests pass.
- Backend: manual `curl '/variables?entity=lead&channel=email&event=lead.status_changed'` shows event group with only transition fields.
- Backend: manual `curl '/variables?entity=contact&channel=whatsapp&event=nonexistent.event'` returns other groups + no event group.

## Self-check
- [ ] Rules 1-3, 5-7: N/A or clean.
- [ ] Rule 4: N/A.
- [ ] Rule 8: 3 files.
- [ ] Rule 9: stop and report.
- [ ] Rule 10: `is_resolvable_here` initial matrix is hardcoded but not a TODO — refinement is a follow-up track, explicitly named.

## Stop & report
Await "proceed".
