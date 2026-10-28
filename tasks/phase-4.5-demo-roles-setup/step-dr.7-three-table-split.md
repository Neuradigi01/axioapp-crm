# Step DR.7 — Three-table split: auth / profile / org-membership

**Goal:** Refactor the work DR.6 just landed so that responsibilities split across three tables, matching the reference architecture:

| Table | Holds | 1:N? |
|---|---|---|
| `tbl_user_login` | id (bigint), user_id (text login-handle), password, 2FA, is_active | **one row per user** |
| `tbl_user_info` | member_id (FK→login), first_name, last_name, email, mobile_no, profile_image, verification flags, joining_date | **1:1 with tbl_user_login** (UNIQUE member_id) |
| `tbl_organization_members` *(NEW)* | id, organization_id (UUID FK→organizations), user_member_id (bigint FK→login), **role_id (UUID FK→roles)**, status, is_active, joined_at, is_demo, ui_preferences | **N:M between login and org** |

After DR.7, a FurnitureCRM login is a join of three rows. One user can theoretically belong to multiple orgs (one membership row per org) — a partial unique index `WHERE is_active=true` enforces one active membership per user at a time, matching the reference.

**Phase:** 4.5 — Demo Roles Setup (side task)
**Depends on:** DR.6 (Done)
**Status:** Done (smoked 2026-05-15 — 4 demo logins, /me, /_dev/demo-logins, audit, legacy admin endpoint all green; `tbl_user_login` reduced to reference shape + `legacy_uuid`; 3 new migrations 0033–0035)

---

## Why we're doing this

DR.6.1 took a shortcut by stuffing FurnitureCRM columns (email / org_id / role_id / full_name / phone / is_demo / legacy_uuid / created_at / updated_at) directly onto `tbl_user_login`. That works but it conflates three concerns on one row:

1. Authentication (who logs in)
2. Profile (who they are)
3. Membership + role (which org they belong to, what role they have there)

The reference architecture splits these. Benefits:

- Email + full_name + phone live with the user identity (`tbl_user_info`), not on the login row — so changing them doesn't churn auth state.
- A user can belong to multiple orgs by having multiple `tbl_organization_members` rows. The current schema can't represent that.
- Role + org-membership state (is_demo, status, ui_preferences) live with the membership, not with the user. Today they're per-row on `tbl_user_login` which only works because every user happens to have exactly one org.

**The `roles` table stays as-is** — keeps per-org role definitions and the `role_permissions` join. `tbl_organization_members.role_id` is a UUID FK to it. This deviates from the reference's literal `role TEXT` column, but preserves FurnitureCRM's permission-gating layer (which the sidebar already depends on).

---

## Decisions explicitly made (and why they deviate from a literal copy of the reference)

| Decision | Reference says | DR.7 does | Why |
|---|---|---|---|
| Role column | `role TEXT` | `role_id UUID FK → roles.id` | FurnitureCRM RBAC is built on per-org `roles` + `role_permissions`. Switching to free-text role would force re-implementing the sidebar/permission gating off a static role-name → permissions map. Out of scope for DR.7. |
| Organization FK | `bigint → tbl_organizations` | `UUID → organizations.id` | We don't have `tbl_organizations`; FurnitureCRM uses `organizations` with UUID PK throughout. |
| 2FA columns | `two_factor_methods JSONB` | keep existing `two_factor_enabled` BOOL + `two_factor_method` TEXT + `two_factor_secret` TEXT | Cosmetic; legacy `UserLogin` mapping already reads these. Worth a separate ticket if we want the JSONB form. |
| `is_demo` | not in reference | add to `tbl_organization_members` | DR.4's `/_dev/demo-logins` filter is keyed on this. Moves with the membership, not with the user. |

If you want any of those flipped (especially `role TEXT` vs `role_id`), say so before DR.7.1.

---

## The "carefully" discipline

Same as DR.6 — break this into 5 micro-steps with smoke + rollback per step. Pause and report after each. If anything reds, revert that step and stop.

| Sub-step | What it does | Reversible? |
|---|---|---|
| DR.7.1 | Migration: create `tbl_organization_members`; no data movement | Yes — `alembic downgrade -1` |
| DR.7.2 | Migration: copy data from `tbl_user_login.{org_id, role_id, is_demo}` → `tbl_organization_members`; populate `tbl_user_info` for the 12 FurnitureCRM users from `tbl_user_login.{email, full_name, phone}` | Yes — `alembic downgrade -1` removes the inserted rows |
| DR.7.3 | Repoint the layered `User` model: `User` becomes `tbl_user_login`-shaped (auth only) + expose `info`/`membership` via SQLAlchemy relationships. Auth lookup reads `tbl_user_info.email` + active membership. | Yes — revert `models.py` + `users/service.py` + `auth/service.py` |
| DR.7.4 | Sweep `user.email` / `user.full_name` / `user.org_id` / `user.role_id` / `user.is_demo` across ~30 files → use the new accessors (`user.info.email`, `user.membership.org_id`, etc.) | Yes — revert each file |
| DR.7.5 | Migration: drop the `tbl_user_login` columns we added in 0031 (email, org_id, role_id, full_name, phone, is_demo, legacy_uuid, created_at, updated_at) + the two partial unique indexes. **Don't touch the data**, only the schema. Final state: `tbl_user_login` looks exactly like the reference. | Yes — `alembic downgrade -1` adds the columns back (data already moved in DR.7.2 so it stays in the new tables) |
| DR.7.6 | End-to-end smoke; update README; mark soak-checklist for the old DR.6 columns shift | n/a — verification only |

---

## DR.7.1 — Schema only: create `tbl_organization_members`

**Migration:** `api/alembic/versions/0033_tbl_organization_members.py`

```sql
CREATE TABLE tbl_organization_members (
  id                   BIGSERIAL PRIMARY KEY,
  organization_id      UUID        NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
  user_member_id       BIGINT      NOT NULL REFERENCES tbl_user_login(id) ON DELETE RESTRICT,
  role_id              UUID        NOT NULL REFERENCES roles(id)         ON DELETE RESTRICT,
  status               TEXT        NOT NULL DEFAULT 'active',
  is_active            BOOLEAN     NOT NULL DEFAULT TRUE,
  is_demo              BOOLEAN     NOT NULL DEFAULT FALSE,
  joined_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  ui_preferences       JSONB       NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT uq_org_member_user UNIQUE (organization_id, user_member_id)
);

CREATE INDEX idx_tbl_org_members_organization_id ON tbl_organization_members (organization_id);
CREATE INDEX idx_tbl_org_members_user_member_id  ON tbl_organization_members (user_member_id);
-- partial unique: one active membership per user at a time
CREATE UNIQUE INDEX uq_org_members_one_active_per_user
  ON tbl_organization_members (user_member_id)
  WHERE is_active = true;
```

**Why no `max_concurrent_chats`:** that's call-center-specific in the reference; FurnitureCRM doesn't need it (yet).

**Smoke:** `\d tbl_organization_members` shows the 9 columns + 3 indexes. Row count = 0. Existing tables untouched.

**Rollback:** `.\docker-helper.cmd downgrade 1`.

---

## DR.7.2 — Data migration: backfill `tbl_user_info` and `tbl_organization_members`

**Migration:** `api/alembic/versions/0034_backfill_info_and_members.py`

```sql
-- 1) Profile rows (only for FurnitureCRM users — exclude the legacy
-- USR29684795 row that has no email).
INSERT INTO tbl_user_info (
    member_id, first_name, last_name, email, mobile_no,
    country_id, state_id, profile_image,
    is_email_verified, is_mobile_verified, joining_date
)
SELECT
    t.id,
    split_part(t.full_name, ' ', 1)                      AS first_name,
    NULLIF(substr(t.full_name, position(' ' in t.full_name) + 1), '') AS last_name_raw,
    -- ^ this is illustrative; we'll handle the no-space case explicitly
    -- in the Python migration (see notes below)
    t.email::text,
    t.phone,
    NULL, NULL, NULL,
    FALSE, FALSE,
    COALESCE(t.created_at, now())
FROM tbl_user_login t
WHERE t.email IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM tbl_user_info i WHERE i.member_id = t.id
  );

-- 2) Membership rows
INSERT INTO tbl_organization_members (
    organization_id, user_member_id, role_id,
    status, is_active, is_demo, joined_at
)
SELECT
    t.org_id,
    t.id,
    t.role_id,
    'active',
    t.is_active,
    t.is_demo,
    COALESCE(t.created_at, now())
FROM tbl_user_login t
WHERE t.org_id IS NOT NULL
  AND t.role_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM tbl_organization_members m
    WHERE m.organization_id = t.org_id
      AND m.user_member_id = t.id
  );
```

**Edge case: `tbl_user_info.first_name` and `last_name` are NOT NULL.** Some seeded users have a single-word `full_name` (e.g. "Demo Admin"). The Python-side migration body does:

```python
parts = full_name.split(maxsplit=1)
first = parts[0]
last = parts[1] if len(parts) > 1 else ""
```

**Edge case: `tbl_user_info.email` is GLOBAL unique.** All 11 FurnitureCRM emails are already distinct, so no collision risk. We confirm this with `SELECT COUNT(DISTINCT email) = COUNT(*) FROM tbl_user_login WHERE email IS NOT NULL` before the INSERT.

**Smoke:**
```sql
SELECT COUNT(*) FROM tbl_user_info;            -- expect 11
SELECT COUNT(*) FROM tbl_organization_members; -- expect 11
SELECT i.email, m.role_id, m.is_demo
FROM tbl_user_info i
JOIN tbl_organization_members m ON m.user_member_id = i.member_id
ORDER BY i.email;
-- expect 11 rows pairing every email with a role and is_demo flag matching pre-DR.7 state
```

**Rollback:** `.\docker-helper.cmd downgrade 1` → DELETE FROM tbl_user_info / tbl_organization_members for the rows the migration inserted (guarded by NOT EXISTS so re-runs are no-ops).

---

## DR.7.3 — Repoint the `User` model + auth lookup

Update `api/src/app/core/users/models.py`:

- `User` maps `tbl_user_login` and exposes ONLY auth columns (id, user_id, password, 2FA, is_active).
- Add `UserInfo` model (1:1 via member_id, `User.info` relationship).
- Add `OrganizationMember` model (N:M, `User.memberships` relationship).
- Helper property `User.active_membership` returns the unique row with `is_active=true`.

Auth lookup in `auth/service.py` changes from:
```python
select(User).where(User.org_id == org_id, User.email == email)
```
to:
```python
select(User).join(UserInfo).join(OrganizationMember).where(
    UserInfo.email == email,
    OrganizationMember.organization_id == org_id,
    OrganizationMember.is_active.is_(True),
    User.is_active.is_(True),
)
```

JWT `sub`: continue carrying the **UUID** identity. Since one user is now one identity (across orgs), `sub` becomes `tbl_user_login.legacy_uuid` for now and migrates to `tbl_user_login.id` (bigint) in a later step if we want — out of scope here.

`get_current_user` resolves the active membership in the JWT's `org_id` claim, exposes role/permissions off that.

**Smoke:** app boots without mapper errors; `POST /api/v1/auth/login` (admin@core-demo) returns 200 + JWT.

**Rollback:** revert the three files.

---

## DR.7.4 — Sweep call sites

Every place that reads `user.email`, `user.full_name`, `user.phone`, `user.org_id`, `user.role_id`, `user.is_demo` needs to go through the new relationships:

- `user.email` → `user.info.email`
- `user.full_name` → `(user.info.first_name + ' ' + user.info.last_name).strip()`
- `user.phone` → `user.info.mobile_no`
- `user.org_id` → `user.active_membership.organization_id`
- `user.role_id` → `user.active_membership.role_id`
- `user.is_demo` → `user.active_membership.is_demo`

Files affected (rough count, from DR.6.5 sweep + the new attrs):
- `core/auth/service.py`, `core/users/router.py`, `core/users/service.py`, `core/users/schemas.py`
- `core/audit/...`, `core/staff/service.py`, `core/staff_portal/service.py`, `core/dev/router.py`
- Every router that does `user_id=user.legacy_uuid` (the DR.6.5 sweep) still works — that uses an attribute we keep on `User`. So this sub-step is a smaller delta than DR.6.5.

**Smoke:** all 4 demo logins → /me returns the correct shape; /_dev/demo-logins returns 4; audit rows still write with UUID user_id.

**Rollback:** revert each file.

---

## DR.7.5 — Drop the DR.6.1 columns from `tbl_user_login`

**Migration:** `api/alembic/versions/0035_drop_dr6_columns_from_login.py`

```sql
DROP INDEX IF EXISTS uq_tbl_user_login_org_email;
DROP INDEX IF EXISTS uq_tbl_user_login_legacy_uuid;
ALTER TABLE tbl_user_login
  DROP CONSTRAINT IF EXISTS fk_tbl_user_login_role_id,
  DROP CONSTRAINT IF EXISTS fk_tbl_user_login_org_id;
ALTER TABLE tbl_user_login
  DROP COLUMN IF EXISTS email,
  DROP COLUMN IF EXISTS org_id,
  DROP COLUMN IF EXISTS role_id,
  DROP COLUMN IF EXISTS full_name,
  DROP COLUMN IF EXISTS phone,
  DROP COLUMN IF EXISTS is_demo,
  DROP COLUMN IF EXISTS legacy_uuid,
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at;
```

After this, `tbl_user_login` looks exactly like the reference (minus the `two_factor_methods JSONB` cosmetic difference — separate ticket).

**Risk: `legacy_uuid`.** The audit/AuthSession layer carries this UUID as the user identity. Removing `legacy_uuid` means:
- JWT `sub` can no longer be a UUID looked up against `tbl_user_login.legacy_uuid`.
- Pre-DR.7 JWTs in users' browsers become invalid (sub is a UUID that's no longer queryable).

Mitigation: before DR.7.5, change `get_current_user` to look up by `tbl_user_login.id` (bigint), and `auth/service.py:login` to encode JWT `sub` as `str(user.id)` (bigint). Existing UUID-typed FK columns (`audit_logs.user_id`, `auth_sessions.user_id`, `staff_sessions.user_id`, `staff_profiles.user_id`) need retargeting to `tbl_user_login.id` (bigint) — but those FK columns are UUID. **So actually DR.7.5 can NOT drop `legacy_uuid`** without first either:
  - (a) Retargeting all the UUID FK columns to bigint via more migrations (lots of work, lots of risk)
  - (b) Leaving `legacy_uuid` on `tbl_user_login` indefinitely — accept the small deviation from the reference.

Recommendation: **option (b).** Keep `legacy_uuid` on `tbl_user_login`. Drop the other 8 DR.6.1 columns. Document the deviation.

If you want option (a) — retarget every UUID-typed FK to bigint — that's at least 4 more migrations and a re-sweep of audit / AuthSession / StaffSession etc. Call it DR.8.

---

## DR.7.6 — End-to-end smoke + README

Same shape as DR.6.6: all 4 demo logins work, legacy admin login still works, `ng build` clean, README updated. The `users` soak checklist from DR.6 is unaffected (we never re-touched `users`).

---

## Files to touch (estimated)

| File | Action |
|---|---|
| `0033_tbl_organization_members.py` | created |
| `0034_backfill_info_and_members.py` | created |
| `0035_drop_dr6_columns_from_login.py` | created |
| `api/src/app/core/users/models.py` | modified — `User`, new `UserInfo` + `OrganizationMember` + relationships |
| `api/src/app/core/auth/service.py` | modified — login lookup via UserInfo+OrgMember join |
| `api/src/app/core/users/router.py` | modified — /me reads off relationships |
| `api/src/app/core/users/service.py` | modified — get_user_by_id, list_users |
| `api/src/app/core/users/schemas.py` | modified — UserOut/UserMe pull from info/membership |
| `api/src/app/core/dev/router.py` | modified — /_dev/demo-logins joins through new tables |
| `api/src/app/scripts/seed_admin_user.py` | modified — write to 3 tables instead of 1 |
| `api/src/app/scripts/seed_core_demo_org.py` | modified — same |
| `api/src/app/core/staff/service.py`, `staff_portal/service.py` | modified — adjust user joins |
| ~6 other small touch-ups for sites that read `user.email` / `user.org_id` / etc. | modified |

**~13 files + 3 migrations.** Bigger than DR.6 (which was ~24 files + 2 migrations) because the sweep is touching different attributes. Most files are small touch-ups.

---

## Risks

1. **Email global-unique on tbl_user_info vs per-org-unique today.** All current FurnitureCRM emails are distinct, so no migration collision. But any future seed that tries to create two users with the same email in different orgs will fail. Flagged.
2. **Pre-DR.7 JWTs become invalid** if we change JWT sub semantics in DR.7.5 — mitigated by keeping `legacy_uuid` on `tbl_user_login` (option b above).
3. **The relationship plumbing** on the User model is more complex than a single mapped class. SQLAlchemy `relationship()` loading strategy needs to be `selectin` or `joined` to avoid N+1 queries on /me.
4. **Legacy `UserLogin` mapping still coexists** on the same table — same coexistence pattern as DR.6.3, no change.

---

## Stop & report

After DR.7.6 smokes green, stop. Mark DR.7 Done in the README. Do NOT touch the `users` table here either — its soak revisit date stays 2026-05-29.

If any sub-step fails, stop immediately at that point, revert, report the failure, and DO NOT proceed.
