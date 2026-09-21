# Step 1: Migration — `tbl_email_quarantine` + `tbl_email_filter_rules`

**Status:** COMPLETED (2026-09-21) — migration `0236_email_quarantine` on `crm_local`; both tables created with CHECK constraints, cascade FKs, partial-unique dedupe index for filter rules, and JSONB columns; downgrade + re-upgrade round-trip clean; both tables register with `Base.metadata` via `main.py` side-effect import.

## Goal

Ship both tables with cascade + probes. No code paths use them yet.

## Files touched

- `api/alembic/versions/0229_quarantine_filters.py` — migration
- `api/src/app/core/email/quarantine/__init__.py`
- `api/src/app/core/email/quarantine/models.py` — `EmailQuarantine`, `EmailFilterRule`
- `api/tests/test_quarantine_migration.py`

## What this step does

- Migration:
  - CREATE TABLE `tbl_email_quarantine` per README schema:
    - `id UUID PK gen_random_uuid()`
    - `org_id UUID FK tbl_organizations.id ON DELETE CASCADE`
    - `endpoint_id UUID FK tbl_channel_endpoints.id ON DELETE CASCADE`
    - `mailgun_delivery_id VARCHAR(64) UNIQUE`
    - `from_address VARCHAR(255) NOT NULL`
    - `from_display_name VARCHAR(255) NULL`
    - `to_recipient VARCHAR(255) NOT NULL`
    - `subject VARCHAR(1024) NULL`
    - `body_snippet TEXT NULL` (max 500 chars enforced at service)
    - `attachment_summary JSONB NOT NULL DEFAULT '[]'::jsonb`
    - `reason_code VARCHAR(32) NOT NULL`
    - `reason_detail JSONB NOT NULL DEFAULT '{}'::jsonb`
    - `payload_path VARCHAR(512) NOT NULL`
    - `status VARCHAR(16) NOT NULL DEFAULT 'held'`
    - `held_at, resolved_at TIMESTAMPTZ NULL`
    - `resolved_by_user_id UUID NULL FK tbl_users.id ON DELETE SET NULL`
    - `blocked_release BOOLEAN NOT NULL DEFAULT false`
  - CHECK reason_code IN ('size_exceeded', 'blocked_sender', 'rate_capped', 'spam_verdict', 'virus_verdict').
  - CHECK status IN ('held', 'released', 'discarded', 'auto_purged').
  - Index `(org_id, status, held_at DESC)`, `(reason_code)`.
  - CREATE TABLE `tbl_email_filter_rules`:
    - `id UUID PK gen_random_uuid()`
    - `org_id UUID FK ON DELETE CASCADE`
    - `endpoint_id UUID NULL FK ON DELETE CASCADE` (NULL = org-wide)
    - `rule_type VARCHAR(16) NOT NULL` (`allow` | `block`)
    - `match_kind VARCHAR(16) NOT NULL` (`email_address` | `email_domain` | `contact_flag`)
    - `match_value VARCHAR(255) NOT NULL`
    - `label VARCHAR(128) NULL`
    - `created_by_user_id UUID FK ON DELETE SET NULL`
    - `created_at, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
  - CHECK constraints on rule_type + match_kind.
  - Index `(org_id, endpoint_id, rule_type, match_kind, match_value)`.

## Tests

- `test_migration_creates_tbl_email_quarantine`
- `test_migration_creates_tbl_email_filter_rules`
- `test_migration_quarantine_reason_code_check_constraint`
- `test_migration_quarantine_status_check_constraint`
- `test_migration_filter_rule_type_check_constraint`
- `test_migration_quarantine_cascades_from_endpoint_delete`
- `test_migration_filter_rule_cascades_from_endpoint_delete`
- `test_migration_down_removes_both_tables`

## Verification checklist

- [ ] Migration up + down clean
- [ ] Pin-tests pass
- [ ] All 8 tests pass
- [ ] Ruff clean

## Self-check

- Rule 2: pass — org_id + RLS + tbl_ prefix.
- Rule 8: pass — 4 files.

## Stop-and-report

Report migration revision, test pass. **Awaiting your "proceed" for Step 2.**
