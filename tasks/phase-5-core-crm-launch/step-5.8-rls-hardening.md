# Step 5.8 — RLS hardening

**Goal:** Audit every table for RLS policies. Add tests that switch tenants and assert isolation.
**Phase:** 5 — Core CRM v1 Launch
**Depends on:** all prior tables
**Status:** Pending

## Scope
**In-scope:**
- Audit script `scripts/audit_rls.py`: lists every TenantScoped table that lacks RLS or a policy. Fails CI if any are missing.
- Cross-tenant tests: `tests/test_rls_full_audit.py` — for every TenantScoped table, asserts queries from org B cannot see org A rows.
- Penetration scenarios: forged JWT with wrong org_id; missing `SET LOCAL app.org_id`; SQL injection on filters.

## Files to touch
- `api/scripts/audit_rls.py` (created)
- `api/tests/test_rls_full_audit.py` (created)
- Any migration that's missing RLS (modified)

## Plan
1. Audit script reflects on metadata, finds all `TenantScoped` tables, queries `pg_policies`, fails if any has no policy.
2. Full-audit test creates two orgs, seeds one row per table for each, switches contexts, asserts visibility.

## Tests to add
- `tests/test_rls_full_audit.py` — comprehensive isolation test.
- `tests/test_jwt_org_id_tamper.py` — tampered tokens rejected.

## Verification checklist
**Backend:**
- run: `python scripts/audit_rls.py` → ✓.
- pytest green.

## Self-check (10 rules)
- [ ] Rule 2 fully verified with tests, not just code review.

## Stop & report
Await "proceed" before Step 6.5.
