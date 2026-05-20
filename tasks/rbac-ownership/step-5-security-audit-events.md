# Step 5 — Security audit events wiring

**Goal:** Every security-relevant action emits an `audit_logs` row carrying enough context to reconstruct who did what to whom. Closes the spec's audit-log requirement by wiring the five events into the modules that own them.
**Track:** RBAC, Ownership & Self-Signup
**Status:** COMPLETED — enriched `invitations.sent` (+ role_name, expires_at, invited_by_user_id), `invitations.accepted` (+ role_id, role_name, accepted_by_user_id), `invitations.revoked` (+ revoked_by_user_id); added new `roles.assigned_to_user` event in `update_user` (fires only when role_id actually changes); added `auth.access_denied` in `require_permissions` (carries path, method, required + missing keys, status_code). Existing `users.created/updated/activated/deactivated`, `roles.created/updated/deleted`, `ownership.transferred`, `auth.signup/login.success/login.failure`, `auth.password.changed` already in place. Action-key naming kept as `<module>.*` (plural) for backward compatibility — step doc used `<entity>.*` (singular) but renaming would churn the audit table; payload shape matches the spec.
**Depends on:** 1.7 (audit_logs table + `audit.log()` service), all prior steps in this track (the events they emit).

---

## Scope

No new files. ~6 modified call-sites — each one adds a single `await audit.log(...)` call right before the `db.commit()` in its parent service. Failures in `audit.log` never break the parent flow (Phase 1.7 contract).

## Events to wire

| Action key | Emitted from | Payload (`after`) |
|---|---|---|
| `invitation.sent` | `core/invitations/service.py` (Phase 2.5.6 `send_invitation`) | `{email, role_id, role_name, expires_at}` |
| `invitation.accepted` | `core/invitations/service.py` (`accept_invitation`) | `{email, role_id, role_name, accepted_by_user_id}` |
| `invitation.revoked` | `core/invitations/service.py` (`revoke_invitation`) | `{email, revoked_by_user_id}` |
| `role.created` | `core/permissions/service.py` (custom role create) | `{role_id, role_name, permission_keys: [...]}` |
| `role.edited` | `core/permissions/service.py` (role permissions update) | `before: {permission_keys: [...]}, after: {permission_keys: [...]}` (the diff is recoverable from these two) |
| `role.deleted` | `core/permissions/service.py` (role delete) | `before: {role_id, role_name, permission_keys: [...]}` |
| `role.assigned_to_user` | `core/users/service.py` (member role change) | `before: {member_id, role_id, role_name}, after: {member_id, role_id, role_name}` |
| `ownership.transferred` | `core/tenants/ownership.py` (Step 3) | `{from_member_id, to_member_id, demoted_to_role_id}` |
| `auth.access_denied` | `core/auth/middleware.py` or the dep that raises 403 | `{path, method, required_permission_keys, status_code}` — written on every 403 response from a permission dep |
| `auth.login.success` / `auth.login.failure` | already wired in Step 1.7 — verify they fire | (unchanged) |

The `entity_type` and `entity_id` columns on `audit_logs` (Phase 1.7) carry the natural object id for each event:

- For `invitation.*` → `entity_type='invitation', entity_id=<invitation.id>`
- For `role.*` → `entity_type='role', entity_id=<role.id>`
- For `ownership.transferred` → `entity_type='organization', entity_id=<org_id>` (the org changed hands)
- For `auth.access_denied` → `entity_type='access_attempt', entity_id=NULL`

## Files to touch

| File | Action |
|---|---|
| `api/src/app/core/invitations/service.py` | modified — 3 `audit.log()` calls |
| `api/src/app/core/permissions/service.py` | modified — 3 `audit.log()` calls (create / edit / delete) |
| `api/src/app/core/users/service.py` | modified — 1 `audit.log()` call (role assignment change) |
| `api/src/app/core/tenants/ownership.py` | modified — already plans to write the audit row in Step 3; this step verifies it lands with the right shape |
| `api/src/app/core/auth/dependencies.py` (or wherever `require_permissions` raises) | modified — emit `auth.access_denied` before raising 403 |
| `api/tests/test_audit_events.py` | created — assertion that each action writes the expected row |

**~6 files. No migrations. No new endpoints.**

## Tests

`api/tests/test_audit_events.py`:

For each event in the table above:

1. Trigger the action (call the service / hit the endpoint as the appropriate user).
2. Assert exactly one new row in `audit_logs` since the previous count, with the expected `action`, `entity_type`, `entity_id`, and key fields in `after` / `before`.
3. Assert `user_id`, `org_id`, `ip`, `ua` populated from `RequestContext`.

Plus one negative test:

- **Audit log failure does not break the parent action:** monkey-patch `audit.log` to raise → fire the parent action (e.g., create a role) → role is created, no audit row, no 500 to the caller. (Verifies Phase 1.7's best-effort guarantee.)

## Smoke

```
docker exec template_api-api-1 pytest tests/test_audit_events.py -v

# Manual walk-through:
# Sign up as Owner A; invite B; B accepts; A creates a custom role "Sales Lead"; A edits its perms;
# A assigns B to "Sales Lead"; A transfers ownership to B; B (now Owner) deletes "Sales Lead";
# B revokes a pending invitation; Employee C tries /user/settings/users → blocked.

# Then:
SELECT action, entity_type, entity_id, user_id, created_at
FROM audit_logs
WHERE created_at > now() - interval '10 minutes'
ORDER BY created_at;

# Expected rows, in order:
#   auth.login.success                 (A)
#   invitation.sent                    (A → B's email)
#   invitation.accepted                (B)
#   role.created                       (A → Sales Lead)
#   role.edited                        (A → Sales Lead)
#   role.assigned_to_user              (A → B becomes Sales Lead)
#   ownership.transferred              (A → B)
#   role.deleted                       (B → Sales Lead)
#   invitation.revoked                 (B)
#   auth.access_denied                 (C → /user/settings/users)
```

## Risks

- **Sensitive data in `before`/`after`:** permission_keys lists are not sensitive. Email is not sensitive in this context (already in `tbl_user_info`). Do **not** include password hashes, tokens, or 2FA secrets in any audit payload.
- **Volume:** `auth.access_denied` could spam if a misconfigured client polls a forbidden endpoint. Acceptable for now — Phase 5.5 (Reporting) can add aggregation / rate-limiting. Do not pre-optimise.
- **Cross-tenant leakage in audit_logs:** Phase 1.7 already applies RLS on this table; verify the 403-from-other-org case writes to the *target* org's audit (the org the resource belonged to), not the *caller*'s. Edge case — most 403s are within-org. If unclear at implementation time, default to caller's org and document.

## Rollback

Revert the 6 source files. No DB state to roll back (no migrations). Audit rows already written stay — they're append-only by design.
