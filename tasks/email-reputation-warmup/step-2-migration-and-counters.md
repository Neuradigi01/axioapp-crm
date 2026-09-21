# Step 2: Migration + Redis counter helpers

**Status:** COMPLETED

## Goal

Ship `tbl_organization_email_reputation` + the time-bucketed Redis counter module. Persistent state (stage, block-until) lives in Postgres; 24h rolling counters live in Redis.

## Files touched

- `api/alembic/versions/0228_email_reputation.py` — migration
- `api/src/app/core/email/reputation/__init__.py`
- `api/src/app/core/email/reputation/models.py` — `OrganizationEmailReputation` ORM
- `api/src/app/core/email/reputation/counters.py` — Redis time-bucket helpers
- `api/tests/test_reputation_migration.py`
- `api/tests/test_reputation_counters.py`

## What this step does

- Migration:
  - CREATE TABLE `tbl_organization_email_reputation` per README schema.
  - `UNIQUE(org_id, envelope_type, domain_id)`.
  - Index `(org_id, envelope_type)` + `(reputation_state, blocked_until)`.
  - CHECK envelope_type IN ('platform_from', 'own_domain').
  - CHECK reputation_state IN ('ok', 'warned', 'blocked').
- ORM class per model.
- Redis counter module:
  - Key format: `rep:{org_id}:{envelope_type}:{domain_id_or_none}:{event_kind}:{bucket_hour}`.
  - Bucket hour = `int(now / 3600)`.
  - `incr_counter(org_id, envelope_type, domain_id, event_kind)` — atomic INCR + set TTL 25h.
  - `sum_last_24h(org_id, envelope_type, domain_id, event_kind) -> int` — pipeline reads 24 buckets, sums.
  - `trim_older_than_24h_all_orgs()` — cron-called; deletes expired keys (Redis TTL already handles it; this is defensive).

## Tests

- `test_migration_creates_tbl_organization_email_reputation`
- `test_migration_unique_constraint_org_envelope_domain`
- `test_migration_check_constraint_envelope_type`
- `test_migration_check_constraint_reputation_state`
- `test_counter_incr_creates_bucket_key`
- `test_counter_incr_sets_ttl_25h`
- `test_counter_sum_last_24h_pipelines_24_buckets`
- `test_counter_sum_excludes_bucket_older_than_24h`
- `test_counter_concurrent_incr_atomic`

## Verification checklist

- [ ] Migration up + down clean
- [ ] Pin-tests pass
- [ ] All 9 tests pass (Redis available in test container)
- [ ] Ruff clean

## Self-check

- Rule 2: pass.
- Rule 8: pass — 6 files.
- DB efficiency: pass — pipeline reads, atomic INCR.

## Stop-and-report

Report file count, migration revision, test pass. **Awaiting your "proceed" for Step 3.**
