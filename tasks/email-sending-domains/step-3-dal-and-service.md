# Step 3: DAL + service (`claim_domain`, `verify_domain`, `release_domain`, `resolve_send_envelope`)

**Status:** COMPLETED

## Goal

Business logic layer. Talks to Mailgun via Step 2's client, persists to Step 1's table, exposes the send-envelope resolver Track 4 and beyond will consume.

## Files touched

- `api/src/app/core/email_sender_setup/data_access.py` — extend with domain functions
- `api/src/app/core/email_sender_setup/service.py` — extend with 4 new service functions
- `api/src/app/core/email_sender_setup/schemas.py` — request/response models
- `api/tests/test_sending_domains_service.py`

## What this step does

- DAL functions:
  - `insert_domain_pending(session, *, org_id, domain, mailgun_domain_id, dns_records, region) -> OrganizationEmailDomain`
  - `find_domain_by_id(session, *, id, org_id=None)` — org-scope enforced if `org_id` passed
  - `find_verified_own_domain_for_org(session, *, org_id) -> OrganizationEmailDomain | None` — pick most-recent verified
  - `list_domains_for_org(session, *, org_id) -> list[OrganizationEmailDomain]`
  - `update_verification(session, *, id, all_pass, failed_count, dns_records) -> None`
  - `mark_demoted(session, *, id) -> None`
  - `mark_released(session, *, id) -> None`
  - `mark_verified_after_demotion(session, *, id) -> None`
- Service functions:
  - `claim_domain(db, *, org_id, actor_user_id, domain, region='us') -> DomainClaimResult`
    - Validate RFC 1035 labels + no scheme. Reject on invalid.
    - Check global uniqueness (409 if already claimed by any org).
    - Call `client.create_domain()` → get `mailgun_domain_id` + records.
    - INSERT row `verification_status='pending'`.
    - Commit + audit `sending_domain.claimed`.
    - Notify owner (in-app).
  - `verify_domain(db, *, org_id, id, actor_user_id) -> OrganizationEmailDomain`
    - Load row (org-scoped). Call `client.verify_domain()`.
    - Detail response → update `spf_verified, dkim_verified, dmarc_verified, mx_verified`.
    - All pass → `verification_status='verified'`, `consecutive_failed_checks=0`. Fire notify-owner-verified if state transition.
    - Any fail → `consecutive_failed_checks += 1`.
    - Commit + audit.
  - `release_domain(db, *, org_id, id, actor_user_id) -> None`
    - Owner-only.
    - Call `client.delete_domain()`. Set `verification_status='released'`, `released_at=now()`.
    - Cascade `tbl_email_endpoint_details.domain_id` FK to NULL (SQL, not ORM).
    - Commit + audit.
    - Notify owner.
  - `resolve_send_envelope(db, *, org_id, caller_supplied_sender_id=None) -> SendEnvelope`
    - Cascade per README's locked decision: caller → org default → verified own-domain → platform-from → raise `SendNotConfiguredError`.
    - Returns dataclass with `from_address`, `reply_to`, `envelope_type` (`smtp_sender` | `oauth_account` | `own_domain` | `platform_from`), and provider-specific dispatch metadata.
- Domain validator: `_validate_domain(domain) -> None` — regex `^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$`. Rejects schemes, paths, spaces.

## Tests

- `test_claim_domain_creates_pending_row_and_stores_dns_records_verbatim`
- `test_claim_domain_conflict_when_domain_already_claimed_by_other_org_returns_409`
- `test_claim_domain_validates_rfc1035_labels_rejects_scheme_urls`
- `test_verify_domain_all_pass_flips_to_verified_zeros_failed_counter`
- `test_verify_domain_any_fail_increments_failed_counter`
- `test_verify_domain_mailgun_5xx_does_not_increment_failed_counter`
- `test_release_domain_sets_status_released_and_calls_mailgun_delete`
- `test_release_domain_cascades_endpoint_details_domain_id_to_null`
- `test_resolve_send_envelope_prefers_caller_supplied_sender`
- `test_resolve_send_envelope_falls_to_verified_own_domain`
- `test_resolve_send_envelope_skips_demoted_own_domain`
- `test_resolve_send_envelope_falls_to_platform_from_when_no_own_domain`
- `test_resolve_send_envelope_raises_send_not_configured_when_all_paths_miss`
- `test_verified_after_demotion_notifies_owner`

## Verification checklist

- [ ] All 14 tests pass
- [ ] Pin-tests pass (service is the only transaction owner)
- [ ] Ruff clean

## Self-check

- Rule 4 (permissions): pass — Owner-only on release.
- Rule 2 (org isolation): pass — all functions org-scoped.
- Layered: pass.
- Rule 10: pass.

## Stop-and-report

Report file count, test pass. **Awaiting your "proceed" for Step 4.**
