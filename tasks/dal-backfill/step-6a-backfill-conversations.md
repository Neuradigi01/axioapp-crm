# Step 6a — Backfill DAL (conversations + its helper services)

**Goal:** Create `data_access.py` for the conversations module. Move all SQL/ORM out of `service.py` AND out of the per-concern helper services (`notes_service.py`, `tags_service.py`, `whatsapp_session.py`, `export.py`, `media_upload.py`). Behaviour unchanged.
**Status:** COMPLETED
**Depends on:** Step 6.
**Effort:** ~1 day (largest single-module backfill in the track).

---

## Why this is its own step

Step 6 covered `custom_fields` + `email`. `conversations` was deferred per Step 6's own size warning (> 400 lines → split). The module is by far the largest in the codebase that needs DAL backfill:

| File | Lines |
|---|---|
| `conversations/service.py` | 928 |
| `conversations/notes_service.py` | 184 |
| `conversations/tags_service.py` | 356 |
| `conversations/whatsapp_session.py` | 70 |
| `conversations/export.py` | 286 |
| `conversations/media_upload.py` | 219 |
| **Total service-layer code** | **2,043** |

Doing it as one focused step keeps the diff reviewable; bundling it with custom_fields + email would have made Step 6 unreadable.

## Scope

In-scope:
- `core/conversations/data_access.py` — **NEW**. Holds every query currently scattered across the 6 service files above.
- `core/conversations/service.py` — refactored to delegate to DAL.
- `core/conversations/notes_service.py` — refactored to delegate to DAL.
- `core/conversations/tags_service.py` — refactored to delegate to DAL.
- `core/conversations/whatsapp_session.py` — refactored to delegate to DAL.
- `core/conversations/export.py` — refactored to delegate to DAL (the bulk export query is one composite stmt; move as-is).
- `core/conversations/media_upload.py` — refactored to delegate to DAL (FK existence checks, message-id lookups).
- Cross-module DAL usages (other modules' services that reach into `conversations` queries) get updated to call through `conversations.service` instead.

Out of scope:
- The `conversations/adapters/` subfolder (WhatsApp / Email adapters). They translate provider payloads → internal models — DAL extraction for adapters is a separate concern; keep their inline writes for now.
- Behaviour changes, new endpoints, new permission checks.

## Files to touch

| File | Action | What |
|---|---|---|
| `core/conversations/data_access.py` | **NEW** | All SQL/ORM extracted from the 6 service files |
| `core/conversations/service.py` | modify | Delegate every query to DAL; transactions stay |
| `core/conversations/notes_service.py` | modify | Same pattern |
| `core/conversations/tags_service.py` | modify | Same pattern |
| `core/conversations/whatsapp_session.py` | modify | Same pattern |
| `core/conversations/export.py` | modify | Bulk export query → DAL |
| `core/conversations/media_upload.py` | modify | Existence checks → DAL |

**~7 files. Could split further if any single service file's edit set exceeds the 400-line cap.**

## Plan

1. Inventory every query across the 6 service files. Expect ~25-40 DAL functions when done.
2. Bucket them by entity:
   - Thread reads (list, get_by_id, get_with_messages, get_by_channel_external_id)
   - Message reads (list_for_thread, get_by_id, count_for_thread)
   - Note reads (list_for_thread, get_by_id)
   - Tag reads + applications
   - WhatsApp session reads
   - Media metadata reads
   - Cross-table joins for export
3. Write `data_access.py` with sub-section headers per bucket.
4. Refactor each service file one at a time. Run `python -c "import ..."` after each so syntax errors surface immediately.
5. Smoke after each refactor.

## DB changes / migrations

None.

## Tests

Run existing pytests. Conversations has the deepest coverage in the project — aim for green before declaring done.

## Smoke

- **List threads:** `/user/conversations` → list loads.
- **Open thread:** click a WhatsApp thread → messages render in order.
- **Reply:** send a reply → message persists, recipient sees it.
- **Notes:** add an internal note → appears on the thread; only visible to staff.
- **Tags:** apply/remove a tag → reflected in list filter.
- **Export:** export thread → CSV/JSON download contains the right rows.
- **Media:** upload a media attachment → preview renders; URL persisted.

## Risks

- Cross-module callers (e.g. `dashboard/service.py`, `reporting/*`) that read directly from conversations tables. Grep before starting and update those paths to go through `conversations.service` calls.
- `whatsapp_session.py` has tight coupling to the WhatsApp 24-hour-window logic — preserve the exact predicate (`last_inbound_at >= now() - 24h AND status='active'`).
- Export's composite JOIN must come back intact — service does the row-shaping; DAL just hands back the rows.

## Self-check (10 rules)

Pure relocation. ✓ `core/` never imports `packs/`. ✓ org_id auto-filter preserved on every DAL function. ✓ Custom-fields engine untouched. ✓ Forms untouched. ✓ Sidebar/registry untouched. ✓ Permissions unchanged. ✓ Pack manifest untouched. ✓ Stop-and-report — almost certainly needs multiple sub-stops if it bumps the 400-line cap. ✓ No TODOs / commented-out code. ✓
