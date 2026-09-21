# Step 1: Discovery + Migration — `tbl_organization_email_domains`

**Status:** Pending

## Goal

Fetch Mailgun's actual `GET /v3/domains/{domain}` response shape (US + EU), lock the JSONB schema, ship the migration. No code paths use the table yet.

## Files touched

- `tasks/email-sending-domains/DISCOVERY-NOTES.md` — fetched URLs + summary
- `api/alembic/versions/0226_email_domains.py` — migration
- `api/src/app/core/email_sender_setup/models.py` — new `OrganizationEmailDomain` class
- `api/tests/test_email_domains_migration.py`

## What this step does

- Discovery pass (2h timebox):
  - Fetch `https://documentation.mailgun.com/en/latest/api-domains.html` — GET/POST/DELETE domain endpoints.
  - Fetch `https://documentation.mailgun.com/en/latest/user_manual.html#verifying-your-domain` — record types (TXT for DKIM, TXT for SPF, MX for receiving, CNAME for tracking).
  - Fetch EU-region base URL variation (`api.eu.mailgun.net`).
  - Document response body shape verbatim in `DISCOVERY-NOTES.md`.
- Migration: create `tbl_organization_email_domains` per README schema.
  - `id UUID PK gen_random_uuid()`
  - `org_id UUID FK tbl_organizations.id ON DELETE CASCADE`
  - `domain VARCHAR(253) NOT NULL UNIQUE`
  - `mailgun_domain_id VARCHAR(64) NOT NULL`
  - `verification_status VARCHAR(16) NOT NULL DEFAULT 'pending'`
  - `dns_records JSONB NOT NULL DEFAULT '{}'::jsonb`
  - `mx_verified, spf_verified, dkim_verified, dmarc_verified BOOLEAN NOT NULL DEFAULT false`
  - `last_verified_at TIMESTAMPTZ NULL`
  - `consecutive_failed_checks INT NOT NULL DEFAULT 0`
  - `demoted_at, released_at TIMESTAMPTZ NULL`
  - `region VARCHAR(4) NOT NULL DEFAULT 'us'`
  - `created_at, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - CHECK constraint: `verification_status IN ('pending','verified','demoted','released')`
  - CHECK constraint: `region IN ('us','eu')`
  - Index on `(org_id, verification_status)`.
- Model: `OrganizationEmailDomain(Base, TenantScoped)`.

## Migration

- Revision: `0226_email_domains`.
- `upgrade()`: CREATE TABLE + indexes + CHECK.
- `downgrade()`: DROP TABLE.

## Tests

- `test_migration_creates_tbl_organization_email_domains`
- `test_migration_enforces_domain_unique_global`
- `test_migration_check_constraint_verification_status_enum`
- `test_migration_check_constraint_region_enum`
- `test_migration_index_on_org_id_verification_status`
- `test_migration_down_removes_table`

## Verification checklist

- [ ] `DISCOVERY-NOTES.md` cites live URLs + exact JSON response shape
- [ ] Migration up + down clean via `run.cmd`
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass (`org_id` + `tbl_` + RLS).
- Rule 8: pass (4 files).
- Discovery per DISCOVERY_RULES rule zero: pass — URLs fetched, not recalled.

## Stop-and-report

Report DISCOVERY-NOTES.md URLs, migration revision, test results. **Awaiting your "proceed" for Step 2.**
