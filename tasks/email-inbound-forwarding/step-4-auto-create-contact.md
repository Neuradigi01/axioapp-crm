# Step 4: Contacts `auto_create_from_email()` + `_persist_inbound_email()` endpoint_type extension

**Status:** COMPLETED (2026-09-21, new `contacts.data_access.insert_minimal_contact` + `contacts.service.auto_create_from_email` with `InvalidFromHeader` exception, pre-check idempotency + IntegrityError fallback for concurrent races, audit `contact.auto_created_from_inbound_email`; `_persist_inbound_email` gains optional `endpoint_type` param stamped into `payload`; `ingest_forwarded.py` replaces the Step-3 `forwarded_awaiting_auto_create` audit stub with the real auto-create call — fail-soft on parse errors; 10 tests in test_contacts_auto_create.py)

## Goal

Auto-create minimal contact from RFC `From:` header when endpoint has `auto_create_contact=True`. Shared helper accepts `endpoint_type` for future extensions.

## Files touched

- `api/src/app/core/contacts/service.py` — new `auto_create_from_email()`
- `api/src/app/core/contacts/data_access.py` — new `insert_minimal_contact()`
- `api/src/app/core/conversations/adapters/email.py` — `_persist_inbound_email()` accepts `endpoint_type` param
- `api/tests/test_contacts_auto_create.py`

## What this step does

- `auto_create_from_email(db, *, org_id, from_header, source='email_forwarded_address') -> Contact`
  - Parse `From: "Name" <email@x>` header via stdlib `email.utils.parseaddr`.
  - `email = email_addr.lower().strip()`. Invalid → raise `InvalidFromHeader`.
  - Split display name: `first_name` = first token, `last_name` = rest (or empty). Preserve unicode.
  - `insert_minimal_contact(session, org_id=..., email=..., first_name=..., last_name=..., source=source)`.
  - Commit + audit `contact.auto_created_from_inbound_email`.
  - Handle race: if UNIQUE(org_id, primary_email) collision, do a SELECT + return existing contact instead of raising.
- `_persist_inbound_email()` new optional param `endpoint_type: str | None = None`. Stamped into `payload.source_reference.endpoint_type`. Behavior branch: `forwarded_address` skips the "unknown-recipient audit" that reply-capture uses on missing sender (forwarded-address always has a valid endpoint → skips that audit).

## Tests

- `test_auto_create_parses_from_header_display_name_and_email`
- `test_auto_create_parses_bare_email_from_header`
- `test_auto_create_lowercases_email`
- `test_auto_create_race_on_unique_email_returns_existing_contact`
- `test_auto_create_invalid_from_raises`
- `test_auto_create_writes_audit_event_with_source`
- `test_auto_create_source_email_forwarded_address_visible_in_attribution`
- `test_persist_helper_stamps_endpoint_type_in_source_reference`
- `test_persist_helper_forwarded_type_skips_unknown_recipient_audit`

## Verification checklist

- [ ] All 9 tests pass
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass — org-scoped.
- Rule 10: pass.
- Reuse: pass — extends existing `_persist_inbound_email` param list.
- DB efficiency: pass — race handled by catching UNIQUE + SELECT existing.

## Stop-and-report

Report file count, test pass. **Awaiting your "proceed" for Step 5.**
