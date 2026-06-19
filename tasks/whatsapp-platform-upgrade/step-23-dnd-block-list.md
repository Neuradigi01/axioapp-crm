# Step 23 — DND / block list + conversation export (DPDP right-to-access)

**Goal:** Block list per org (numbers we won't send to / accept from). Inbound from blocked silently dropped; outbound refuses. Plus DPDP right-to-access: export a contact's full data (conversations, opt-in history, deals) as JSON + PDF.
**Status:** Pending
**Depends on:** Step 22 (consent events table).

---

## Scope

In-scope:
- New table `tbl_whatsapp_blocked_numbers` (org-scoped, RLS):
  - id, org_id, phone_number, blocked_reason ENUM (`spam` / `fraud` / `requested` / `harassment`), blocked_by_user_id, blocked_at, notes TEXT
- Inbound webhook: check block list early → drop the message (no conversation row, no auto-reply).
- Outbound: refuse to send to blocked numbers (400 with reason).
- Endpoints:
  - `GET /api/v1/whatsapp/block-list` (paginated)
  - `POST /api/v1/whatsapp/block-list`
  - `DELETE /api/v1/whatsapp/block-list/{id}`
- Permission `whatsapp.opt_in.manage` (consolidates with Step 22).
- New Settings sub-page WhatsApp → Block List.
- Quick "Block this number" action from conversation header with reason picker.
- Conversation export: `POST /api/v1/conversations/{id}/export` → CSV + PDF transcript (excluding internal notes per Step 13).
- DPDP right-to-access: `GET /api/v1/contacts/{id}/data-export` → JSON + PDF bundle (conversations + opt-in history + related deals/leads).

Out of scope:
- DPDP erasure — separate compliance track.
- Org-wide block of entire country prefixes — out of v1.

## Files to touch

| File | Action |
|---|---|
| `API/src/app/core/integrations/whatsapp/block_list.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/models.py` | New table |
| `API/alembic/versions/<ts>_block_list.py` | **NEW** |
| `API/src/app/core/integrations/whatsapp/automation_router.py` | Extend with block-list CRUD |
| `API/src/app/core/integrations/whatsapp/webhook.py` | Block-check early in inbound pipeline |
| `API/src/app/core/integrations/whatsapp/adapters/whatsapp.py` | Block-check before outbound |
| `API/src/app/core/conversations/export.py` | **NEW** transcript generator |
| `API/src/app/core/contacts/data_export.py` | **NEW** DPDP bundle |
| `APP/.../whatsapp/block-list/block-list-page.component.ts` | **NEW** |
| `APP/.../conversations/header/block-number-action.component.ts` | **NEW** |
| `APP/.../conversations/header/export-button.component.ts` | **NEW** |
| `APP/.../contacts/detail/data-export-button.component.ts` | **NEW** |
| `API/tests/integrations/test_block_list.py` | **NEW** |
| `API/tests/contacts/test_data_export.py` | **NEW** |

**~14 files. ~900 lines.**

## Plan

1. Migration creates block_list with RLS + unique on `(org_id, phone_number)`.
2. Block-check service called from webhook (early) and adapter (pre-send).
3. Export pipeline: CSV (msg per row) + PDF (formatted transcript via existing PDF service).
4. DPDP bundle: zip of JSON metadata + PDF transcript + opt-in history. Email link to owner.
5. Frontend block-list page: table + search + bulk unblock + quick add modal.
6. Tests cover: inbound drop, outbound refuse, export shape, DPDP bundle completeness, permission.

## DB changes / migrations

One new table.

## Tests

10 pytest + 3 Jest.

## Smoke

```
1. Block +91 99XXX with reason "spam" via Settings → Block List.
2. Send inbound from that number → no conversation row created. Audit log captures drop.
3. Try campaign send including blocked number → blocked recipient skipped.
4. Conversation header → "Block this number" → adds to list with reason.
5. Conversation export → CSV + PDF downloaded. Internal notes excluded.
6. Contact detail → "Export my data" → ZIP downloaded with conversations + opt-in history + deals.
7. Sales-Junior cannot block — 403.
```

## Risks

- Outbound check must hit before rate-limit / template-approval checks.
- Block-list lookup performance: index on (org_id, phone_number); cache hot orgs in Redis if needed.
- PDF generation can be slow — async job for large conversations.

## Self-check (10 rules)

`core/integrations/whatsapp/` + `core/conversations/` + `core/contacts/`. ✓. org_id + RLS. ✓. No custom-field changes. ✓. Static UI. ✓ N/A. New sub-page registered. ✓. `whatsapp.opt_in.manage` permission reuse. ✓. pack.yaml untouched. ✓. 14 files / ~900 lines (at edge — could split DPDP export to its own step if too big). ✓. Stop-report. ✓. No TODOs. ✓.

## Stop & report

```
Step 23 — DND / block list + DPDP export
Files: 14
Verify: block silently drops inbound + outbound; conversation export excludes notes; DPDP bundle complete.
Tests: 10 pytest + 3 Jest.
Phase 8 (Compliance) complete. Next: Step 24 — click-to-WhatsApp attribution.
Awaiting "proceed".
```
