# Step 1 — Backend: assignee + last_activity columns, migration, sort/filter, activity hook

**Goal:** add `assigned_to_id` and `last_activity_at` to `contacts`, surface them in the list endpoint with sort + filter, and wire the activity-insert hook so `last_activity_at` stays fresh.

## Files changed

### New
- `API/alembic/versions/0052_contacts_assignee_and_last_activity.py`

### Modified
- `API/src/app/core/contacts/models.py`
- `API/src/app/core/contacts/schemas.py`
- `API/src/app/core/contacts/service.py`
- `API/src/app/core/contacts/router.py`
- `API/src/app/core/activities/service.py`

### Tests
- `API/tests/core/contacts/test_assignee_and_last_activity.py` (new)

## Migration `0052_contacts_assignee_and_last_activity.py`

- `ALTER TABLE contacts ADD COLUMN assigned_to_id UUID NULL REFERENCES users(id) ON DELETE SET NULL`
- `ALTER TABLE contacts ADD COLUMN last_activity_at TIMESTAMPTZ NULL`
- `CREATE INDEX ix_contacts_org_assigned_to ON contacts (org_id, assigned_to_id)`
- `CREATE INDEX ix_contacts_org_last_activity_desc ON contacts (org_id, last_activity_at DESC NULLS LAST)`
- Backfill: `UPDATE contacts SET last_activity_at = sub.max_ts FROM (SELECT entity_id, MAX(created_at) AS max_ts FROM activities WHERE entity_type='contact' GROUP BY entity_id) sub WHERE contacts.id = sub.entity_id;`
- `downgrade()` drops both indexes then both columns. No data loss flagged (additive).

## `models.py`

Add:
```python
assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
    UUID(as_uuid=True),
    ForeignKey("users.id", ondelete="SET NULL"),
    nullable=True,
)
last_activity_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True),
    nullable=True,
)
```
No relationship attribute — service-level join is enough for the list view; we want to avoid SQLAlchemy lazy-load surprises in the hot path.

## `schemas.py`

- `ContactListItem`: + `assigned_to_id: uuid.UUID | None`, `assigned_to_name: str | None`, `last_activity_at: datetime | None`.
- `ContactOut`: same three additions.
- `ContactCreate`, `ContactUpdate`: + `assigned_to_id: uuid.UUID | None = None`.
- **Excluded from create/update:** `last_activity_at` — only the activity-insert hook and migration backfill touch it.

## `service.py`

`list_contacts(...)` signature gains:
- `assigned_to_id: uuid.UUID | None = None`
- `sort: Literal["full_name", "created_at", "last_activity_at"] = "created_at"`
- `order: Literal["asc", "desc"] = "desc"`

Implementation notes:
- Whitelist `sort` keys server-side — reject anything else with `422` in the router; do not interpolate raw strings into the ORDER BY.
- Join `users` table for `assigned_to_name`: `SELECT users.first_name || ' ' || users.last_name AS assigned_to_name LEFT JOIN users ON users.id = contacts.assigned_to_id`. Use the actual user-name column(s) the codebase already standardises on.
- For `last_activity_at` sort, append `NULLS LAST` so unassigned/never-touched rows go to the bottom.

`create_contact` and `update_contact` accept the new `assigned_to_id` field; passing through unchanged.

## `router.py`

Add to `list_contacts_endpoint`:
```python
assigned_to_id: uuid.UUID | None = Query(default=None),
sort: Literal["full_name", "created_at", "last_activity_at"] = Query(default="created_at"),
order: Literal["asc", "desc"] = Query(default="desc"),
```
Pass through to `list_contacts(...)`. FastAPI's `Literal` validation rejects bad values with 422 — no manual check needed.

## `activities/service.py` — the bump hook

Locate the `create_activity(...)` function. After the successful insert + commit, run a single conditional UPDATE:

```python
_LAST_ACTIVITY_TABLES = {"contact": Contact}  # extended in update-leads/walkins/appointments tracks

table = _LAST_ACTIVITY_TABLES.get(entity_type)
if table is not None:
    await db.execute(
        update(table)
        .where(table.id == entity_id)
        .where(
            or_(
                table.last_activity_at.is_(None),
                table.last_activity_at < new_activity.created_at,
            )
        )
        .values(last_activity_at=new_activity.created_at)
    )
    await db.commit()
```

The dispatch dict starts with `contact` only — `lead`, `walk_in`, `appointment` get added in their own update tracks. Keep the dict at module scope, not inside the function, so other tracks just append to it.

If the UPDATE fails (parent row deleted between insert and hook), log and swallow — don't roll back the activity. The activity is the authoritative record; `last_activity_at` is a denormalisation.

## Test `test_assignee_and_last_activity.py`

Five tiny cases (single tenant fixture, single user fixture, single contact fixture):
1. `list?assigned_to_id={user}` returns only the contact assigned to that user.
2. `list?sort=last_activity_at&order=desc` returns contacts ordered by `last_activity_at` desc, nulls last.
3. `list?sort=evil` → 422.
4. Creating an activity for a contact bumps `last_activity_at` to `now()`.
5. Creating an *older* activity does not regress `last_activity_at` (the `<` guard).

## Permission posture

No new permission keys. `contacts.read` continues to gate the list and detail endpoints. `contacts.write` gates create/update including the new `assigned_to_id` field. (The reassign-specific permission `contacts.reassign` and its dedicated endpoint land in Step 3.)

## Self-check vs the 10 rules

- ✅ Rule 1 — no pack imports added.
- ✅ Rule 2 — `org_id` already present; new columns tenant-neutral. RLS unaffected (queries still filter by `org_id`).
- ✅ Rule 3 — `custom_data` JSONB untouched.
- ✅ Rule 4 — render endpoint unchanged.
- ✅ Rule 5 — sidebar registry untouched.
- ✅ Rule 6 — no new permission keys this step.
- ✅ Rule 7 — `pack.yaml` untouched.
- ✅ Rule 8 — 6 files, 1 migration, 1 test. Under the limit.
- ✅ Rule 9 — report + wait for `proceed` before Step 2.
- ✅ Rule 10 — backfill runs in the migration; no TODOs.

## Stop-and-report template

> ✅ Step 1 complete.
> **Files changed:** 6 (1 new migration, 4 modified backend, 1 new test file).
> **What you can verify:**
> 1. `uv run alembic upgrade head` succeeds; `\d contacts` shows the two new columns + indexes.
> 2. `uv run alembic downgrade -1` then `upgrade head` round-trips cleanly.
> 3. `curl /api/v1/contacts?sort=last_activity_at&order=desc` returns rows in the right order.
> 4. `POST /api/v1/activities` for `entity_type=contact` bumps `last_activity_at` on the parent contact.
> **Tests added:** `tests/core/contacts/test_assignee_and_last_activity.py` (5 cases).
> **Self-check:** all 10 rules ✅.
> **Raw SQL for manual seed (none — backfill in migration).**
> Awaiting your **"proceed"** before Step 2.
