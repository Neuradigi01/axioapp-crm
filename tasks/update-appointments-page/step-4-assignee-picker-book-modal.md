# Step 4 — Frontend: Assignee picker in Book Appointment modal (users-list API wire-up)

**Goal:** Replace the hardcoded `assigned_to_id: user.id` in the Book Appointment modal with a real Assignee dropdown listing every active user in the org. Owner (or anyone with `appointments.write`) can pick the staff member the appointment is for. Default selection = current user (preserves today's behaviour for solo users).

**Depends on:** Step 1 (`assigned_to_id` already required and validated on the backend). No backend changes — `GET /api/v1/users` already exists and returns the active org members.

## Why this step exists

The Book modal has a stale comment from a half-finished feature:

```ts
// `assigned_to_id` defaults to the current user; there's
// no users-list API yet so we keep it implicit.
```

The users-list API was added later (`GET /api/v1/users` returns `UserOut[]` filtered by current org). This step finally connects the two. Without it, an Owner cannot delegate appointments to staff — they have to book under their own name and then reassign, which is broken UX for a multi-user team.

## Files changed

### New
- (none)

### Modified
- `APP/src/app/features/user/core/appointments/book-appointment-modal.component.ts`
- `APP/src/app/features/user/core/appointments/book-appointment-modal.component.html`

### Tests
- Browser smoke (manual) — no unit test (per the Step 3/4 convention used in `onboarding-setup/`).

## `book-appointment-modal.component.ts`

Add a users signal sourced from the existing API. Default the form's `assigneeId` to the current user's id:

```ts
import { firstValueFrom } from 'rxjs';
// existing imports...

readonly users = signal<UserOut[]>([]);
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

async ngOnInit(): Promise<void> {
  // existing me() fetch...
  try {
    const list = await firstValueFrom(this.usersApi.list({ limit: 200 }));
    this.users.set(list);
    // Default selection = current user; preserves today's behaviour
    // for the solo-user case. Owner/Admin override by picking another.
    const me = this.me();
    if (me) this.assigneeControl.setValue(me.id);
  } catch {
    // /users failure shouldn't block booking; fall back to current
    // user and surface a soft warning in the modal.
    this.users.set([]);
    const me = this.me();
    if (me) this.assigneeControl.setValue(me.id);
  }
}
```

Replace the submit payload's hardcoded `assigned_to_id`:

```ts
const payload = {
  contact_id: contact.id,
  title: this.titleControl.value.trim(),
  // ... existing fields ...
  assigned_to_id: this.assigneeControl.value || user.id,  // ← signal-backed
};
```

Replace the stale doc comment block at the top of the class:

```ts
/**
 * `assigned_to_id` is selected from the Assignee dropdown
 * (`GET /api/v1/users` lists active org members). Defaults to the
 * current user so solo users see no extra friction.
 */
```

## `book-appointment-modal.component.html`

Replace the "Assigned to: you" footer paragraph with a real picker. Place it before the When/Duration row so the assignee is decided up front:

```html
<!-- Assignee picker -->
<div class="mt-4">
  <label
    for="assignee"
    class="block text-xs font-medium text-zinc-600 mb-1"
  >
    Assigned to
  </label>
  <select
    id="assignee"
    [formControl]="assigneeControl"
    class="block w-full rounded-md border border-zinc-300 px-3 py-2 text-sm
           text-zinc-900 focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
  >
    @for (u of users(); track u.id) {
      <option [value]="u.id">{{ u.full_name }}@if (u.id === me()?.id) { (you) }</option>
    }
  </select>
  <p class="mt-1 text-[11px] text-zinc-500">
    The assignee receives the in-app notification when the appointment lands.
  </p>
</div>
```

Remove (or rewrite) the existing footer line `Assigned to: <span>{{ me()?.full_name ?? 'you' }}</span>` — the explicit picker above replaces it.

## Permission gate

No new permission key. The backend already checks `appointments.write` on the create endpoint. The picker is shown to every user who can open the modal; default to current user means a Sales Exec without `appointments.reassign` can still book "for themselves" without extra friction.

## Tests

Browser smoke (manual — primary):

1. Owner opens `/user/appointments` → click **Book Appointment**.
2. Confirm **Assignee dropdown** renders with every active org user.
3. Confirm Owner's name is **default-selected**.
4. Pick another user (e.g. "Priya") → click Book.
5. After save, confirm the new appointment's Owner column shows **Priya**, not Owner.
6. **Solo-user case:** an org with one active user sees only themselves in the dropdown; default still works.

## Acceptance

- Book Appointment modal renders an Assignee dropdown with full org user list.
- Default selection = current user.
- Submit payload carries the picked user's UUID as `assigned_to_id`.
- New appointment lands with the correct Owner.

## Self-check vs the 10 rules

- ✅ Rule 5 — no new module/sidebar entries.
- ✅ Rule 6 — uses existing `appointments.write` permission; no new keys.
- ✅ Rule 8 — 2 files; well under limit.
- ✅ Rule 10 — replaces a documented half-finished feature; no TODOs left.

## Stop-and-report template

> ✅ Step 4 complete.
> **Files changed:** 2.
> **What you can verify:**
> 1. Book Appointment modal shows an Assignee dropdown.
> 2. Selecting another user → new appointment is assigned to them.
> 3. Default selection = current user (solo users unaffected).
> **Tests added:** browser smoke only.
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 5.
