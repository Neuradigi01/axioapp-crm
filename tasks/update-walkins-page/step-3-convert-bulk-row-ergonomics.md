# Step 3 — Walk-in → Lead conversion + bulk reassign + row ergonomics (tel / WhatsApp, URL state, styled confirm)

**Goal:** close the showroom-to-funnel gap with a Convert-to-Lead button; add bulk reassign and bulk mark-done; finish row-level UX (click-to-call, WhatsApp, URL state, styled confirm delete).

**Depends on:** Step 2 + `update-contacts-page/` Steps 3–4 (`BulkActionBar`, `ReassignModal`, `ConfirmDialog`, `PhoneLink`, `WhatsappLink`, `UrlFilterStateDirective`), and `update-leads-page/` Step 1 (the lead state-machine + create paths).

## Files changed

### Modified backend
- `API/src/app/core/walk_ins/router.py` — `POST /walk-ins/{id}/convert`, `POST /walk-ins/{id}/reassign`, `POST /walk-ins/bulk-reassign`, `POST /walk-ins/bulk-mark-done`.
- `API/src/app/core/walk_ins/service.py` — `convert_walk_in_to_lead(...)`, `reassign_walk_in`, `bulk_reassign_walk_ins`, `bulk_mark_done`.
- `API/src/app/core/walk_ins/schemas.py` — `WalkInConvertRequest`, `WalkInConvertResponse`, `WalkInReassign`, `WalkInBulkReassign`, `WalkInBulkMarkDone`.

### New frontend
- `APP/src/app/features/user/core/walk-ins/walkin-convert-modal.component.ts`
- `APP/src/app/features/user/core/walk-ins/walkin-convert-modal.component.html`

### Modified frontend
- `APP/src/app/features/user/core/walk-ins/walk-ins-api.service.ts` — add `convert`, `reassign`, `bulkReassign`, `bulkMarkDone`.
- `APP/src/app/features/user/core/walk-ins/walk-ins.page.ts` — selection state, URL state, bulk handlers.
- `APP/src/app/features/user/core/walk-ins/walk-ins.page.html` — checkbox column, BulkActionBar, ReassignModal, ConfirmDialog, Convert modal mount; tel/WhatsApp on phone cell.

### Tests
- `API/tests/core/walk_ins/test_convert_and_bulk.py` (new)

## Backend — `POST /walk-ins/{id}/convert`

Body:
```json
{
  "contact_link_mode": "create" | "link" | "auto",
  "linked_contact_id": "<uuid> | null",
  "source": "<string | null>",   // e.g. "Walk-in"
  "notes": "<string | null>"
}
```

Service (atomic):
1. Resolve / create `contact` (same auto-match phone+email logic as `update-leads-page/` Step 4).
2. Create a `lead` with `contact_id`, `source` (default "Walk-in"), owner = walk-in's `assigned_to_id`, custom_data = walk-in's `custom_data`.
3. Link the walk-in: `walk_in.linked_lead_id = <new lead id>` (column may already exist — confirm in migration; if not, add a nullable column in this migration).
4. Audit activity `type='convert'` on the walk-in with `body={"contact_id":..., "lead_id":...}`.
5. Don't auto-advance walk-in status — convert is independent.

Permissions: `walk_ins.write` AND `contacts.write` AND `leads.write`.

## Backend — bulk endpoints

- `POST /walk-ins/{id}/reassign` — body `{"assigned_to_id": uuid | null}`. `walk_ins.reassign`.
- `POST /walk-ins/bulk-reassign` — `walk_ins.reassign`. Max 200 ids.
- `POST /walk-ins/bulk-mark-done` — `walk_ins.write`. Each row must be in `with_staff` (state-machine validated); per-row errors aggregated in the response.

## Frontend — `walkin-convert-modal.component`

Inputs: `walkIn`.

Body:
- Section 1: **Contact** — Create / Link / Auto radio.
- Section 2: **Lead** — source dropdown (defaults to "Walk-in"), notes textarea.
- Cancel / Convert.

On confirm → `api.convert(walkInId, payload)` → success snackbar "Lead created" with link to the lead detail.

## `walk-ins.page.ts` — selection + URL state

Pattern matches contacts/leads:
- Selection signal + bulk actions array (Reassign / Mark Done / Delete — all permission-gated).
- URL state config covers `assignee`, `status`, `date_chip`, `scope`, `sort`, `order`, `page`.

## `walk-ins.page.html`

- Checkbox column + BulkActionBar mount.
- Phone cell wrapped with `[appPhoneLink]` + WhatsApp icon `[appWhatsappLink]`.
- Per-row **Convert to Lead** button next to the status-transition buttons (gated `leads.write`).
- Replace `window.confirm` paths with `<app-confirm-dialog>`.

## Test `test_convert_and_bulk.py`

1. Convert with `auto` and clean phone → new contact + new lead + walk-in linked.
2. Convert when walk-in already has `linked_lead_id` → 409 "already converted."
3. Convert with cross-tenant `linked_contact_id` → 422.
4. Bulk reassign 3 walk-ins → 3 activities written, all rows updated.
5. Bulk mark-done with one walk-in in `done` → returns partial-success.

## Acceptance

1. Convert-to-Lead button on walk-in row + detail (modal). Creates lead + contact + audit entry; walk-in shows "Linked to lead" indicator after.
2. Bulk reassign / bulk mark-done / bulk delete work on selected rows.
3. tel / WhatsApp icons on phone cells.
4. URL state round-trips.
5. Styled confirm dialog replaces `window.confirm`.
6. Junior staff sees no convert / no reassign / no bulk.

## Lucide icons used

`arrow-right-circle` (convert), `users` (link to lead), `phone`, `message-circle`.

## Self-check vs the 10 rules

- ✅ Rule 1 — convert composes Layer 1 only.
- ✅ Rule 8 — 9 files; under limit.
- ✅ Rule 10 — atomic convert; bulk errors aggregated, not silenced.

## Stop-and-report template

> ✅ Step 3 complete. Walk-ins track done.
> **Files changed:** 9 (3 modified backend, 2 new FE convert modal, 3 modified FE page + service, 1 new test).
> **What you can verify:**
> 1. Convert flow creates linked lead + contact in one transaction.
> 2. Bulk reassign / mark-done / delete on selected.
> 3. tel / WhatsApp on phone cells.
> 4. URL state preserves filters.
> 5. Walk-in `linked_lead_id` populated after convert.
> **Tests added:** `test_convert_and_bulk.py` (5).
> **Self-check:** all 10 rules ✅.
> **Walk-ins track complete.** Recommend proceeding to `update-appointments-page/`.
