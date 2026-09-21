# Step 2: Backend — `core/channel_endpoints/` module (schemas, DAL, service, router)

**Status:** COMPLETED (2026-09-21) — schemas + DAL + service + router shipped; router wired under `/api/v1/channel-endpoints` with Owner+Admin `email.accounts.manage` gate; OpenAPI schema clean; import smoke passes (2 routes registered end-to-end).

## Goal

Complete the layered module for `channel_endpoints`: schemas, DAL, service, router. Owner+Admin-only admin-overview endpoint. No caller wires in yet.

## Files touched

- `api/src/app/core/channel_endpoints/schemas.py`
- `api/src/app/core/channel_endpoints/data_access.py`
- `api/src/app/core/channel_endpoints/service.py`
- `api/src/app/core/channel_endpoints/router.py`
- `api/src/app/main.py` — register router under `/api/v1/channel-endpoints`
- `api/tests/test_channel_endpoints_dal.py`
- `api/tests/test_channel_endpoints_service.py`

## What this step does

- Schemas: `ChannelEndpointOut`, `EmailEndpointDetailsOut`, `ChannelEndpointListOut`. No create/update schemas yet — creation is per-endpoint-type in later steps (Track 3 for `forwarded_address`, Track 2 for `oauth_mailbox` new-flow).
- DAL functions:
  - `find_by_reply_token(session, *, token) -> tuple[ChannelEndpoint, EmailEndpointDetails] | None`
  - `find_by_forwarding_token(session, *, token) -> tuple[ChannelEndpoint, EmailEndpointDetails] | None`
  - `find_active_for_org(session, *, org_id, endpoint_type=None) -> list[tuple[ChannelEndpoint, EmailEndpointDetails]]`
  - `create_smtp_reply_capture(session, *, org_id, smtp_sender_id, reply_token, label) -> ChannelEndpoint` — regenerates token on UNIQUE collision, up to 10 tries
  - `create_oauth_mailbox(session, *, org_id, oauth_account_id, label) -> ChannelEndpoint`
  - `deactivate(session, *, endpoint_id) -> None`
  - `soft_delete_orphans_older_than(session, *, cutoff_dt) -> int`
- Service:
  - `list_endpoints_for_org(db, *, org_id, endpoint_type=None) -> list[schemas.ChannelEndpointOut]`
  - `deactivate_endpoint(db, *, org_id, endpoint_id, actor_user_id) -> None` — permission check (Owner+Admin), row-lock, audit event `channel_endpoint.deactivated`.
  - Owns transactions per layered convention.
- Router (Owner+Admin only):
  - `GET /api/v1/channel-endpoints?endpoint_type=<x>` — list org's endpoints
  - `POST /api/v1/channel-endpoints/{id}/deactivate` — deactivate
- Never exposes tokens in responses — schemas explicitly `exclude={"forwarding_token","reply_token"}` on the details out-schema.

## Tests

- `test_find_by_reply_token_returns_endpoint_and_details`
- `test_find_by_reply_token_returns_none_on_missing`
- `test_find_by_reply_token_returns_none_on_inactive_endpoint`
- `test_find_by_forwarding_token_returns_tuple`
- `test_create_smtp_reply_capture_regenerates_on_token_collision`
- `test_deactivate_endpoint_requires_owner_or_admin`
- `test_deactivate_endpoint_writes_audit_event`
- `test_list_endpoints_scoped_by_org`
- `test_list_endpoints_never_leaks_token_values`
- `test_soft_delete_orphans_only_older_than_cutoff`

## Verification checklist

- [ ] Pin-tests pass
- [ ] Router → Service → DAL enforced — service is the only layer calling `db.commit/refresh`
- [ ] Router never calls `db.execute` / DAL directly
- [ ] Ruff clean
- [ ] All 10 named tests pass

## Self-check

- Layered: pass — DAL is pure CRUD, service owns transactions, router owns HTTP.
- Rule 4 (permissions): pass — Owner+Admin required at service layer.
- Rule 8 (small step): pass — ~7 files.
- Rule 10: pass.

## Stop-and-report

Report files changed, DAL functions added, test results. **Awaiting your "proceed" for Step 3.**
