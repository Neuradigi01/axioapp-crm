# Step 14 — Tags and labels on conversations

**Goal:** Org-scoped tags for conversations with CRUD, assign/unassign, multi-tag OR filter in inbox, and chip display in list rows + conversation header.
**Status:** COMPLETED
**Depends on:** Step 13 (conversation-level patterns established).

---

## Scope

In-scope:
- New table `tbl_conversation_tags` (org-scoped, RLS): id, org_id, name, color, created_by_user_id, created_at.
- New join table `tbl_conversation_tag_assignments` (org-scoped, RLS): id, org_id, conversation_id, tag_id, tagged_by_user_id, tagged_at.
- Endpoints:
  - `GET /api/v1/conversations/tags`
  - `POST /api/v1/conversations/tags`
  - `PATCH /api/v1/conversations/tags/{id}`
  - `DELETE /api/v1/conversations/tags/{id}` (cascade)
  - `POST /api/v1/conversations/{id}/tags`
  - `DELETE /api/v1/conversations/{id}/tags/{tag_id}`
- Extend `GET /api/v1/conversations?tag_ids=...` (OR semantics).
- New permission `settings.conversations.manage` for tag CRUD; assignment uses existing `conversations.write`.
- Frontend: tag chips inline in list rows (max 3 visible + "+N more"); tag manager dropdown in conversation header; filter chip in inbox.
- Fixed palette of ~12 accessible colors.
- Search + create-inline within tag picker.

Out of scope:
- Tag-based auto-actions — Step 17 (keyword/automation engine).
- Bulk-tag operations — defer to follow-up.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/conversations/models.py` | New tables |
| `API/alembic/versions/<ts>_conversation_tags.py` | **NEW** migration |
| `API/src/app/core/conversations/tags_service.py` | **NEW** |
| `API/src/app/core/conversations/router.py` | New endpoints |
| `API/src/app/core/conversations/module.py` | Register `settings.conversations.manage` |
| `APP/.../conversations/list/tag-chip.component.ts` | **NEW** |
| `APP/.../conversations/header/tag-manager.component.ts` | **NEW** dropdown |
| `APP/.../conversations/filters/tag-filter.component.ts` | **NEW** filter chip |
| `APP/.../conversations/conversations.service.ts` | New methods |
| `API/tests/conversations/test_tags.py` | **NEW** |

**~10 files. ~600 lines.**

## Plan

1. Migration: two tables with RLS; UNIQUE on `(org_id, lower(name))` to prevent dupes.
2. Service: enforce permission on CRUD; cascade unassignment on tag delete.
3. Endpoint extension: pagination preserved; tag filter is OR.
4. Frontend chip rendering uses fixed palette mapping name → color.
5. Tag manager: typeahead with `+ Create "<typed>"` row when no match.
6. Filter chip integrates with saved-views infra (existing inbox).
7. Tests: full CRUD + assignment + filter + permission gate + dupe rejection.

## DB changes / migrations

Two new tables. Indexes on org_id + foreign keys.

## Tests

8 pytest + 3 Jest.

## Smoke

```
1. Conversation header → tag manager → create "high-value" with red.
2. Apply "high-value" to current conversation → chip appears in header + list row.
3. Inbox tag filter chip → select "high-value" → list filters.
4. Multi-select "high-value" + "urgent" → OR filter applied.
5. Rename "high-value" to "vip" → chip everywhere updates.
6. Delete tag → unassigned from all conversations + filter resets.
7. Sales-Junior without settings.conversations.manage → can assign existing tags, cannot create/edit/delete.
```

## Risks

- Tag explosion (hundreds of tags) — list view paginates + searches.
- Color palette accessibility — fixed palette avoids low-contrast choices.

## Self-check (10 rules)

All `core/conversations/`. ✓. New tables org_id + RLS. ✓. No custom-field changes (tags are first-class entities). ✓. Static schema. ✓ N/A. New permission registered. ✓ Rule 6. pack.yaml untouched. ✓. 10 files / ~600 lines. ✓ at edge. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 14 — Tags & labels
Files: 10
Verify: CRUD + assignment + filter + permission split.
Tests: 8 pytest + 3 Jest.
Next: Step 15 — 24-hour session window banner.
Awaiting "proceed".
```
