# Step 2: Backend — schema extension + `create_forwarded_address_endpoint()`

**Status:** Pending

## Goal

Add `auto_create_contact` + `default_assignee_user_id` columns to `tbl_email_endpoint_details`. Endpoint service function to create `forwarded_address` type endpoints with `f-<token>`.

## Files touched

- `api/alembic/versions/0227_forwarded_address.py` — migration
- `api/src/app/core/channel_endpoints/models.py` — extend `EmailEndpointDetails` model
- `api/src/app/core/channel_endpoints/data_access.py` — new function
- `api/src/app/core/channel_endpoints/service.py` — new function + validation
- `api/src/app/core/channel_endpoints/schemas.py` — new schemas
- `api/tests/test_forwarded_address_endpoint.py`

## What this step does

- Migration `0227_forwarded_address`:
  - `ALTER TABLE tbl_email_endpoint_details ADD COLUMN auto_create_contact BOOLEAN NOT NULL DEFAULT true;`
  - `ALTER TABLE tbl_email_endpoint_details ADD COLUMN default_assignee_user_id UUID NULL REFERENCES tbl_users(id) ON DELETE SET NULL;`
  - Index `(default_assignee_user_id) WHERE default_assignee_user_id IS NOT NULL`.
- Model: two new mapped columns.
- DAL: `create_forwarded_address(session, *, org_id, forwarding_token, label, auto_create_contact=True, default_assignee_user_id=None) -> ChannelEndpoint`.
- Service: `create_forwarded_address_endpoint(db, *, org_id, actor_user_id, label, auto_create_contact=True, default_assignee_user_id=None) -> ChannelEndpoint`
  - Owner/Admin only.
  - Validate assignee is in same org.
  - Generate `f-<12chars>` token via `secrets.token_urlsafe(9)[:12]`.
  - Retry on UNIQUE collision, 10 tries.
  - Insert endpoint + details in one transaction.
  - Audit `forwarded_address_endpoint.created`.
- Schemas:
  - `CreateForwardedAddressIn`: `label, auto_create_contact=True, default_assignee_user_id=None`
  - `ForwardedAddressOut`: `id, label, forwarding_address (computed: "f-{token}@{INBOUND_EMAIL_DOMAIN}"), auto_create_contact, default_assignee (id + name), is_active, last_inbound_at, created_at` — token NEVER exposed directly.

## Tests

- `test_migration_adds_auto_create_contact_default_true`
- `test_migration_adds_default_assignee_user_id_nullable_set_null_on_user_delete`
- `test_create_forwarded_address_generates_f_prefixed_token`
- `test_create_forwarded_address_owner_or_admin_only`
- `test_create_forwarded_address_rejects_assignee_from_other_org`
- `test_create_forwarded_address_regenerates_on_token_collision`
- `test_create_forwarded_address_audit_event_written`
- `test_forwarded_address_out_never_exposes_raw_token`

## Verification checklist

- [ ] Migration up + down clean
- [ ] Pin-tests pass
- [ ] Ruff clean
- [ ] All 8 tests pass

## Self-check

- Rule 2: pass — org-scoped.
- Rule 4: pass — Owner/Admin required + assignee validation.
- Rule 8: pass — 6 files.

## Stop-and-report

Report file count, migration revision, test pass. **Awaiting your "proceed" for Step 3.**
