# Step 18 — Auto-assignment rules (round-robin / load-balanced / tag-based / team-based)

**Goal:** Auto-assign new conversations to staff using configurable strategies. Round-robin distributes evenly; load-balanced picks lightest queue; tag-based maps tags to users; team-based maps to staff groups.
**Status:** COMPLETED
**Depends on:** Step 14 (tags), Step 17 (automation page exists).

---

## Scope

In-scope:
- Table `tbl_whatsapp_assignment_rules` (org-scoped, RLS): id, org_id, name, strategy ENUM, config JSONB, enabled, priority.
- Strategies:
  - `round_robin` — config: `eligible_user_ids` list
  - `load_balanced` — config: `eligible_user_ids` + cap_per_user
  - `tag_based` — config: `{ tag_id: user_id }` map
  - `team_based` — config: `team_id` (uses existing teams module if present, else falls back to user list)
- On new conversation creation (or `assignee_id IS NULL` after greeting/keyword run) → pick rule by priority → assign.
- Skip-nights/weekends option uses Step 11's business hours.
- Skip offline staff (`is_active = false` or last_seen > N min).
- Endpoints under `/api/v1/whatsapp/assignment-rules`.
- Frontend Automation sub-page → "Assignment" tab.

Out of scope:
- SLA-based reassignment (escalate if not responded in N min) — defer to a Phase 7 analytics step.
- Time-zone-aware skip — assumes single org timezone.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/assignment_engine.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | New table |
| `API/alembic/versions/<ts>_assignment_rules.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/automation_router.py` | Extend with rule CRUD |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Hook into pipeline post-greeting |
| `APP/.../whatsapp/automation/assignment-rule-editor.component.ts` | **NEW** |
| `APP/.../whatsapp/automation/automation-page.component.ts` | Add Assignment tab |
| `API/tests/integrations/test_assignment_engine.py` | **NEW** |

**~8 files. ~500 lines.**

## Plan

1. Migration with single-table + indexes; config JSONB validated per strategy at insert.
2. Engine: pure-function pick given current load snapshot + eligible users + strategy config.
3. Round-robin state: persist last-assigned index per rule (single int column or Redis counter).
4. Load-balanced: count of open conversations per user from `tbl_conversations`.
5. Skip-offline: join `tbl_users.is_active` + `last_seen_at`.
6. Frontend: strategy picker → renders strategy-specific config form.
7. Tests: each strategy distribution; offline-skip; tag-mapped; priority ordering.

## DB changes / migrations

One new table. Optional `last_assigned_index` column for round-robin persistence (or Redis).

## Tests

8 pytest + 2 Jest.

## Smoke

```
1. Create round-robin rule across [Ravi, Asha, Devang]. Enable.
2. Three new contacts → assigned in rotation.
3. Mark Asha offline → next assignment skips her → Devang then Ravi.
4. Switch to load-balanced → next new convo goes to user with fewest open conversations.
5. Switch to tag-based: "warranty" → Asha. Tag a new convo "warranty" → assigned to Asha.
6. Skip-nights enabled + after-hours → new convo stays unassigned with reason "after-hours".
7. Disable rule → unassigned again.
```

## Risks

- Concurrent webhooks may pick same user in round-robin — atomic counter (Redis INCR or DB row lock).
- Tag-based rule with deleted tag → engine skips gracefully + alerts owner.
- Empty eligible_user_ids → rule disabled with banner.

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. No custom-field changes. ✓. Static config forms. ✓ N/A. New tab under existing sub-page. ✓. Existing `whatsapp.automation.manage` permission. ✓. pack.yaml untouched. ✓. 8 files / ~500 lines. ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 18 — Auto-assignment rules
Files: 8
Verify: each strategy distributes correctly; offline skip; tag mapping; concurrency safe.
Tests: 8 pytest + 2 Jest.
Next: Step 19 — AI agent wiring.
Awaiting "proceed".
```
