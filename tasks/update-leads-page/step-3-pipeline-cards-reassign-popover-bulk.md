# Step 3 — Pipeline cards: owner avatar + last-activity badge + click-to-reassign popover + bulk select on list

**Goal:** upgrade pipeline cards so reps can read who-owns-what and when-it-was-last-touched at a glance. Add a small reassign popover when an admin clicks a card. Wire bulk-select on the list view with the shared `BulkActionBar`.

**Depends on:** Step 2 frontend + `update-contacts-page/` Step 3 (`BulkActionBar`, `ReassignModal`).

## Files changed

### New backend
- (none — bulk-reassign endpoint registered)

### Modified backend
- `API/src/app/core/leads/router.py` — add `POST /leads/{id}/reassign`, `POST /leads/bulk-reassign`, `POST /leads/bulk-update-status`, `POST /leads/bulk-delete`.
- `API/src/app/core/leads/service.py` — `reassign_lead`, `bulk_reassign_leads`, `bulk_update_status`, `bulk_delete`.
- `API/src/app/core/leads/schemas.py` — `LeadReassign`, `LeadBulkReassign`, `LeadBulkUpdateStatus`, `LeadBulkDelete`.

### New frontend
- `APP/src/app/features/user/core/leads/lead-reassign-popover.component.ts`
- `APP/src/app/features/user/core/leads/lead-reassign-popover.component.html`

### Modified frontend
- `APP/src/app/features/user/core/leads/leads-api.service.ts` — add the four bulk methods.
- `APP/src/app/features/user/core/leads/leads.page.ts` — selection state + bulk handlers.
- `APP/src/app/features/user/core/leads/leads.page.html` — checkbox column + BulkActionBar mount + Reassign-popover wiring on pipeline cards.
- `APP/src/app/features/user/core/leads/lead-card.component.ts` — emit `(reassignClick)` on the owner badge click.
- `APP/src/app/features/user/core/leads/lead-card.component.html` — owner avatar + last-activity badge + pencil button (conditional on permission).
- `APP/src/app/features/user/core/leads/pipeline-board.component.html` — wire `(reassignClick)` → open `<app-lead-reassign-popover>`.

### Tests
- `API/tests/core/leads/test_reassign_and_bulk.py` (new)

## Backend endpoints

All require `leads.reassign` (or `leads.write` for bulk delete / bulk update-status). Tenant-scoped via `TenantScoped`.

- `POST /leads/{id}/reassign` — body `{"assigned_to_id": "<uuid>" | null}`. Validates target in same org. Writes an `entity_type='lead'` audit activity `type='reassign'`. Bumps `last_activity_at` via the existing hook.
- `POST /leads/bulk-reassign` — body `{"ids": [...], "assigned_to_id": <uuid> | null}`. Max 200 ids. Per-id loop reuses single-reassign for audit consistency.
- `POST /leads/bulk-update-status` — body `{"ids": [...], "status": "<new_status>", "lost_reason"?, "lost_reason_other"?}`. State-machine + lost-reason validators apply per row; rows that can't transition return per-id error in response. Requires `leads.write`.
- `POST /leads/bulk-delete` — same shape as contacts; requires `leads.write`.

## `lead-reassign-popover.component`

A small standalone popover (positioned by parent) wrapping the shared `ReassignModal`'s user-picker — but rendered inline as a popover rather than as a centred dialog. Same `confirm`/`cancel` outputs.

Inputs: `leadId`, `currentOwnerId`, `anchorEl`.

The popover differs from `ReassignModal` only in **trigger position** — for card-on-board contexts, a centred modal feels too heavy. List-view single reassign continues to use `ReassignModal`.

(Design note: this is the *only* duplicate to ReassignModal we introduce. Justification: a card-anchored popover has different positioning needs than a viewport-centred dialog. Both delegate to the shared `UsersDirectoryService`.)

## `lead-card.component.html`

Add to the card footer:
- Owner mini-avatar (initials) + name. "Unassigned" if null.
- Last-activity badge: `{{ lastActivityAt | relativeTime }}`, muted text.
- Pencil button (lucide `pencil`) — visible only if `*hasPermission="'leads.reassign'"`. `(click)="reassignClick.emit($event)"`.

## `leads.page.html` — selection state on list view

Same checkbox pattern as `update-contacts-page/` Step 3:
- Row + header checkbox columns.
- Mount `<app-bulk-action-bar [selectedCount]="selectedIds().size" [actions]="bulkActions()">`.
- `bulkActions()` computed: Reassign / Update status / Delete (each behind its permission key).
- Mount `<app-reassign-modal>` (shared) + a small `<app-bulk-status-modal>` (inline, ~30 lines) + `<app-confirm-dialog>`.

`<app-bulk-status-modal>` lets admin pick a target status; if "Lost," prompts for reason (same picklist as create modal).

## `pipeline-board.component.html` — wire popover

When a lead card emits `(reassignClick)`, the board component opens the popover anchored to the card. Same component used for all three pipelines (sales / design / production) that the board renders.

## Permission posture

| Action | Required key |
|---|---|
| Single reassign (card / list) | `leads.reassign` |
| Bulk reassign (list) | `leads.reassign` |
| Bulk update status (list) | `leads.write` |
| Bulk delete (list) | `leads.write` |

## Test `test_reassign_and_bulk.py`

1. `POST /leads/{id}/reassign` writes new owner + audit activity.
2. `POST /leads/bulk-reassign` updates N rows + N audit activities.
3. Bulk status update with invalid transition per row → returns partial-success response shape.
4. Caller without `leads.reassign` → 403.
5. Cross-tenant target uuid → 422.

## Acceptance

1. Admin on pipeline board: cards show owner avatar + last-activity badge.
2. Admin clicks pencil on a card → popover opens → picks user → card refreshes with new owner; audit activity logged.
3. Junior sales rep: cards show owner + last-activity (read-only); no pencil.
4. Admin on list view: row checkboxes → bulk-reassign / bulk-update-status / bulk-delete work.
5. Bulk status to "Lost" prompts for reason; missing reason rejected.
6. Cross-tenant uuid attempt → graceful error in modal.

## Lucide icons used

`pencil`, `user-cog`, `circle-check`, `trash-2`. Verify all registered.

## Self-check vs the 10 rules

- ✅ Rule 1 — leads/* never touches packs.
- ✅ Rule 6 — uses `leads.reassign` registered in Step 1.
- ✅ Rule 8 — 13 files (4 backend, 2 new FE, 7 modified FE). At limit; if drift, split popover into its own micro-step.
- ✅ Rule 10 — no half-finished states; bulk-status validates per row.

## Stop-and-report template

> ✅ Step 3 complete.
> **Files changed:** 13.
> **What you can verify:**
> 1. Pipeline cards show owner avatar + last-activity badge.
> 2. Single reassign popover works on cards (admin only).
> 3. Bulk reassign / bulk status / bulk delete on list view.
> 4. Audit activity logged for every reassign + status change.
> 5. Permission gates enforced (junior sees no reassign / bulk).
> **Tests added:** `test_reassign_and_bulk.py` (5).
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 4 (convert + row ergonomics).
