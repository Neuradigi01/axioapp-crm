# Step 3 — Ownership transfer

**Goal:** An `Owner` hands their org over to another active member. The target member becomes Owner; the original Owner is demoted to `Admin` (default — confirmable in the UI). Single-Owner-per-org invariant maintained atomically.
**Track:** RBAC, Ownership & Self-Signup
**Status:** Pending
**Depends on:** Step 1 (Owner role exists per org), Step 2 (Admin role exists per org as default demote target), 2.5.1 (admin user CRUD).

---

## Scope

One backend endpoint + one modal on the Users page. The endpoint must be atomic — partial state where two members carry Owner, or no member does, is unrecoverable without a DB-level fix.

## Schema

No new tables. No new columns required, but recommend adding:

| Column | Type | Why |
|---|---|---|
| `tbl_organization_members.transferred_at` | TIMESTAMPTZ NULL | Audit + UI sorting; non-null on the row that was *demoted* during a transfer. |
| `tbl_organization_members.transferred_from` | BIGINT NULL FK → tbl_organization_members.id | Trail showing who handed it over. Self-FK is fine. |

Optional. If the team prefers to lean only on `audit_logs` for the trail, skip these and the migration. Default: skip — keep this step migration-free unless an explicit need surfaces.

## Backend

| Endpoint | Auth | Behaviour |
|---|---|---|
| `POST /api/v1/ownership/transfer` | **Caller must be Owner** of the current org context (enforced at the service layer, not by a `users.write` permission key — Owner is the only one who can do this even if Admin holds `users.write`). | Body: `{target_member_id, demote_to_role_id?}`. Validates: (a) caller is current Owner; (b) target is an active member of the same org; (c) target is not already Owner. If `demote_to_role_id` omitted, defaults to the `Admin` role of this org (if instantiated; otherwise no demote — caller becomes a regular member with no role, which we reject with 422 and ask them to pass `demote_to_role_id` explicitly). **Single transaction:** (1) update caller's row: `role_id = <demote_to_role_id>`; (2) update target's row: `role_id = <Owner role>`; (3) write audit row `ownership.transferred` with both members + previous/new roles; (4) commit. Returns 200 with `{new_owner: MemberOut, demoted: MemberOut}`. The caller's JWT continues to work but their permissions change immediately. |

**Why not a `ownership.transfer` permission key?** Because Owner is fixed — the role *is* the authorisation. Adding a key would imply Admins could grant themselves transfer rights, which violates Rule 7's "Owner is fixed, undeletable" contract. Service layer hard-coded check is the right enforcement.

**Self-transfer (target == caller):** 422 with clear message. The endpoint is explicitly for handing over, not no-ops.

## Frontend

`/user/settings/users` (from Phase 2.5.2) currently lists members. Owner-only addition:

1. **[Transfer ownership]** button at top-right of the Users page. Visible only when `currentUser.role.name == 'Owner'`.
2. Opens a modal: **"Transfer ownership of {org_name}"**. Contents:
   - Dropdown: target member (active members of this org, excluding self, excluding any other Owner row — which shouldn't exist).
   - Dropdown: "Your new role" — defaults to "Admin" (if Admin role exists in this org), otherwise prompts the Owner to select a non-Owner role.
   - **Big red warning:** "After transfer, you lose Owner permissions immediately and {target.name} gains them. This cannot be undone without their cooperation."
   - Confirm by typing the org name (existing pattern from delete-org if any; otherwise a checkbox "I understand").
   - Submit button disabled until confirmation.
3. On 200: toast "Ownership transferred to {target.name}." Reload `/users/me` (permissions now reflect demoted role). Re-render sidebar with the new (likely reduced) permission set.

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/tenants/ownership.py` | created — `transfer_ownership(...)` service function (or live in `tenants/service.py`) |
| `api/src/app/core/tenants/router.py` | modified — `POST /ownership/transfer` |
| `api/src/app/core/tenants/schemas.py` | modified — `OwnershipTransferRequest`, `OwnershipTransferResponse` |
| `api/tests/test_ownership_transfer.py` | created |
| `app/src/app/features/user/core/settings/users/transfer-ownership-modal.component.{ts,html}` | created |
| `app/src/app/features/user/core/settings/users/users-page.component.{ts,html}` | modified — render the [Transfer ownership] button + wire modal |
| `app/src/app/features/user/core/settings/users/users.service.ts` | modified — `transferOwnership(targetId, demoteToRoleId)` |

**~7 files. No migrations.**

## Tests

`api/tests/test_ownership_transfer.py`:

- **Happy path:** Owner A transfers to Admin B → 200; B's membership.role_id is now Owner; A's is now Admin; A's `/users/me` returns demoted permission set; B's returns Owner perms; one new `ownership.transferred` audit row references both members.
- **Atomicity:** monkey-patch the second UPDATE to fail → transaction rolls back; both A and B's role_ids unchanged; no audit row written.
- **Non-Owner caller:** Admin C attempts transfer → 403.
- **Target not in same org:** Owner A attempts transfer to D (in a different org) → 422.
- **Self-transfer:** Owner A targets A → 422.
- **Target already Owner:** impossible by invariant, but test the safeguard — manually set up two Owner rows in a test fixture, attempt transfer → 422 with a "multiple owners detected" message.
- **demote_to_role_id omitted, Admin role missing:** Owner deleted Admin from their org, then attempts transfer without a demote target → 422 asking for explicit `demote_to_role_id`.
- **Single-Owner invariant intact post-transfer:** count `tbl_organization_members` rows in this org with role.name='Owner' → exactly 1.

## Smoke

```
.\docker-helper.cmd upgrade   # no-op
docker exec template_api-api-1 pytest tests/test_ownership_transfer.py -v

# Browser:
#   sign up as Owner A. Invite B as Employee. B accepts (Phase 2.5.6 flow).
#   A: /user/settings/users → [Transfer ownership]
#   modal: target=B, demote=Admin, type org name, confirm → submit
#   toast "Ownership transferred to B"
#   /user/settings/users → A's role badge now reads Admin; B's now reads Owner
#   /user/settings/users → A no longer sees [Transfer ownership] button
#   Log in as B → A's row visible, B's role badge reads Owner, [Transfer ownership] button visible
#   Audit log: SELECT * FROM audit_logs WHERE action = 'ownership.transferred' → one row carrying both member ids
```

## Risks

- **Active-session JWT staleness:** A's JWT still references "Owner" in claims (if claims include role). Step 4 of this track and Phase 1.6's JWT design need to read permissions from the live DB on each request, not from JWT claims. Verify before this step ships — if JWT carries role, A could still hit Owner-only routes for the next 15 minutes. Mitigation: the endpoint can also bump A's `token_id` so the JWT is invalidated on next request; user is forced to re-login. (Existing template has `token_id` invalidation infra per CLAUDE.md.)
- **B is inactive at transfer time:** validate `target.is_active = true` server-side; UI dropdown only lists active members.
- **Demoted Owner left without any role:** if `demote_to_role_id` resolves to a role that doesn't exist at commit time (race with a delete), the second UPDATE fails and the whole transaction rolls back. Safe.

## Rollback

Revert the 7 source files. No data lost (no migrations).
