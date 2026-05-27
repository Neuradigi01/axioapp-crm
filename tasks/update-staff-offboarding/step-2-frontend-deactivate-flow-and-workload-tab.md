# Step 2 — Frontend: deactivate flow modal + Workload tab in Settings → Staff

**Goal:** wire the offboarding UX. The Deactivate button on a user becomes a two-step flow (count → transfer target → deactivate). Add a Workload tab in Settings → Staff showing per-user open-record counts.

**Depends on:** Step 1 backend.

## Files changed

### New
- `APP/src/app/features/user/core/settings/staff/staff-deactivate-modal.component.ts`
- `APP/src/app/features/user/core/settings/staff/staff-deactivate-modal.component.html`
- `APP/src/app/features/user/core/settings/staff/staff-workload.component.ts`
- `APP/src/app/features/user/core/settings/staff/staff-workload.component.html`

### Modified
- `APP/src/app/features/user/core/settings/staff/staff.page.ts` — tab state, deactivate handler.
- `APP/src/app/features/user/core/settings/staff/staff.page.html` — Tab navigation (Users / Workload), Deactivate button wired to modal.
- `APP/src/app/features/user/core/settings/staff/staff-api.service.ts` — `getOpenRecordsCounts(userId)`, `transferRecords(userId, payload)`, `getWorkload()`.

## `staff-api.service.ts`

```typescript
getOpenRecordsCounts(userId: string): Observable<OpenRecordsCounts> { ... }

transferRecords(
  userId: string,
  payload: { to_user_id: string; entities: string[]; reason: string | null }
): Observable<TransferRecordsResponse> { ... }

getWorkload(): Observable<{ users: WorkloadUser[]; as_of: string }> { ... }
```

## `staff-deactivate-modal.component`

Inputs: `user` (target — the user being deactivated), `usersInOrg` (cached list).

Lifecycle:
1. On open → fetch `getOpenRecordsCounts(user.id)`.
2. Show the counts table with per-entity numbers.
3. **If `total === 0`** → show "User has no open records. Deactivate?" with a single Confirm button.
4. **If `total > 0`** → show transfer-target picker (typeahead over `usersInOrg`, filtered to `is_active=true` and `id !== user.id`). Required to proceed. Show "Skip transfer" button **disabled** with tooltip "User has open records; choose a transfer target before deactivation."
5. Optional reason textarea ("Why are you offboarding?").
6. **Confirm** button → calls `transferRecords(user.id, ...)` then `deactivateUser(user.id)` sequentially. Both succeed → modal closes; staff list reloads.
7. Mid-failure: show inline error; nothing else changes.

Body layout:
```
+----------------------------------+
| Deactivate Anita Sharma          |
+----------------------------------+
| Open records:                    |
|   Contacts ............ 12       |
|   Leads ............... 5        |
|   Walk-ins ............ 3        |
|   Appointments ........ 4        |
|   Tasks ............... 7        |
|   Total ............... 31       |
+----------------------------------+
| Transfer to: [ Rahul Verma ▾ ]   |
| Reason: [ ____________________ ] |
+----------------------------------+
|     [Cancel]   [Transfer & Deactivate] |
+----------------------------------+
```

## `staff-workload.component`

Inputs: none — fetches `getWorkload()` on init.

Table columns: User · Contacts · Leads · Walk-ins · Appointments · Tasks · Total.

Sortable by any numeric column. Highlight the user with the largest workload in zinc bg (light visual cue, not aggressive).

Refresh button reloads.

## `staff.page.html` — tabs

Add a tab nav (matches the pattern in `contact-detail.page.html`):
- **Users** (existing list) — default.
- **Workload** — new component.

Only Owner / Admin / Store Manager (i.e. users with `users.read`) see the Workload tab. Hide for everyone else.

## `staff.page.ts`

Selecting Deactivate on a row opens `staff-deactivate-modal` bound to the target user. Modal close → reload staff list.

Reuses existing permission guards on the Settings page itself; this step does not add new permission keys.

## Acceptance

1. Admin clicks Deactivate on Anita → modal opens, fetches counts, shows them.
2. With open records > 0, "Skip transfer" disabled; transfer target required.
3. Transfer + deactivate happens atomically (one click, one wait, both succeed or both don't).
4. Anita's records each show new audit activity in their respective timelines.
5. Anita's `is_active=false` after.
6. New Workload tab shows per-user counts; sortable; refresh button works.
7. Junior staff / non-Admin doesn't see Deactivate or Workload tab.
8. Owner row's Deactivate button is disabled / hidden (per existing `rbac-ownership/`).

## Lucide icons used

`user-x` (deactivate), `users` (workload tab), `refresh-cw`. Verify all registered in `app.config.ts`.

## Self-check vs the 10 rules

- ✅ Rule 1 — feature lives in `core/settings/staff/`; no pack imports.
- ✅ Rule 8 — 7 files (4 new + 3 modified). Under limit.
- ✅ Rule 10 — modal handles all edge cases (zero records, transfer rejection, target deactivated, cross-tenant — server returns clear errors that the modal surfaces).

## Stop-and-report template

> ✅ Step 2 complete. Staff-offboarding track done.
> **Files changed:** 7.
> **What you can verify:**
> 1. Deactivate flow modal shows counts and requires transfer when total > 0.
> 2. Transfer + deactivate is atomic.
> 3. Records' timelines show the audit activity after.
> 4. Workload tab renders per-user counts.
> 5. Junior staff sees neither Deactivate (already gated) nor Workload tab.
> 6. Owner can't be deactivated through this flow.
> **Tests added:** none (FE smoke; backend covered in Step 1).
> **Self-check:** all 10 rules ✅.
> **Staff-offboarding track complete.** All six upgrade tracks now have full step files.
