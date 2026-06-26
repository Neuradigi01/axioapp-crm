# Step 9 — Routing actions (round-robin / least-loaded / territory / skill)

**Goal:** Register the lead-routing action handlers — assign a lead or contact to a user via round-robin, least-loaded, territory match (by lead.region / state / city), or skill match (by user tags). Critical for sales-ops automation patterns.
**Status:** Pending
**Depends on:** Step 4 (engine + action contract). `core/users/` + `core/leads/` exist with `tbl_organization_members.role_id` + `tbl_leads.owner_user_id`.

---

## Scope

In-scope:

- `core/workflows/actions/routing.py` registering these handlers:

  - `routing.round_robin` — picks the next user in a configured pool. Node config: `{pool: 'role:Sales' | 'role:Manager' | 'team:Inbound' | 'users:[<uuid>,<uuid>...]', target: 'lead.owner_user_id' | 'contact.owner_user_id'}`. Pool resolves dynamically at fire time (users added/removed from the role since workflow creation are honored). State (which user got the LAST round-robin assignment) lives in `tbl_org_settings.routing_state JSONB` keyed by pool string — kept tiny.

  - `routing.least_loaded` — picks the user in the pool with the fewest **open leads** (lead.status NOT IN ('won','lost','archived')). Tie-broken by last-assigned-at ascending so a user idle for longer wins. Reads `tbl_leads` with the standard tenant filter.

  - `routing.territory` — picks the user whose `tbl_users.metadata->'territories'` array contains the lead's `region` / `state` / `city` (configurable which field). Falls through to a `fallback_resolver` (default: round_robin) when no user matches.

  - `routing.skill` — picks the user whose `tbl_users.metadata->'skills'` array contains the lead's `skill_required` (typically a custom field). Falls through to fallback resolver.

  - `routing.specific_user` — assigns to a configured user_id. Useful for "always send to the founder until org grows".

- Each handler returns `ActionResult(next_edge_label=None, output={'assigned_user_id': UUID, 'assignment_method': str, 'pool_size': int})` so downstream nodes can branch on the assignment (e.g. notify the assignee via send.email).

- `core/workflows/actions/routing.py` shares helpers via a tiny `_pool.py` (NOT a separate module):
  - `resolve_pool(session, *, org_id, pool_spec: str) -> list[UUID]` — pool_spec is `role:<role_name>` | `team:<team_id>` | `users:<csv of uuids>`.
  - `pick_least_loaded(session, *, org_id, candidates: list[UUID]) -> UUID`.

- Round-robin state — `tbl_org_settings.routing_state JSONB`, default `{}`. Service-layer helper `bump_routing_pointer(org_id, pool_spec) -> UUID` advances the pointer atomically (`SELECT ... FOR UPDATE` against the org_settings row). Persists `last_picked_user_id` + `last_picked_at` per pool_spec.

- Audit: the assignment writes a `tbl_activities` row (`type='assignment_changed'`) via the activities module's service so the lead's timeline shows "Auto-routed to Asha by workflow X".

- Cross-module access: assignment goes through `leads.service.assign_lead(...)` / `contacts.service.assign_contact(...)` — same as a manual reassign UI action. Permission check is against the workflow's `created_by_user_id`.

Out of scope:

- Time-zone-aware routing (assign only if the candidate is in working hours) — a v2 polish; not required for v1 seeded workflows.
- Multi-tier escalation (try territory → then skill → then round-robin) — operators string two routing nodes via a branch in the meantime.
- Weighted round-robin — equal-weight is the v1 default.
- Web-widget chat live assignment — that lives on conversations engine, not workflows.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/workflows/actions/routing.py` | **NEW** |
| `API/src/app/core/workflows/actions/__init__.py` | edit — side-effect import routing.py |
| `API/src/app/core/settings/models.py` | edit — add `routing_state` JSONB column to `tbl_org_settings` |
| `API/alembic/versions/<ts>_org_settings_routing_state.py` | **NEW** — ALTER ADD COLUMN |
| `API/tests/workflows/test_routing_actions.py` | **NEW** |

**~5 files. ~400 lines.**

## Plan

1. Migration adds `routing_state JSONB default '{}'` to `tbl_org_settings`.
2. Pool resolver + atomic pointer bump.
3. The five routing handlers.
4. Action registry side-effect import.
5. Tests: each routing mode picks the expected user against seeded org data + edge cases (empty pool, single-user pool, all-users-overloaded).

## DB changes / migrations

One ALTER TABLE — `tbl_org_settings.routing_state JSONB default '{}'`. Reversible.

## Tests

10 pytest cases:

- `round_robin` cycles through pool in order; state persisted; second fire picks next user.
- `round_robin` with single-user pool always picks that user.
- `round_robin` with empty pool returns skip_reason='no_candidates'.
- `least_loaded` picks user with fewest open leads.
- `least_loaded` tie-break by last_assigned_at ascending.
- `territory` matches by lead.region against user.metadata.territories.
- `territory` with no matching user falls through to round-robin fallback.
- `skill` matches by lead.skill_required.
- `specific_user` always returns the configured uuid.
- Assignment writes a timeline activity row.

## Smoke

```
1. Org has 3 sales reps in role 'Sales': Asha, Rahul, Priya.
2. Workflow: trigger(lead.created) → routing.round_robin(pool='role:Sales', target='lead.owner_user_id') → send.email(notify assignee).
3. publish lead.created x3 → leads assigned Asha, Rahul, Priya in order; each gets a "new lead" notification.
4. publish lead.created → cycle wraps → assigned to Asha.
5. Swap to routing.least_loaded → with Asha having 5 open leads and Rahul/Priya 2 each → next lead → assigned to Rahul (tie-broken by who's been idle longest).
```

## Risks

- Atomic pointer bump under high concurrency — `SELECT ... FOR UPDATE` on a tiny org_settings row is fine; lock-hold time ~1ms.
- "Workflow's created_by_user assigned, but they don't have leads.assign perm" → assignment fails with PermissionDenied skip_reason. Document that workflow creators need the perms their actions exercise.
- Empty pool at fire time (every Sales rep was removed since workflow saved) — skip_reason='no_candidates' lands on step_run; operator sees in run history. No crash.

## Self-check (10 rules)

`core/workflows/actions/` + tiny `core/settings/` extension. ✓ org_id-scoped. ✓ N/A custom fields. ✓ N/A dynamic forms. ✓ N/A sidebar. Permissions enforced via origin services. pack.yaml untouched. ✓ 5 files / ~400 lines. Stop-report. ✓ No TODOs. ✓.

## Stop & report

```
Step 9 — Routing actions
Files: 5
Verify: 5 routing modes operational; round-robin cycles correctly; least-loaded honors current load; territory/skill fall through to fallback.
Tests: 10 pytest cases.
Awaiting "proceed".
```
