# Step 4 — `GET /api/v1/variables` router with composer-permission dispatch

**Goal:** ship the unified `GET /api/v1/variables?entity=&channel=&event=` endpoint. Composer-permission gate (union of `templates.edit / workflows.edit / chatbots.edit / campaigns.edit / automations.edit / ai_assistants.edit`); explicit org_id filter; per-user rate limit; ETag + Cache-Control.
**Phase:** Variables Unification track — step 4/13
**Depends on:** Steps 1, 2, 3
**Status:** Pending

## Scope

**In-scope:**
- `core/variables/router.py` exposes `GET /api/v1/variables?entity=<name>&channel=<name>&event=<name>`. Returns:
  ```json
  { "groups": [
      { "key": "contact", "label": "Contact", "variables": [<VariableDef>, ...] },
      { "key": "contact_custom", "label": "Contact — Custom fields", "variables": [...] },
      ...
    ],
    "truncated": false
  }
  ```
- `core/variables/service.list_variables(session, org_id, user, entity, channel, event)` — assembles standard (from `constants.py`) + custom (via `custom_field_bridge`) groups.
- **Composer-permission dispatch:** endpoint accepts if user has ANY of `templates.edit`, `workflows.edit`, `chatbots.edit`, `campaigns.edit`, `automations.edit`, `ai_assistants.edit`. Actual perm-key strings verified against `core/permissions/registry.py` at implementation.
- **Sensitive-field gate:** custom fields marked `is_sensitive=true` filtered out unless caller ALSO has the entity's per-object read perm (`contacts.read` for `entity=contact`, `invoices.read` for `entity=invoice`, etc.). Non-sensitive standard fields always visible.
- **Response headers:** `Cache-Control: private, max-age=60`, `ETag: "<hash of response body>"`. Client 304-conditional-fetch supported.
- **Response cap:** `variables[]` hard-capped at 500 total across all groups; `truncated: true` flag if hit.
- **Per-user rate limit:** 60 rps via existing rate-limit middleware (Redis-backed if available, else in-process).
- Validation: `entity` must be in known-entity set (returned as full static list in 400 error — NOT filtered by caller perm, per Attacker F6 fix).
- Registers empty router in `main.py` include (already done Step 1).

**Out of scope:**
- Provider registry (this step declares standard groups inline in the service; the registry pattern deferred as no benefit for the 8 static entities per Architect finding).
- `{{event.*}}` handling (Step 5).
- Stale-ref detector (Step 6).

## Files to touch
- `api/src/app/core/variables/router.py` (modified — endpoint).
- `api/src/app/core/variables/service.py` (modified — `list_variables` composition).
- `api/src/app/core/variables/data_access.py` (modified — thin `list_custom_for_org(session, org_id, entity_types)` wrapper on custom_fields DAL with explicit `org_id` param).
- `api/src/app/core/variables/schemas.py` (modified — `VariablesResponse`, `VariableGroup` Pydantic models).
- Tests.

## Plan
1. Implement `list_variables()` — reads standard variables from `constants.ALLOWED_VARIABLES_BY_CHANNEL[channel]` + custom via `custom_field_bridge.to_field_spec` (batch via `list_fields_by_entities(org_id=...)`).
2. Implement `_ENTITY_READ_PERM` map + `_COMPOSER_PERMS` set. Endpoint checks composer OR at least one; then sensitive-field gate uses entity-read perm.
3. Add hardcoded `_KNOWN_ENTITIES = {"contact","lead","appointment","quote","invoice","org","sender","user","task","assignee","chatbot_runtime"}`.
4. Add ETag calculation (SHA256 of JSON body).
5. Add response cap check.
6. Wire per-user rate-limit dependency.

## DB changes / migrations
None.

## Tests to add
- `test_variables_endpoint_returns_system_and_custom_for_contact_email`.
- `test_variables_endpoint_401_unauthenticated`.
- `test_variables_endpoint_403_no_composer_permission`.
- `test_variables_endpoint_composer_without_entity_read_perm_gets_non_sensitive_only` — user has `templates.edit` but not `invoices.read`; `entity=invoice` returns standard invoice fields but NOT `is_sensitive=true` custom fields.
- `test_variables_endpoint_composer_with_entity_read_gets_sensitive` — same user + `invoices.read` → sensitive fields included.
- `test_variables_endpoint_400_unknown_entity_returns_full_static_known_list_not_filtered_by_perm`.
- `test_variables_endpoint_tenant_scoped_with_rls_disabled` — RLS mocked off; explicit `org_id` in DAL still returns tenant-scoped results.
- `test_variables_endpoint_response_cap_500_flags_truncated`.
- `test_variables_endpoint_etag_and_cache_control_headers_present`.
- `test_variables_endpoint_304_on_matching_etag`.
- `test_variables_endpoint_rate_limit_429_over_60_rps`.

## Verification checklist
- Backend: all named tests pass.
- Backend: manual `curl -H "Authorization: Bearer <token>" 'http://localhost:8000/api/v1/variables?entity=contact&channel=email'` returns groups.
- Backend: response includes `ETag` header; second call with `If-None-Match` returns 304.
- Backend: cross-tenant leak test passes with RLS off (belt only).

## Self-check (10 rules)
- [ ] Rule 1: core only.
- [ ] Rule 2: no new DB.
- [ ] Rule 3: reads via extended DAL.
- [ ] Rule 4: N/A.
- [ ] Rule 5: N/A.
- [ ] Rule 6: reuses existing composer perms; no new perm keys.
- [ ] Rule 7: N/A.
- [ ] Rule 8: ~5 files — under limit.
- [ ] Rule 9: stop and report.
- [ ] Rule 10: no TODOs.

## Stop & report
Await "proceed".
