# Step 8 — Ask-* nodes: Ask Question + Ask Address + Ask Location + Ask Media

**Goal:** Ship the four question-shaped node types that ask the customer something, wait for the reply, validate + save to a whitelisted target, and expose the captured value downstream as `{{answers.<node_id>}}`.
**Depends on:** Steps 6 (engine), 7 (send methods)
**Status:** Pending

## Scope

**In-scope**
- `nodes/ask_question.py`, `ask_address.py`, `ask_location.py`, `ask_media.py`.
- Save-to logic using the Step 2 `save_target_registry` allow-list.
- Validation per `expected_format`: `text | number | email | phone | date | url | choice` for Ask Question; specialized parsers for Ask Address (street/city/state/postal/country); `{lat, lng}` for Ask Location (from WA location message OR text with a lat,lng regex); file upload via existing `StorageBackend` for Ask Media.
- Retry logic: max_retries (default 2) → send retry message → invalid port after cap.
- Timeout: default 22h → timeout port.
- `{{answers.<node_id>}}` resolver extension in `core/templates/` variable engine.
- Placeholder-contact linkage handling (Case #7): if conversation has no contact, create/reuse a placeholder contact (`is_placeholder=true`).

**Out of scope**
- Action nodes — Step 9.
- CRM-extra nodes — Step 10.

## Files to touch

- `API/src/app/core/chatbots/nodes/ask_question.py` (created)
- `API/src/app/core/chatbots/nodes/ask_address.py` (created)
- `API/src/app/core/chatbots/nodes/ask_location.py` (created)
- `API/src/app/core/chatbots/nodes/ask_media.py` (created)
- `API/src/app/core/chatbots/validators.py` (created — small pure helpers: email, phone via `phonenumbers`, url, date, choice)
- `API/src/app/core/templates/variable_engine.py` (or equivalent — modified — add `answers.*` namespace)
- `API/src/app/core/contacts/service.py` (modified — `get_or_create_placeholder_contact(org_id, external_id, channel)`)

## Plan

1. `ask_question.py`:
   - Send prompt text via channel_bridge (WA or email).
   - Return `NodeResult(park_key=("reply", conversation_id, run_id))`.
   - On resume (via `engine.resume_run` from Step 6): validate reply via `validators.py` per `expected_format`.
   - Valid → save to target via `save_target_registry.write(target, value, run.contact_id, run.lead_id)`; store `answers[node_id] = value`; take `answered` port.
   - Invalid → increment `retry_count` in run's `context`; if `< max_retries`, send `retry_message` and re-park; else take `invalid` port.
   - `expected_format = choice` → also matches against the `choices` list with alias support (Pabbly-style: "yes" / "y" / "yep" all match "yes"); on match, save the canonical choice value.
2. `ask_address.py`:
   - Prompt asks for postal address.
   - Parses reply into `{street, city, state, postal_code, country}` via simple regex + heuristics (US/IN/UK addresses documented; free-form fallback stores raw text).
   - `save_to` must be a JSONB custom field OR five individual field targets (drawn from `save_target_registry`).
3. `ask_location.py`:
   - Prompt asks for location.
   - On WA: accepts an inbound `location` message type → `{lat, lng, name?, address?}`.
   - On text: parses `lat, lng` pair via regex; rejects otherwise.
   - Saves to `custom.location` JSONB by default.
4. `ask_media.py`:
   - Prompt asks for a file/image/video.
   - Inbound WA media message → download via `WhatsAppAdapter.download_media()` (add if missing) → store via existing `StorageBackend` → save `file_id` to target.
   - File-type + size caps (10 MB default, configurable per node).
5. `answers.*` resolver — extend the templates variable engine so `{{answers.<node_id>}}` and `{{answers.<save_to_alias>}}` both resolve. Missing → empty string per existing fallback.
6. Placeholder contact — if inbound event has no linked contact, `get_or_create_placeholder_contact` creates one with the external_id (phone or email), `is_placeholder=true`, and links it to the conversation. Case #7 + #23.

## DB changes / migrations

None (schema pre-provisioned; storage columns exist).

## Tests to add

Location: `API/tests/core/chatbots/test_nodes_ask.py`

- `test_ask_question_park_and_resume` (T22)
- `test_ask_question_save_to_custom_field` (T23)
- `test_ask_question_save_to_sensitive_field_rejected_at_save` (T24)
- `test_ask_question_email_format_validation` (T25)
- `test_ask_question_phone_format_validation`
- `test_ask_question_choice_alias_match`
- `test_ask_question_max_retries_takes_invalid_port` (T25)
- `test_ask_question_timeout_takes_timeout_port` (T26)
- `test_ask_address_parses_us_address`
- `test_ask_address_free_form_fallback`
- `test_ask_location_wa_location_message` (T28)
- `test_ask_location_text_lat_lng_regex`
- `test_ask_media_stores_file_and_saves_file_id` (T29)
- `test_ask_media_size_cap_enforced`
- `test_placeholder_contact_created_for_unknown_number` (T23-adjacent)
- `test_answers_resolver_in_downstream_template`

## Verification checklist

**Backend**
- [ ] Manual test with test-fire: 3-question flow captures name + email + phone into a real contact.
- [ ] Ask Media test-fire uploads a real image to storage; contact.custom.avatar_file_id populated.
- [ ] Ask Location on WA test number resolves lat/lng from a real WA location share.

**Frontend** — N/A.

**Code review**
- [ ] `save_target_registry.write` is the ONLY write path — no direct `db.execute("UPDATE ...")` in node handlers.
- [ ] Placeholder-contact creation is idempotent (repeat calls return the same row).
- [ ] Validators are pure functions (no DB) — kept in `validators.py`.

## Self-check (10 rules)

- [ ] `core` didn't import `packs`
- [ ] `org_id` scoped in every DB write
- [ ] Custom-fields registry usage correct (rule #3)
- [ ] Sidebar/permissions N/A
- [ ] Reuse — reused `StorageBackend`, `phonenumbers`, existing templates variable engine
- [ ] Zero TODOs

## Stop & report

Report the four node handlers' state-machine (send → park → resume → validate → save → advance), a test-fire transcript for a full 3-question flow, and sample rows written to `tbl_contacts.custom_data`. Await "proceed".
