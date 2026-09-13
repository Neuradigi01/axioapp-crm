# Step 7b — `POST /events/track` payload validation + contact resolution

**Goal:** add payload validation (types + caps + URL-scheme + enum + regex) and contact resolution (through `contacts.service.create_contact_service()`, `default_owner_user_id` validation, uniform response on hit/miss for enumeration defense).
**Phase:** Custom Events track — step 7b/17
**Depends on:** Step 7a
**Status:** Pending

## Scope

**In-scope:**
- `core/public_ingest/ingest/payload_validator.py`:
  - Look up `tbl_custom_events` row by `event` (auto-add `custom.` prefix via `add_prefix()`).
  - If not found → 400 with actionable message + link to Custom Events page.
  - If `is_active=false` → 400 "event inactive".
  - Validate `properties` against `payload_schema`:
    - Type coercion + range checks.
    - `url` scheme allowlist (HTTPS only; no server-side fetch; length ≤2048).
    - `email` bounded-parser (length ≤254; RFC 5321 non-regex validator).
    - `date` strict ISO-8601 parse.
    - `number` → `Decimal` string preserved.
    - `enum` value must be in declared list.
    - `max_length` per-string cap: 4KB (`string`) / 8KB (`text`).
    - Extra keys stored verbatim.
  - Total payload cap 64KB (413), property count 50, enum cap 50×128.
  - Property names sanitized (`^[a-z][a-z0-9_]{0,63}$`).
- `core/public_ingest/ingest/contact_resolution.py`:
  - `contact_id` provided → validate belongs to `org_id`. Cross-tenant → return `contact_id=None` in resolved state (NOT 400; uniform response).
  - `email` / `phone` provided → normalize (lowercase email, phonenumbers E.164) → lookup in org.
  - Per-identifier throttle (Redis-scoped): same email/phone > 2/min → 429.
  - On miss + `key.auto_create_contacts=true` + `key.mode='live'`:
    - **Call `core.contacts.service.create_contact_service(session, org_id, payload={"email": ..., "source": "event_ingest", "owner_id": key.default_owner_user_id})`.** NEVER direct DAL insert.
    - This routes through blocklists, consent gates, dedup, and publishes `contact.created` on bus (welcome workflows trigger).
    - Validate `key.default_owner_user_id` is active + in-org; on invalid, fall back to round-robin per org config (NEVER Owner).
    - Race handling: wrap in try/except `IntegrityError`; on `(org_id, email)` unique conflict, re-lookup and repoint. Test asserts 2 concurrent unseen-email fires produce 1 contact + 2 occurrences.
  - On miss + `auto_create_contacts=false` OR `mode='test'` → return `contact_id=None`.
  - Uniform response — no side-channel oracle between hit and miss.

**Out of scope:**
- Bus publish + persistence (Step 7c).

## Files to touch
- `core/public_ingest/ingest/payload_validator.py` (new).
- `core/public_ingest/ingest/contact_resolution.py` (new).
- `core/public_ingest/ingest/service.py` (modified — wire both).
- Tests.

## Plan
1. Payload validator (per-type, per-cap).
2. Contact resolution with service-layer routing.
3. Race-handling for concurrent auto-create.
4. Tests.

## Tests to add
- `test_events_track_400_unknown_event`.
- `test_events_track_400_inactive_event`.
- `test_events_track_400_property_type_mismatch`.
- `test_events_track_400_property_name_regex`.
- `test_events_track_413_payload_too_large`.
- `test_events_track_400_property_count_over_50`.
- `test_events_track_400_url_non_https`.
- `test_events_track_400_url_over_2048`.
- `test_events_track_400_email_invalid_bounded_parser`.
- `test_events_track_400_enum_value_not_in_list`.
- `test_events_track_400_enum_over_50_values_at_schema_edit`.
- `test_events_track_400_property_value_over_4kb_string_or_8kb_text`.
- `test_events_track_contact_lookup_by_id_in_own_org`.
- `test_events_track_contact_lookup_cross_tenant_id_uniform_response_no_400` (H1 fix).
- `test_events_track_contact_lookup_by_email_normalized`.
- `test_events_track_contact_lookup_by_phone_e164`.
- `test_events_track_email_miss_auto_creates_via_service_layer_fires_contact_created_bus_event`.
- `test_events_track_email_miss_uses_default_owner_user_id_from_key`.
- `test_events_track_default_owner_invalid_falls_back_to_round_robin_not_org_owner`.
- `test_events_track_email_miss_no_auto_create_when_key_auto_create_contacts_false`.
- `test_events_track_test_key_never_auto_creates_contacts`.
- `test_events_track_uniform_response_on_match_and_miss` (no oracle).
- `test_events_track_per_identifier_throttle_429`.
- `test_events_track_concurrent_auto_create_races_produce_one_contact_two_occurrences`.
- `test_events_track_auto_created_contact_bypasses_domain_blocklist_test` — negative: blocklist should apply because we route through service.
- `test_events_track_auto_created_contact_carries_source_event_ingest_and_created_from_event_id`.

## Verification checklist
- Backend: all tests pass.
- Backend: `contact.created` bus subscribers confirm they fire on auto-create.

## Self-check
- [ ] Rules clean.
- [ ] Rule 8: 4 files — under limit.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
