# Step 3 — Reassign UI (single + bulk) + shared `ReassignModal` + `BulkActionBar`

**Goal:** add the transfer mechanic — single reassign on the detail page, bulk reassign + delete + add-tag from the list. Build the two shared components (`ReassignModal`, `BulkActionBar`) that every other page reuses. Add the `contacts.reassign` permission key, gate the new endpoints, and write an audit activity for every transfer.

**Depends on:** Step 2 frontend.

## Files changed

### New backend
- (none — endpoints added inline to existing files)

### Modified backend
- `API/src/app/core/contacts/router.py` — `POST /contacts/{id}/reassign`, `POST /contacts/bulk-reassign`, `POST /contacts/bulk-delete`, `POST /contacts/bulk-add-tag`.
- `API/src/app/core/contacts/service.py` — `reassign_contact`, `bulk_reassign_contacts`, `bulk_delete_contacts`, `bulk_add_tag`.
- `API/src/app/core/contacts/schemas.py` — `ContactReassign`, `ContactBulkReassign`, `ContactBulkDelete`, `ContactBulkAddTag`.
- `API/src/app/core/contacts/module.py` — register `contacts.reassign` permission key.

### New frontend (shared primitives — re-used by leads, walk-ins, appointments, tasks)
- `APP/src/app/features/user/core/shared/reassign-modal.component.ts`
- `APP/src/app/features/user/core/shared/reassign-modal.component.html`
- `APP/src/app/features/user/core/shared/bulk-action-bar.component.ts`
- `APP/src/app/features/user/core/shared/bulk-action-bar.component.html`
- `APP/src/app/features/user/core/shared/confirm-dialog.component.ts`
- `APP/src/app/features/user/core/shared/confirm-dialog.component.html`

### Modified frontend
- `APP/src/app/features/user/core/contacts/contacts-api.service.ts` — `reassign(id, userId)`, `bulkReassign(ids, userId)`, `bulkDelete(ids)`, `bulkAddTag(ids, tag)`.
- `APP/src/app/features/user/core/contacts/contacts-list.page.ts` — selection state, bulk handlers.
- `APP/src/app/features/user/core/contacts/contacts-list.page.html` — row checkboxes, header checkbox, BulkActionBar mount.
- `APP/src/app/features/user/core/contacts/contact-detail.page.html` — pencil icon next to Owner → opens ReassignModal.
- `APP/src/app/features/user/core/contacts/contact-detail.page.ts` — wire reassign + replace `window.confirm` delete with `ConfirmDialog`.

### Tests
- `API/tests/core/contacts/test_reassign_and_bulk.py` (new).

## Permission key registration

In [contacts/module.py](../../API/src/app/core/contacts/module.py), add `contacts.reassign` to the permission list. Per `project_rbac_requirements.md`:
- **Owner** (fixed) — granted automatically (Owner has all keys).
- **Admin** (template) — granted by default in the admin template.
- **Employee** (template) — NOT granted by default. Editable by Admin.

The backfill needs an Alembic migration? No — the permission registry seeds on app boot per existing patterns. Confirm via the existing seeder pattern in `permissions/role_templates.py` (already open in the IDE).

## Backend endpoints

All four endpoints require **`contacts.reassign`** (or `contacts.write` for bulk delete / bulk add tag — see below). All are tenant-scoped via the `TenantScoped` ORM filter.

### `POST /contacts/{id}/reassign`
Body: `{"assigned_to_id": "<uuid>" | null}`. Validates the target user is in the same `org_id`. Updates the contact. **Writes an activity** on `entity_type='contact'`, `entity_id=<contact id>`, `type='reassign'`, `body={"from": <old>, "to": <new>}`. The existing activity-insert hook then bumps `last_activity_at` automatically.

Returns the updated `ContactOut`.

### `POST /contacts/bulk-reassign`
Body: `{"ids": ["<uuid>", ...], "assigned_to_id": "<uuid>" | null}`. Max 200 ids per call. Loop: per id, call `reassign_contact(...)` so each row gets its own audit activity. Single transaction; atomic.

Returns `{"reassigned": <count>}`.

### `POST /contacts/bulk-delete`
Body: `{"ids": ["<uuid>", ...]}`. Requires `contacts.write` (not `contacts.reassign`). Max 200 ids. Soft-delete? Step 1 didn't add a `deleted_at` column — bulk delete is a **hard** delete to match the existing `DELETE /contacts/{id}` semantic. Document the consequence in the FE confirm dialog.

Returns `{"deleted": <count>}`.

### `POST /contacts/bulk-add-tag`
Body: `{"ids": ["<uuid>", ...], "tag": "<string>"}`. Requires `contacts.write`. Appends the tag to the `tags` array if not already present (Postgres `array_append` + `NOT array_contains`). Trims, lowercases — match whatever the existing create-tag path does.

Returns `{"updated": <count>}`.

## Permission posture summary

| Action | Required key |
|---|---|
| Single reassign (detail page) | `contacts.reassign` |
| Bulk reassign (list page) | `contacts.reassign` |
| Bulk delete | `contacts.write` |
| Bulk add tag | `contacts.write` |

Junior Sales (template) has `contacts.write` but **not** `contacts.reassign`. They can bulk-delete their own contacts (if they have write on those rows — RLS will enforce visibility separately in `update-leads-page` Step 1 scope work).

## `ReassignModal` component (shared)

Inputs: `entityLabel` (`'contact'` | `'lead'` | `'walk-in'` | `'appointment'` | `'task'`), `count` (number — `1` for single, `N` for bulk), `currentOwnerId` (for single; omitted for bulk).

Body:
- Heading: *Reassign 1 contact* or *Reassign 12 contacts* (uses `count`).
- User picker — typeahead dropdown over `UsersDirectoryService.list()`. Selecting `null` = Unassigned (allowed).
- Optional note textarea (kept short — `body.note` saved on the audit activity).
- Cancel / Reassign buttons.

Outputs: `confirm` (emits `{ userId: string | null, note: string | null }`), `cancel`.

No backend calls — parent handles the API call. Modal is purely presentational.

## `BulkActionBar` component (shared)

Inputs: `selectedCount` (number — drives visibility), `actions` (array of `{ key, label, icon, danger?: boolean, permissionKey?: string }`).

Renders as a floating bar at the bottom of the viewport (`fixed bottom-4 left-1/2 -translate-x-1/2`). Hidden when `selectedCount === 0`.

Outputs: `action` (emits the action key), `clear` (clears selection).

Each action button checks `permissionKey` against the current user's permissions via the existing `PermissionsService` — actions the user can't perform are hidden, not disabled, to avoid confusion.

## `ConfirmDialog` component (shared)

Standard styled confirm: title, body (`@Input`), confirm-button label + colour (`danger?`), cancel label. Outputs `confirm` / `cancel`. Replaces `window.confirm` everywhere this track touches.

## `contacts-list.page.ts` — selection state

```typescript
readonly selectedIds = signal<Set<string>>(new Set());
readonly allOnPageSelected = computed(() => {
  const ids = this.items().map(i => i.id);
  const sel = this.selectedIds();
  return ids.length > 0 && ids.every(id => sel.has(id));
});

toggleRow(id: string) { /* add/remove from set */ }
toggleAllOnPage() { /* select all visible or clear */ }
clearSelection() { this.selectedIds.set(new Set()); }

readonly bulkActions = computed<BulkAction[]>(() => [
  { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'contacts.reassign' },
  { key: 'tag', label: 'Add tag', icon: 'tag', permissionKey: 'contacts.write' },
  { key: 'delete', label: 'Delete', icon: 'trash-2', danger: true, permissionKey: 'contacts.write' },
]);
```

`onBulkAction(key)` opens the matching modal. After confirm: call API, clear selection, `reload()`.

## `contacts-list.page.html` — checkbox column

Prepend a checkbox `<th>` and `<td>`. Header checkbox is bound to `allOnPageSelected()`; row checkboxes call `toggleRow(id)`. **Stop propagation** on the checkbox click so it doesn't trigger the row's `(click)="onRowClick(...)"`.

Mount `<app-bulk-action-bar>` at the bottom of the page (sibling to the table). Mount the three modals (reassign, add-tag, confirm-delete) conditionally based on signals.

## `contact-detail.page.html` — single reassign

Next to the Owner field in the dl, add a pencil icon (`<lucide-icon name="pencil">`) — visible only if the current user has `contacts.reassign` (use the existing `*hasPermission` directive). Click opens `<app-reassign-modal [entityLabel]="'contact'" [count]="1" [currentOwnerId]="c.assigned_to_id">`. On confirm → `api.reassign(c.id, userId)` → refresh contact signal.

Also replace the existing `window.confirm` in `onDelete()` with the `ConfirmDialog` component.

## Lucide icons used

`user-cog`, `tag`, `trash-2`, `pencil`, `x` (modal close). Confirm registry in `app.config.ts` per `feedback_lucide_icon_registry.md`.

## Test `test_reassign_and_bulk.py`

Six cases:
1. `POST /contacts/{id}/reassign` writes the new owner.
2. Same call creates an `activity` entry with `type='reassign'`.
3. Same call bumps `last_activity_at` on the contact.
4. `POST /contacts/bulk-reassign` updates all 3 contacts in one call, writes 3 activities.
5. Target user from a different org → 422 (cross-tenant attempt rejected).
6. Caller without `contacts.reassign` → 403.

## Acceptance

1. Admin on the contacts list selects 3 rows → BulkActionBar appears → "Reassign to…" → picks Anita → all 3 reassigned, audit entries created, list reloads.
2. Junior Sales does the same → BulkActionBar shows only "Delete" + "Add tag" (no reassign button visible).
3. Admin opens a contact detail → clicks pencil next to Owner → picks Rahul → reassigned + activity logged. Junior Sales does not see the pencil.
4. Bulk delete shows the `ConfirmDialog` with "Delete 3 contacts? This cannot be undone." Cancelling does nothing.
5. Bulk add-tag prompts for a tag string → applied to all selected.
6. Cross-tenant target uuid returns 422 and shows a graceful error in the modal.
7. Smoke target Ajay's Workspace.

## Self-check vs the 10 rules

- ✅ Rule 1 — shared components live in `core/shared/`, no pack imports.
- ✅ Rule 6 — `contacts.reassign` registered through `contacts/module.py`.
- ✅ Rule 7 — `pack.yaml` untouched. Pack-installer (Step 7 in pack.yaml track) may need to grant `contacts.reassign` to specific furniture roles later; out of scope here.
- ✅ Rule 8 — 13 files (4 modified backend + 6 new shared FE + 5 modified contacts FE). At the soft limit; if drift, split bulk delete + bulk add tag into a Step 3b.
- ✅ Rule 10 — `window.confirm` removed (no half-finished improvements).

## Stop-and-report template

> ✅ Step 3 complete.
> **Files changed:** 14 (4 backend modified, 6 new shared FE components, 4 modified contacts FE, 1 new test).
> **What you can verify:**
> 1. Single reassign from contact detail (admin sees pencil; junior does not).
> 2. Bulk reassign / delete / add tag from list (admin sees all 3; junior sees 2).
> 3. Activity timeline shows the reassign event with from / to.
> 4. Cross-tenant target → 422; missing permission → 403.
> **Tests added:** `tests/core/contacts/test_reassign_and_bulk.py` (6 cases).
> **New permission key:** `contacts.reassign` (granted to Owner + Admin templates by default).
> **Self-check:** all 10 rules ✅.
> Awaiting your **"proceed"** before Step 4 (row ergonomics).
