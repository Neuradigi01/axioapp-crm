# Step 2 — Frontend: Owner + Last Activity columns, sortable headers, assignee filter

**Goal:** surface the new backend fields on the contacts list and detail. Add sortable column headers, an assignee dropdown filter with "Me" preset, and read-only Owner display on the detail page.

**Depends on:** Step 1 backend.

## Files changed

### New
- `APP/src/app/features/user/core/shared/relative-time.pipe.ts`
- `APP/src/app/features/user/core/shared/users-directory.service.ts`

### Modified
- `APP/src/app/features/user/core/contacts/contacts-api.service.ts`
- `APP/src/app/features/user/core/contacts/contacts-list.page.ts`
- `APP/src/app/features/user/core/contacts/contacts-list.page.html`
- `APP/src/app/features/user/core/contacts/contact-detail.page.html`
- `APP/src/app/features/user/core/contacts/contact-form-modal.component.ts`
- `APP/src/app/features/user/core/contacts/contact-form-modal.component.html`

## `contacts-api.service.ts`

- Extend `ContactListItem`, `Contact`, `ContactCreate`, `ContactUpdate` with `assigned_to_id`, `assigned_to_name`, `last_activity_at`. (`last_activity_at` is read-only — exclude from create/update.)
- Extend `ContactListQuery` with `sort?: 'full_name' | 'created_at' | 'last_activity_at'`, `order?: 'asc' | 'desc'`, `assigned_to_id?: string | null`.
- Pass new params through in `list(...)`. `assigned_to_id` can be the literal string `"unassigned"` to mean "owner is null" — backend Step 1 handles that special-case.

## `shared/users-directory.service.ts`

A tiny `providedIn: 'root'` service that caches the result of `GET /users` for the session.

```typescript
@Injectable({ providedIn: 'root' })
export class UsersDirectoryService {
  private readonly http = inject(HttpClient);
  private cache$: Observable<UserMini[]> | null = null;

  list(): Observable<UserMini[]> {
    if (!this.cache$) {
      this.cache$ = this.http
        .get<UserMini[]>(`${environment.apiBaseUrl}/users`)
        .pipe(shareReplay({ bufferSize: 1, refCount: false }));
    }
    return this.cache$;
  }
}
```
`UserMini = { id, first_name, last_name, email }`. Shared by every page that needs an owner dropdown.

## `shared/relative-time.pipe.ts`

Pure pipe. `transform(value: string | Date | null): string`:
- `null` / `undefined` → `'—'`
- `< 60s` → `'just now'`
- `< 60m` → `'<N>m ago'`
- `< 24h` → `'<N>h ago'`
- `< 7d` → `'<N>d ago'`
- otherwise → `'<N> Mon'` (e.g. `'24 Apr'`)
- `> 1y` → `'<dd> <Mon> <YYYY>'`

No external dep — write it in ~30 lines.

## `contacts-list.page.ts`

Signals to add:
```typescript
readonly sortKey = signal<'full_name' | 'created_at' | 'last_activity_at'>('created_at');
readonly sortOrder = signal<'asc' | 'desc'>('desc');
readonly assigneeControl = new FormControl<string>('', { nonNullable: true });
readonly users = toSignal(this.usersDir.list(), { initialValue: [] });
```

Wire `assigneeControl.valueChanges` → reset page → reload (same pattern as the existing controls). `'me'` resolves to the current user id via the existing `AuthService` (`currentUser()`).

Add `toggleSort(key)` method: same key → flip order; new key → set the key and default to ascending for `full_name`, descending otherwise.

Pass new params into `api.list({ sort, order, assigned_to_id })`.

## `contacts-list.page.html`

**Filter row** — add a fourth control on the grid (drop to `sm:grid-cols-5` to fit):
```html
<select [formControl]="assigneeControl">
  <option value="">All owners</option>
  <option value="me">Me</option>
  <option value="unassigned">Unassigned</option>
  @for (u of users(); track u.id) {
    <option [value]="u.id">{{ u.first_name }} {{ u.last_name }}</option>
  }
</select>
```

**Header row** — wrap Name / Created / Last activity headers in a `<button>` so they're keyboard-activatable. Each shows a chevron icon (up / down) when active:
```html
<th>
  <button type="button" (click)="toggleSort('full_name')">
    Name
    @if (sortKey() === 'full_name') {
      <lucide-icon [name]="sortOrder() === 'asc' ? 'chevron-up' : 'chevron-down'" />
    }
  </button>
</th>
```

**New columns:**
- Owner — avatar (initials of `assigned_to_name`, or grey if null) + name (or "Unassigned" label, muted).
- Last activity — `{{ item.last_activity_at | relativeTime }}`. Right-aligned, monospace digits.

Drop the Tags column behind the new ones? Hold for now — keep all five existing + two new = 7 columns; the table is wide but acceptable at `max-w-7xl`. Tighter visual pass is a v2 polish.

## `contact-detail.page.html`

In the header dl, add two rows:
```html
<div class="flex items-center gap-1">
  <dt>Owner</dt>
  <dd>
    @if (c.assigned_to_name) {
      <span class="inline-flex items-center gap-1.5">
        <span class="avatar">{{ initials(c.assigned_to_name) }}</span>
        {{ c.assigned_to_name }}
      </span>
    } @else {
      <span class="text-zinc-400">Unassigned</span>
    }
  </dd>
</div>
<div class="flex items-center gap-1">
  <dt>Last activity</dt>
  <dd>{{ c.last_activity_at | relativeTime }}</dd>
</div>
```

The reassign pencil icon next to Owner is **NOT** added in this step — it lands in Step 3 along with the modal.

## `contact-form-modal.component.ts/html`

Add an "Owner" select to the form group:
```typescript
assigned_to_id: this.fb.control<string | null>(null),
```

In the HTML, a single `<select>` populated from `usersDir.list()`. Default on **create** = current user; on **edit** = existing value. Optional — empty value clears.

## Acceptance

1. List shows two new columns. `last_activity_at` populated for any contact that has activities (from Step 1 backfill).
2. Click Name header → list re-sorts by `full_name` asc. Click again → desc. Default sort still `created_at desc`.
3. Click Last activity header → list re-sorts by `last_activity_at desc`, nulls at bottom.
4. Assignee dropdown shows "All / Me / Unassigned / <users>". Picking "Me" filters to caller. Picking a name filters to that user. Picking "Unassigned" shows null-owner rows.
5. Detail page shows Owner + Last activity in the header dl.
6. Create modal lets you set Owner; defaults to caller. Edit modal pre-fills the existing owner.
7. Smoke test on Ajay's Workspace (`41f9ede9-…`) per `feedback_smoke_test_target_org.md`.

## Lucide icons used

`chevron-up`, `chevron-down` — confirm both are registered in `app.config.ts` per `feedback_lucide_icon_registry.md`. Add to the registry if missing.

## Self-check vs the 10 rules

- ✅ Rule 4 — first-class fields (Owner, Last activity) render directly in the static dl, *not* through the dynamic-form path. Custom fields still come from `GET /custom-fields/contact/render`.
- ✅ Rule 5 — sidebar registry untouched.
- ✅ Rule 8 — 8 files (2 new shared + 6 modified). Under limit.

## Stop-and-report template

> ✅ Step 2 complete.
> **Files changed:** 8 (2 new shared, 4 modified contacts FE, 2 modified form-modal).
> **What you can verify:**
> 1. `npm run start` → `/user/contacts` shows Owner + Last activity columns.
> 2. Headers sort on click; chevron flips.
> 3. Assignee dropdown filters; "Me" preset works.
> 4. Detail page header shows Owner + Last activity.
> 5. Create modal lets you set Owner; defaults to current user.
> **Tests added:** none (Step 1 backend already covers the surface; FE is smoke-tested in browser).
> **Self-check:** all 10 rules ✅.
> Awaiting your **"proceed"** before Step 3 (reassign UI).
