# Step 17 — Keyword triggers + auto-tagging

**Goal:** Rule engine for "if inbound message matches keyword → execute actions" (reply text, reply template, tag conversation, assign to user, escalate to AI). Auto-tagging from content piggybacks the same engine.
**Status:** Pending
**Depends on:** Step 16 (auto-reply pipeline exists), Step 14 (tags).

---

## Scope

In-scope:
- Tables (org-scoped, RLS):
  - `tbl_whatsapp_keyword_rules` (id, org_id, name, keywords TEXT[], match_type ENUM (`contains`/`exact`/`regex`), enabled, priority INT)
  - `tbl_whatsapp_keyword_actions` (id, org_id, rule_id, action_type ENUM (`reply_text`/`reply_template`/`tag_conversation`/`assign_to_user`/`escalate_to_ai`), action_config JSONB)
- On inbound → after greeting/away → evaluate active keyword rules in priority order → execute actions.
- Endpoints under `/api/v1/whatsapp/keyword-rules`: CRUD + reorder + test.
- Per-contact per-rule cooldown to prevent loops (default 60s).
- Permission `whatsapp.automation.manage`.
- Frontend Automation sub-page rule builder:
  - List of rules with drag-to-reorder priority.
  - Editor: keywords + match_type + stack of actions (template/text/tag/assign/AI).
  - Test panel: paste a sample message → see which rules would fire + actions executed (dry-run).

Out of scope:
- Auto-assignment rules (round-robin/team-based) — Step 18 (different engine).
- AI agent details — Step 19 (this step adds `escalate_to_ai` hook only).

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/keyword_engine.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | Two new tables |
| `API/alembic/versions/<ts>_keyword_rules.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/automation_router.py` | **NEW** CRUD endpoints |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Pipeline integration |
| `API/src/app/core/integrations/whatsapp/module.py` | Register `whatsapp.automation.manage` |
| `APP/.../whatsapp/automation/automation-page.component.ts` | **NEW** (tabs for future steps) |
| `APP/.../whatsapp/automation/keyword-rule-editor.component.ts` | **NEW** |
| `APP/.../whatsapp/automation/rule-test-panel.component.ts` | **NEW** dry-run |
| `APP/src/app/features/user/user.routes.ts` | Add `/user/whatsapp/automation` |
| `API/tests/integrations/test_keyword_engine.py` | **NEW** |

**~11 files. ~700 lines.**

## Plan

1. Migration creates both tables with RLS, indexes on `(org_id, enabled, priority)`.
2. Engine evaluates rules in priority order; first matching rule fires; remaining short-circuit by default (configurable per rule for power users — opt-in only).
3. Action handlers dispatch to existing services (templates, tags, assignment, AI hook).
4. Cooldown stored in Redis (per-rule per-contact key with TTL).
5. Frontend: signal-driven rule list with drag-handle reorder; rule editor uses small action stack.
6. Dry-run endpoint accepts sample message → returns matched rule + actions list.
7. Tests cover priority ordering, cooldown, action dispatch, regex match safety (timeout).

## DB changes / migrations

Two new tables + enums; indexes.

## Tests

10 pytest + 3 Jest.

## Smoke

```
1. Create rule "pricing query" → keywords ['price', 'rate', 'cost'] / contains → action: reply with template "pricing_v1".
2. Inbound "What's the price?" → template sent within seconds.
3. Add second action: tag with "pricing-interested".
4. Re-test → both actions fired.
5. Re-send same message within 60s → cooldown prevents duplicate.
6. Dry-run panel: paste "How much for the sofa?" → shows rule matched + actions previewed.
7. Drag rule to lower priority → another rule matches first.
8. Disable rule → no longer fires.
9. Sales-Junior without automation.manage → list visible, edits blocked.
```

## Risks

- Regex match types must use timeout-bounded engine (`re2` or guard) — untrusted patterns can DoS.
- Action loop if reply template body itself matches a rule — engine ignores outbound messages.
- Priority collisions: define stable sort tiebreaker (created_at).

## Self-check (10 rules)

All `core/integrations/whatsapp/`. ✓. org_id + RLS. ✓. No custom-field changes. ✓. Rule editor static. ✓ N/A. New automation sub-page registered. ✓. New permission registered. ✓. pack.yaml untouched. ✓. 11 files / ~700 lines (at edge). ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 17 — Keyword triggers + auto-tagging
Files: 11
Verify: rule match + action dispatch + cooldown + dry-run.
Tests: 10 pytest + 3 Jest.
Next: Step 18 — auto-assignment rules.
Awaiting "proceed".
```
