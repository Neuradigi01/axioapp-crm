# Step 5 — `tbl_custom_events` + `tbl_custom_event_occurrences` + `_archive` + `tbl_custom_event_test_runs`

**Goal:** create the four tables (event definitions without prefix, denormalised-schema-snapshot occurrences, month-partitioned archive, 7-day test-runs table). Partial-unique index for soft-delete. All RLS-enabled from migration one.
**Phase:** Custom Events track — step 5/17
**Depends on:** Steps 1-4
**Status:** Pending

## Scope

**In-scope:**
- Migration `NNNN_custom_events_schema.py` (revision ID ≤ 32 chars):

  **`tbl_custom_events`**
  ```
  id UUID PK
  org_id UUID NOT NULL FK tbl_organizations
  name TEXT NOT NULL (stored WITHOUT `custom.` prefix; NFKC + regex '^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){0,3}$')
  display_label TEXT NOT NULL
  category TEXT NULL
  is_active BOOLEAN NOT NULL DEFAULT TRUE
  created_by UUID NOT NULL FK tbl_users
  payload_schema JSONB NOT NULL DEFAULT '{}'::jsonb
  schema_updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  Partial-unique index: `CREATE UNIQUE INDEX idx_custom_events_org_name_active ON tbl_custom_events(org_id, LOWER(name)) WHERE is_active = TRUE`.
  RLS enabled + policy.

  **`tbl_custom_event_occurrences`** (month-partitioned by `fired_at`; parent table + one initial partition)
  ```
  id UUID PK
  org_id UUID NOT NULL FK
  event_id UUID NOT NULL FK tbl_custom_events
  payload_schema_snapshot JSONB NOT NULL   -- denormalised (no version table)
  payload JSONB NOT NULL
  contact_id UUID NULL FK tbl_contacts ON DELETE SET NULL
  external_id VARCHAR(128) NULL           -- cookie/utk anon identifier
  source VARCHAR(64) NOT NULL             -- 'api' | 'webhook' | 'zapier' | 'manual'
  mode VARCHAR(4) NOT NULL CHECK (mode IN ('live','test'))
  is_test BOOLEAN NOT NULL DEFAULT FALSE
  ip_hashed BYTEA NULL                    -- HMAC(per-org rotated pepper, ip)
  api_key_id UUID NOT NULL FK tbl_api_keys ON DELETE SET NULL
  fired_at TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  Indexes: `(org_id, event_id, fired_at DESC)`, `(org_id, contact_id, fired_at DESC)`, `(external_id) WHERE external_id IS NOT NULL`. RLS enabled.

  **`tbl_custom_event_occurrences_archive`** — same schema as parent occurrences table. RLS enabled. `(org_id, event_id, fired_at DESC)` index.

  **`tbl_custom_event_test_runs`**
  ```
  id UUID PK
  org_id UUID NOT NULL FK
  event_id UUID NOT NULL FK
  fired_by_user_id UUID NOT NULL FK tbl_users
  payload_snapshot JSONB NOT NULL
  rendered_actions_preview JSONB NOT NULL      -- from dry_run engine
  fired_at TIMESTAMPTZ NOT NULL DEFAULT now()
  ```
  Index `(org_id, event_id, fired_at DESC)`. RLS enabled. 7-day retention (cleanup in Step 10).

- Per-org `ip_hash_pepper` — stored in `tbl_organizations.ip_hash_pepper BYTEA NULL` (Fernet-encrypted; rotated annually by follow-up track). Generated on first use.

- Contact-source enum extension: `contact.source` field is free-form VARCHAR(64) per project audit — no enum expansion needed. `'event_ingest'` becomes a first-class value in frontend filter (Step 15 wires the dropdown).

**Out of scope:**
- CRUD endpoints (Step 6).
- Ingest endpoint (Step 7).

## Files to touch
- `api/alembic/versions/NNNN_custom_events_schema.py`.
- `api/src/app/core/public_ingest/custom_events/models.py` (new — `CustomEvent`, `CustomEventOccurrence`, `CustomEventOccurrenceArchive`, `CustomEventTestRun`).
- `api/src/app/core/tenants/models.py` (modified — add `ip_hash_pepper` column).
- Tests.

## Plan
1. Migration up + down.
2. Models with proper indexes + FKs.
3. RLS policies for each new table.
4. `ip_hash_pepper` generation helper.

## DB changes / migrations
See scope.

## Tests to add
- `test_custom_events_schema_columns_and_indexes_match_spec`.
- `test_custom_events_partial_unique_allows_soft_delete_recreate`.
- `test_custom_events_partial_unique_case_insensitive`.
- `test_custom_events_rls_policies_present_on_all_four_tables`.
- `test_occurrences_table_is_partitioned_by_month`.
- `test_ip_hash_pepper_column_present_on_organizations`.

## Verification checklist
- Backend: migration up + down clean via `API\run.cmd upgrade`.
- Backend: tests pass.
- Backend: `\d+ tbl_custom_events` in psql shows expected columns + indexes.

## Self-check
- [ ] Rule 1: core.
- [ ] Rule 2: `org_id` + RLS on all 4 new tables + archive.
- [ ] Rule 8: 3 files.
- [ ] Rule 10: no half-done.
- [ ] Feedback: revision ID ≤ 32 chars.
- [ ] Feedback: migration executed via `API\run.cmd upgrade`.

## Stop & report
Await "proceed".
