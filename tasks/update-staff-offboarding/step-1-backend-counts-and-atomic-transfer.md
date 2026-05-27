# Step 1 — Backend: `GET /users/{id}/open-records-counts` + `POST /users/{id}/transfer-records` (atomic) + `GET /reports/workload`

**Goal:** ship the two backend endpoints that drive offboarding. The counts endpoint feeds the deactivation modal. The transfer endpoint atomically bulk-reassigns every open record across all five entities in one transaction, writing audit activities for every row. A small reports endpoint exposes per-user workload counts to drive the Workload tab + (optional) list-page widgets.

**Depends on:** all five page update tracks (each provides a `bulk_reassign_*` service function that this step composes).

## Files changed

### New
- `API/src/app/core/users/offboarding.py` — orchestration service for the atomic transfer.

### Modified
- `API/src/app/core/users/router.py` — mount the two new endpoints.
- `API/src/app/core/users/schemas.py` — `OpenRecordsCounts`, `TransferRecordsRequest`, `TransferRecordsResponse`.
- `API/src/app/core/users/service.py` — `deactivate_user` now refuses unless `open_records_count == 0` OR a `transfer_to_user_id` is supplied in the same call.
- `API/src/app/core/reporting/router.py` — add `GET /reports/workload` (per-user open-record counts).
- `API/src/app/core/reporting/service.py` — `compute_workload(...)`.

### Tests
- `API/tests/core/users/test_offboarding_transfer.py` (new)

## Endpoint — `GET /users/{id}/open-records-counts`

Permission: `users.read`. Returns:
```json
{
  "user_id": "<uuid>",
  "contacts": 12,
  "leads": 5,
  "walk_ins": 3,
  "appointments": 4,
  "tasks": 7,
  "total": 31
}
```

Definitions of "open":
- **contacts** — all contacts assigned to the user (no archival state on contacts; all are "open").
- **leads** — `status IN ('new','contacted','qualified')`. Won + lost are historical, not transferred.
- **walk_ins** — `status IN ('waiting','with_staff')`.
- **appointments** — `status = 'scheduled' AND scheduled_at >= now()`.
- **tasks** — `status != 'done'`.

Implementation: one query per entity counting rows where `assigned_to_id = :id` AND the open-state condition. Run them concurrently with `asyncio.gather`.

## Endpoint — `POST /users/{id}/transfer-records`

Permission: `users.write`. Body:
```json
{
  "to_user_id": "<uuid>",
  "entities": ["contacts", "leads", "walk_ins", "appointments", "tasks"],
  "reason": "<string | null>"
}
```

Validation:
- `to_user_id` must exist in the same `org_id` and be `is_active=true`.
- `entities` must be a non-empty subset of the five names. (Default — all five.)
- Caller must have `users.write`.

Service (`offboarding.transfer_records`):
- Open a single async transaction.
- For each entity in `entities`:
  - Find the ids assigned to `:id` matching the entity's "open" predicate.
  - Call the entity's existing `bulk_reassign_*` service function (NOT the HTTP endpoint).
  - Each function writes its own per-row audit activity as usual.
- Commit on success; rollback on any exception (atomicity guarantee).

Response:
```json
{
  "transferred": { "contacts": 12, "leads": 5, "walk_ins": 3, "appointments": 4, "tasks": 7 },
  "total": 31,
  "from_user_id": "<uuid>",
  "to_user_id": "<uuid>",
  "audit_activities_written": 31
}
```

## `deactivate_user` change

The existing PATCH `/users/{id}/status` that sets `is_active=false` now refuses with `409` if `open_records_count > 0`. The frontend handles the two-step (count → transfer → deactivate) UX; the backend just enforces the invariant.

To make the FE flow easier, also accept a compound `POST /users/{id}/transfer-and-deactivate` body `{"to_user_id": "<uuid>", "reason": "..."}` that runs `transfer_records(all five) + deactivate_user` in one call. Same atomic transaction. Optional — defer to Step 2 if file budget tight.

## Endpoint — `GET /reports/workload`

Permission: `users.read`. Returns:
```json
{
  "users": [
    {
      "user_id": "<uuid>",
      "first_name": "Anita",
      "last_name": "Sharma",
      "is_active": true,
      "counts": {
        "contacts": 12, "leads": 5, "walk_ins": 3, "appointments": 4, "tasks": 7, "total": 31
      }
    },
    …
  ],
  "as_of": "2026-05-27T10:11:12Z"
}
```

Uses the same open-state predicates as the counts endpoint. Optionally accepts `?active_only=true` (default).

## `offboarding.py`

```python
async def transfer_records(
    db: AsyncSession,
    *,
    from_user_id: UUID,
    to_user_id: UUID,
    org_id: UUID,
    entities: list[str],
    reason: str | None,
    actor_user: User,  # who triggered the transfer (for audit)
) -> dict:
    # validate target
    # async transaction: bulk_reassign per entity
    # return summary
```

Each per-entity bulk-reassign is the same service function already exposed by the entity router (re-used to keep audit semantics identical).

## Test `test_offboarding_transfer.py`

1. **Counts endpoint** returns correct per-entity counts.
2. **Transfer endpoint** atomically reassigns all five entities; activity-log entries on every transferred row.
3. **Cross-tenant target** rejected → 422.
4. **Deactivated target** rejected → 422.
5. **Mid-transaction failure** (simulate `leads/bulk_reassign` raising) → all changes rolled back (counts unchanged).
6. **Owner deactivation** — even with `to_user_id` supplied, deactivating the Owner is rejected → 403 (per `rbac-ownership/`).
7. **Permission gate** — caller without `users.write` → 403.

## Acceptance

- `GET /users/<id>/open-records-counts` returns the right numbers.
- `POST /users/<id>/transfer-records` updates all open rows and is atomic.
- `GET /reports/workload` returns per-user counts for the org.
- Deactivation refuses while open records remain unless transfer requested.

## Self-check vs the 10 rules

- ✅ Rule 1 — composes Layer 1 service functions only.
- ✅ Rule 2 — tenant-scoped throughout; cross-tenant target rejected explicitly.
- ✅ Rule 6 — no new permission key (composes existing ones via service-level calls).
- ✅ Rule 8 — 7 files; under limit.
- ✅ Rule 9 — stop-and-report after this step.
- ✅ Rule 10 — atomic, no partial-transfer state possible.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 7 (1 new orchestrator, 4 modified users, 2 modified reporting + 1 new test).
> **What you can verify:**
> 1. `GET /users/<id>/open-records-counts` returns correct counts.
> 2. `POST /users/<id>/transfer-records` atomically transfers + writes audits.
> 3. Mid-transaction failure rolls back everything.
> 4. Cross-tenant + Owner-deactivation rejected.
> 5. `GET /reports/workload` returns the per-user table.
> **Tests added:** `test_offboarding_transfer.py` (7).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 2 (Settings → Staff frontend flow + Workload tab).
