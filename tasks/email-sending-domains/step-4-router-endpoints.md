# Step 4: Router endpoints (Owner-only 4 endpoints)

**Status:** Pending

## Goal

Wire the service functions to REST. Owner-only. Predictable errors.

## Files touched

- `api/src/app/core/email_sender_setup/router.py` — extend with 4 new endpoints
- `api/src/app/core/email_sender_setup/schemas.py` — request/response schemas
- `api/tests/test_sending_domains_router.py`

## What this step does

- New endpoints under `/api/v1/sender-domains`:
  - `POST /` — claim. Body: `{domain, region='us'}`. Returns `DomainOut` with verbatim `dns_records`.
  - `GET /` — list org's domains with status + records.
  - `POST /{id}/verify` — trigger immediate re-verify. Returns fresh `DomainOut`.
  - `DELETE /{id}` — release. 204.
- Auth: Owner-only via existing role dependency.
- Error mapping:
  - `MailgunAuthError` → 500 (internal)
  - `MailgunNotFound` → 404
  - `MailgunProviderError` → 502
  - `DomainAlreadyClaimed` → 409
  - `SendNotConfiguredError` → 400 with clear reason
- Schemas:
  - `ClaimDomainIn`: `domain: str (Field(max_length=253))`, `region: Literal['us','eu'] = 'us'`
  - `DomainOut`: `id, domain, verification_status, dns_records (verbatim JSONB), spf_verified, dkim_verified, dmarc_verified, mx_verified, last_verified_at, region, created_at`
  - Never expose `mailgun_domain_id` (internal).

## Tests

- `test_claim_endpoint_owner_only_403_for_admin`
- `test_claim_endpoint_conflict_returns_409_with_reason`
- `test_claim_endpoint_invalid_domain_returns_422`
- `test_list_endpoint_returns_domains_scoped_to_org`
- `test_list_endpoint_never_exposes_mailgun_domain_id`
- `test_verify_endpoint_triggers_service_verify`
- `test_verify_endpoint_cross_org_returns_404`
- `test_delete_endpoint_owner_only_204`
- `test_delete_endpoint_cross_org_returns_404`
- `test_delete_endpoint_calls_mailgun_delete_and_cascades`

## Verification checklist

- [ ] All 10 tests pass
- [ ] Pin-tests pass — router doesn't call DB directly
- [ ] Ruff clean

## Self-check

- Rule 4: pass — server-side Owner check.
- Rule 2: pass — org-scoped.
- Rule 10: pass.

## Stop-and-report

Report file count, test pass, endpoint list. **Awaiting your "proceed" for Step 5.**
