# Step DR.6.7 — Drop the remaining `users.id` FK constraints on core CRM tables

**Goal:** Finish what migration `0037_drop_users_id_fks` started on 2026-05-18. After DR.6/DR.7 nothing writes to the legacy `users` table anymore, but 17 FK constraints across 14 core CRM tables still reference `users.id`. Any user created after the DR.6.2 backfill (e.g. invited via `/staff` after 2026-05-15) is absent from `users`, so writing their UUID into one of these tables fails with `ForeignKeyViolationError`. Drop the remaining constraints; the columns stay UUID; application-level membership checks (`_assert_user_in_org`) already enforce validity.

**Phase:** 4.5 — Demo Roles Setup (DR.6 soak cleanup)
**Depends on:** DR.6 (Done), DR.7 (Done), `0037_drop_users_id_fks` (Done)
**Status:** Pending

---

## Scope

**In scope — core CRM (17 FKs, 14 model files):**

| Table | Column | ondelete | Constraint name |
|---|---|---|---|
| activities | user_id | SET NULL | activities_user_id_fkey |
| appointments | assigned_to_id | RESTRICT | appointments_assigned_to_id_fkey |
| attendance | user_id | CASCADE | attendance_user_id_fkey |
| calls | assigned_to_id | SET NULL | calls_assigned_to_id_fkey |
| campaigns | created_by_id | SET NULL | campaigns_created_by_id_fkey |
| contacts | assigned_to_id | SET NULL | contacts_assigned_to_id_fkey |
| conversations | assigned_to_id | SET NULL | conversations_assigned_to_id_fkey |
| demo_credentials | user_id | CASCADE | demo_credentials_user_id_fkey |
| leads | assigned_to_id | SET NULL | leads_assigned_to_id_fkey |
| messages | sender_user_id | SET NULL | messages_sender_user_id_fkey |
| notifications | user_id | CASCADE | notifications_user_id_fkey |
| notification_preferences | user_id | CASCADE | notification_preferences_user_id_fkey |
| reviews | replied_by_id | SET NULL | reviews_replied_by_id_fkey |
| staff_profiles | user_id | CASCADE | staff_profiles_user_id_fkey |
| staff_sessions | user_id | CASCADE | staff_sessions_user_id_fkey |
| tasks | assigned_to_id | RESTRICT | tasks_assigned_to_id_fkey |
| walk_ins | assigned_to_id | SET NULL | walk_ins_assigned_to_id_fkey |

**Out of scope:**

- Furniture pack tables (`inventory.*`, `custom_orders.*` — 3 more FKs). User instruction: core CRM only this step.
- The legacy `users` table itself stays in place. Dropping it is a separate later step (DR.6.8) after this one has soaked for a few days.
- Retargeting any FK to `tbl_user_login.legacy_uuid`. Rejected because (a) `legacy_uuid` lacks a full UNIQUE constraint (only a partial unique index `WHERE legacy_uuid IS NOT NULL`), (b) matches the precedent set in `0037_drop_users_id_fks` which dropped without retarget.

## Why "just drop" instead of retarget

1. **Application already validates.** `_assert_user_in_org()` in `core/leads/service.py:583`, `core/contacts/service.py:400`, and the equivalent in walk-ins / appointments runs before every assignment write. The Postgres FK was redundant with this check.
2. **Matches the established pattern.** `0037_drop_users_id_fks` (2026-05-18) did exactly this for `auth_sessions.user_id` and `audit_logs.user_id` with the same reasoning in its docstring.
3. **Cheaper.** Retargeting needs `tbl_user_login.legacy_uuid` to be `NOT NULL UNIQUE`, which requires generating a UUID for the legacy admin row (`USR29684795`) that currently has NULL there — extra data migration with its own risks.

## `ondelete` semantics we're losing

| Original | What it did | Application replacement |
|---|---|---|
| SET NULL (activities, calls, campaigns, contacts, conversations, leads, messages, reviews, walk_ins) | Owner becomes NULL when user is deleted | Offboarding flow (`tasks/update-staff-offboarding/`) transfers or NULLs records as part of deactivation before user deletion |
| CASCADE (attendance, demo_credentials, notifications, notification_preferences, staff_profiles, staff_sessions) | Child rows deleted with user | Offboarding flow must explicitly DELETE these; alternatively, deletion is rare and a manual cleanup query suffices |
| RESTRICT (appointments, tasks) | User deletion blocked while open rows exist | Offboarding flow already requires transfer-target selection when open records exist (covered in `update-staff-offboarding/step-1` and `step-2`) |

In practice, user *deletion* in this system happens only through the offboarding flow, which already enforces these semantics at the application layer. The Postgres FK was a redundant safety net.

## Files to touch

| File | Change |
|---|---|
| `tasks/phase-4.5-demo-roles-setup/step-dr.6.7-drop-core-users-fks.md` | created (this file) |
| `API/alembic/versions/0062_drop_core_users_id_fks.py` | created — 17 `drop_constraint` in `upgrade()`, 17 `create_foreign_key` in `downgrade()` |
| `API/src/app/core/activities/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Activity.user_id`; remove unused `ForeignKey` import |
| `API/src/app/core/appointments/models.py` | remove `ForeignKey("users.id", ondelete="RESTRICT")` from `Appointment.assigned_to_id` |
| `API/src/app/core/calls/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Call.assigned_to_id` |
| `API/src/app/core/campaigns/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Campaign.created_by_id` |
| `API/src/app/core/contacts/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Contact.assigned_to_id`; remove unused `ForeignKey` import |
| `API/src/app/core/conversations/models.py` | remove FKs from `Conversation.assigned_to_id` and `Message.sender_user_id` |
| `API/src/app/core/dev/models.py` | remove `ForeignKey("users.id", ondelete="CASCADE")` from `DemoCredential.user_id`; remove unused `ForeignKey` import |
| `API/src/app/core/leads/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Lead.assigned_to_id` |
| `API/src/app/core/notifications/models.py` | remove FKs from `Notification.user_id` and `NotificationPreference.user_id`; remove unused `ForeignKey` import |
| `API/src/app/core/reviews/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `Review.replied_by_id` |
| `API/src/app/core/staff/models.py` | remove FKs from `StaffProfile.user_id` and `Attendance.user_id`; remove unused `ForeignKey` import |
| `API/src/app/core/staff_portal/models.py` | remove `ForeignKey("users.id", ondelete="CASCADE")` from `StaffSession.user_id`; remove unused `ForeignKey` import |
| `API/src/app/core/tasks/models.py` | remove `ForeignKey("users.id", ondelete="RESTRICT")` from `Task.assigned_to_id`; remove unused `ForeignKey` import |
| `API/src/app/core/walk_ins/models.py` | remove `ForeignKey("users.id", ondelete="SET NULL")` from `WalkIn.assigned_to_id` |

No router, service, schema, or test changes.

## Rollback

`alembic downgrade -1` recreates every constraint with its original `ondelete` semantics. Safe as long as the legacy `users` table still exists (it does — DR.6.8 not yet run). After running downgrade, every user UUID stored in these columns must also exist in `users.id`; the manual backfill we ran on 2026-05-28 ensured this for current users, but any user created *between* `upgrade` and `downgrade` would need a follow-up `INSERT INTO users …` — same backfill SQL we used today.

## Smoke checklist

In the browser tab logged in as `ajaygogane224@gmail.com` (Owner of `Ajay's Workspace`, org `41f9ede9-41b3-44ce-b489-3004566d4068`):

- [ ] **Leads → List**: tick a row → **Reassign to…** → pick MS Dhoni → save. Expect 200, lead now owned by MS Dhoni, `lead_reassigned` activity in timeline.
- [ ] **Contacts → List**: open a contact → reassign to MS Dhoni. Expect 200, `contact_reassigned` activity in timeline.
- [ ] **Walk-ins → List**: open one → reassign to MS Dhoni. Expect 200, activity in timeline.
- [ ] **Appointments**: reassign one to MS Dhoni (or create new appointment assigned to him). Expect 200.
- [ ] **Tasks**: create a new task assigned to MS Dhoni. Expect 200, task lands in his "Assigned to me" list.

If any one fails, stop, capture the API log, revert with `alembic downgrade -1`, and report.

## Self-check (10 rules)

- Rule 8 — 16 files, single migration, all changes mechanical (one-line removal per FK + import cleanup in 7 files). Reviewable in <30 min.
- Rule 9 — explicit smoke checklist after `alembic upgrade head`; no proceed-to-next-step.
- Rule 10 — no TODOs, no commented-out FK declarations. The `ondelete` semantics are documented in this task file and in the migration docstring; the offboarding flow at `tasks/update-staff-offboarding/` is the new enforcement point.

## Stop & report

After all 5 smoke checks pass, report: "DR.6.7 done. 17 FKs dropped, smoke green. Legacy `users` table parked for DR.6.8."

If the migration itself fails, revert with `alembic downgrade -1` (or `alembic downgrade <previous-revision>`) and report the exact error.
