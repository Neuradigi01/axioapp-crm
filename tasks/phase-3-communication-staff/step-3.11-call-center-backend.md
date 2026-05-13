# Step 3.11 — Call Center: backend

**Goal:** `calls`, `call_transcripts`, `call_outcomes` (config table). CRUD + analytics endpoint (outcomes distribution, daily volume, direction split).
**Phase:** 3
**Depends on:** 2.4
**Status:** COMPLETED

## Scope
**In-scope:**
- Models:
  - `Call` (TenantScoped): id, org_id, contact_id, direction (in/out), started_at, duration_sec, outcome_id, notes, recording_url (nullable), assigned_to_id, custom_data JSONB, created_at.
  - `CallTranscript` (TenantScoped): id, org_id, call_id, text, language, created_at.
  - `CallOutcome` (TenantScoped, config): id, org_id, key, label, color, display_order. Defaults seeded; furniture pack adds more in 4.2.
- Migration + RLS + indexes.
- Endpoints: `/calls` CRUD, `/calls/{id}/transcript`, `/call-outcomes` CRUD (admin), `/calls/analytics?from=&to=`.
- Permission: `calls.read`, `calls.write`, `calls.outcomes.manage`.

## Files to touch
- `api/src/app/core/calls/{__init__,models,schemas,service,router,module}.py` (created)
- `api/alembic/versions/0019_calls.py` (created)
- `api/src/app/main.py` (modified)

## Plan
1. Models + migration.
2. Analytics endpoint computes:
   - outcomes distribution (count by outcome over period).
   - daily volume bar (count by day).
   - direction split (in vs out).
3. Activity log per call (`type='call'`).

## Tests to add
- `tests/test_calls_crud.py`
- `tests/test_calls_analytics.py`

## Verification checklist
**Backend:**
- create call → appears in list.
- `GET /calls/analytics?from=...&to=...` → JSON with three chart-ready arrays.

## Self-check (10 rules)
- [ ] org_id + RLS.
- [ ] Outcomes are config (not hardcoded).

## Stop & report
Await "proceed" before Step 3.12.
