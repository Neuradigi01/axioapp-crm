# Step 2: Filter-rules DAL + service + router + validation + per-org cap

**Status:** COMPLETED (2026-09-21) — filter-rules DAL (list, create, delete, count, dedupe-lookup) + service (create with cap + dedupe check, delete with 404) + router (3 endpoints: `GET/POST/DELETE /api/v1/email-filter-rules`) + Pydantic schemas with per-kind regex validation (email address / RFC domain / contact flag key); per-org cap `EMAIL_FILTER_RULES_MAX_PER_ORG=500`; Owner/Admin only via `email.accounts.manage`; router registered in main.py.

## Goal

CRUD for filter rules. Per-org cap. Precedence-aware read helper the gate chain uses.

## Files touched

- `api/src/app/core/email/quarantine/data_access.py` — filter rule DAL
- `api/src/app/core/email/quarantine/service.py` — CRUD + validation + precedence read
- `api/src/app/core/email/quarantine/schemas.py` — filter rule schemas
- `api/src/app/core/email/quarantine/router.py` — filter rule endpoints
- `api/tests/test_filter_rules_service.py`
- `api/tests/test_filter_rules_router.py`

## What this step does

- DAL:
  - `list_filter_rules(session, *, org_id, endpoint_id=None)`
  - `insert_filter_rule(session, *, org_id, endpoint_id, rule_type, match_kind, match_value, label, created_by_user_id)`
  - `delete_filter_rule(session, *, id, org_id)`
  - `count_rules_for_org(session, *, org_id) -> int`
  - `find_rules_for_gate(session, *, org_id, endpoint_id) -> list[FilterRule]` — reads both org-wide and endpoint-scoped, sorted by precedence
- Service:
  - `create_filter_rule(db, *, org_id, actor_user_id, payload)`:
    - Owner/Admin only.
    - Cap check: `count_rules_for_org() < EMAIL_FILTER_RULES_MAX_PER_ORG (500)` → else 409.
    - Validate `match_value`:
      - `email_address`: RFC email regex
      - `email_domain`: RFC 1035 label regex
      - `contact_flag`: must match a shipped contact flag key
    - Deduplication: `UNIQUE(org_id, endpoint_id, rule_type, match_kind, match_value)` check-then-insert.
    - Audit `filter_rule.created`.
  - `delete_filter_rule(db, *, id, org_id, actor_user_id)` — soft-delete not offered; hard delete + audit.
  - `resolve_effective_rules(db, *, org_id, endpoint_id) -> ResolvedRules` — for gate chain:
    - Load org-wide + endpoint-scoped rules.
    - Return dict-indexed by (kind, value) with rule_type + specificity score.
    - Cached 1s per (org, endpoint) via Redis to avoid DB hit per inbound.
- Router:
  - `GET /api/v1/email-filter-rules` — org-wide list + optional `endpoint_id` filter
  - `POST /api/v1/email-filter-rules` — create
  - `DELETE /api/v1/email-filter-rules/{id}` — delete

## Tests

- `test_filter_rule_create_validates_email_address_format`
- `test_filter_rule_create_validates_email_domain_format`
- `test_filter_rule_create_validates_contact_flag_key`
- `test_filter_rule_create_owner_or_admin_only`
- `test_filter_rule_create_enforces_500_per_org_cap`
- `test_filter_rule_create_rejects_duplicate`
- `test_filter_rule_delete_cross_org_returns_404`
- `test_resolve_effective_rules_merges_org_wide_and_endpoint_scoped`
- `test_resolve_effective_rules_cached_1s_per_org_endpoint`
- `test_router_list_scoped_by_org`

## Verification checklist

- [ ] All 10 tests pass
- [ ] Pin-tests pass
- [ ] Ruff clean

## Self-check

- Rule 4: pass — server-side Owner/Admin check.
- Rule 2: pass.
- DB efficiency: pass — 1s cache avoids per-inbound DB roundtrip.

## Stop-and-report

Report test pass. **Awaiting your "proceed" for Step 3.**
