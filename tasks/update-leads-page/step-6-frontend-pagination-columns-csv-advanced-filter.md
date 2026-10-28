# Step 6 — Frontend: pagination + column customization + CSV export button + advanced filter builder

**Goal:** consume the new paged endpoint, ship a polished pagination footer, let users show/hide/reorder columns (persisted to localStorage per-user), wire a "Export CSV" button that hits the new endpoint with the current filter, and ship an advanced filter modal that builds the filter DSL the backend already understands. Saved views land in Step 7.

**Depends on:** Step 5 backend.

## Files changed

### New
- `APP/src/app/features/user/core/leads/column-customization-menu.component.ts` *(inline template, ~120 LOC)*
- `APP/src/app/features/user/core/leads/advanced-filter-modal.component.ts`
- `APP/src/app/features/user/core/leads/advanced-filter-modal.component.html`
- `APP/src/app/features/user/core/shared/column-prefs.service.ts` *(localStorage wrapper, reusable across list pages)*
- `APP/src/app/features/user/core/shared/filter-dsl.types.ts` *(TS types mirroring backend DSL)*

### Modified
- `APP/src/app/features/user/core/leads/leads-api.service.ts` — page params, CSV export trigger, filter DSL types, paged response shape.
- `APP/src/app/features/user/core/leads/leads.page.ts` — pagination + column-visibility + advanced-filter state.
- `APP/src/app/features/user/core/leads/leads.page.html` — pagination footer, CSV button, column menu mount, advanced-filter modal mount, score column.

## `filter-dsl.types.ts`

```typescript
export type FilterField =
  | 'status' | 'source' | 'assigned_to_id' | 'lead_score'
  | 'budget' | 'last_activity_at' | 'created_at'
  | 'contact_name' | 'contact_phone' | 'contact_email'
  | 'linked_deal_id'
  | `custom_data.${string}`;

export type FilterOp =
  | 'eq' | 'neq' | 'in' | 'nin'
  | 'gt' | 'gte' | 'lt' | 'lte'
  | 'contains' | 'starts_with'
  | 'between' | 'is_empty' | 'is_not_empty';

export interface FilterClause {
  field: FilterField;
  op: FilterOp;
  value?: unknown;   // omitted for is_empty / is_not_empty
}

export interface FilterDsl {
  all?: FilterClause[];
  any?: FilterClause[];
}
```

The same shape is consumed by `leads-api.service.ts` and emitted by `advanced-filter-modal.component`. Future list pages (contacts v2, walk-ins) reuse these types.

## `column-prefs.service.ts`

A thin Angular `@Injectable({ providedIn: 'root' })` wrapper over `localStorage`:

```typescript
@Injectable({ providedIn: 'root' })
export class ColumnPrefsService {
  private readonly KEY = (page: string) => `crm.columns.${page}`;

  get(page: string, defaults: ColumnDef[]): ColumnDef[] { ... }
  set(page: string, cols: ColumnDef[]): void { ... }
  reset(page: string): void { ... }
}

export interface ColumnDef {
  key: string;       // matches LeadListItem field name
  label: string;     // header label
  visible: boolean;
  // No `order` field — array order IS the order.
}
```

LocalStorage is deliberate (not backend persistence yet) — keeps Step 6 lean. Step 7 migrates this to a `user_preferences` table when saved views need backend persistence anyway.

## `leads-api.service.ts`

- Replace `list(query)`'s return type from `LeadListItem[]` to `LeadListResponse`:
  ```typescript
  export interface LeadListResponse {
    items: LeadListItem[];
    next_cursor: string | null;
    total: number | null;
  }
  ```
- Extend `LeadListItem` with `lead_score: number`.
- Extend `LeadListQuery` with `cursor`, `limit`, `with_total`, `filter` (the DSL object — service stringifies it as a JSON-encoded query param).
- New: `exportCsv(query: LeadListQuery): void` — builds the same URL with `/export.csv` and triggers a download via a hidden `<a>` tag. Uses the auth interceptor's token; no manual header injection.

## `column-customization-menu.component.ts`

Standalone component, inline template (~120 LOC total). Inputs: `columns: ColumnDef[]`, `pageKey: string`. Outputs: `(columnsChange)` emits the updated array.

UI:
- Trigger: a `lucide:columns-3` icon button in the toolbar with tooltip "Customize columns."
- Popover panel: a scrollable list of columns; each row has a checkbox + drag handle (lucide `grip-vertical`).
- Drag-to-reorder uses Angular CDK's `cdkDropList` (already in the project via the pipeline kanban).
- "Reset to default" link at the bottom calls `columnPrefs.reset(pageKey)` and re-emits.

Reads/writes through `ColumnPrefsService`; the parent (leads page) holds the canonical signal and re-renders on emit.

## `advanced-filter-modal.component`

A centred dialog. Inputs: `initial: FilterDsl`, `customFields: CustomFieldDefinition[]`. Outputs: `(apply)` emits `FilterDsl`, `(cancel)`.

UI:
- Header: "Advanced filter — Leads."
- Body: a stack of clause rows under a single "Match ALL of the following" label (v1 = AND only; OR group deferred — backend supports it but UI complexity isn't worth the second step).
- Each clause row:
  - Field picker (grouped: Standard fields / Custom fields).
  - Op picker — narrowed by field type (string fields hide `gt/lt`; numeric hide `contains`; etc.).
  - Value input — typed by field+op (date-range picker for `between` on dates; tag-input for `in/nin`; checkbox-only "is set / is not set" rows).
  - Trash icon to remove the row.
- "+ Add filter" button below the list.
- Footer: Cancel · Reset · Apply.

Field metadata (which fields, which types, allowed ops per type) is a constant in the component — small enough to inline.

On Apply, emits a `FilterDsl` with the `all` array populated. Empty rows are dropped. If no clauses remain, emits `{}`.

## `leads.page.ts` — state additions

```typescript
readonly pageSize = signal(50);
readonly cursor = signal<string | null>(null);
readonly nextCursor = signal<string | null>(null);
readonly cursorHistory = signal<(string | null)[]>([]);   // back-stack for "Previous" button
readonly totalCount = signal<number | null>(null);

readonly columns = signal<ColumnDef[]>(this.columnPrefs.get('leads', DEFAULT_LEAD_COLUMNS));
readonly advancedFilter = signal<FilterDsl>({});
readonly advancedFilterOpen = signal(false);

readonly DEFAULT_LEAD_COLUMNS: ColumnDef[] = [
  { key: 'contact_name', label: 'Contact', visible: true },
  { key: 'status',       label: 'Status',  visible: true },
  { key: 'owner',        label: 'Owner',   visible: true },
  { key: 'source',       label: 'Source',  visible: true },
  { key: 'lead_score',   label: 'Score',   visible: true },
  { key: 'budget',       label: 'Budget',  visible: false },
  { key: 'last_activity_at', label: 'Last activity', visible: true },
  { key: 'created_at',   label: 'Created', visible: true },
  { key: 'phone',        label: 'Phone',   visible: false },
  { key: 'email',        label: 'Email',   visible: false },
];
```

Handlers:
- `onColumnsChange(cols)` → `columns.set(cols)`; `columnPrefs.set('leads', cols)`.
- `onAdvancedFilterApply(dsl)` → `advancedFilter.set(dsl)`; reset `cursor` to null; refetch.
- `onNextPage()` → push current cursor onto history, set `cursor.set(nextCursor())`, refetch.
- `onPrevPage()` → pop from history, set as cursor, refetch.
- `onExportCsv()` → calls `api.exportCsv({ ...currentQueryWithoutPaging })`.

`currentQuery()` computed signal merges convenience filters + `advancedFilter()` into the DSL the API expects.

## `leads.page.html` — additions

**Toolbar additions** (right of existing filters):
- Advanced filter button (lucide `sliders-horizontal`) with a badge showing active-clause count.
- Columns customization menu trigger.
- Export CSV button (lucide `download`) — disabled if no `leads.export` permission.

**List view table:**
- Render header + cells dynamically from `columns()`, only `visible` ones, in array order.
- Score column: small rounded pill, color band:
  - `0–29` zinc (cold), `30–59` amber (warm), `60–89` orange (hot), `90+` red (on fire).

**Pagination footer** (below the table, inline — no separate component this step):
- Left side: "Showing X–Y of N" (when `total` known) or "Showing X" (cursor-only mode).
- Right side: Page-size dropdown (25 / 50 / 100 / 200), Previous · Next buttons.
- Previous disabled when `cursorHistory().length === 0`; Next disabled when `nextCursor() === null`.

**Pipeline view:** unchanged — pagination is list-view-only. Pipeline cards continue to load via the existing per-stage fetch.

## Acceptance

1. List view loads 50 leads, shows a "Showing 1–50 of N" footer (the existing FE passes `with_total=true` on first page).
2. Next / Previous buttons walk the cursor; refresh on page 3 keeps cursor state (URL state in Step 4 already round-trips `page` indirectly — re-verify nothing regressed).
3. Page-size 200 fetches 200 in one round trip.
4. Columns menu hides Budget by default; toggling visible adds it; drag-reorder persists across reloads (localStorage check).
5. Score column shows colour-banded pill; sortable header (chevron toggles `sort=lead_score&order=…`).
6. Advanced filter modal: add `status = qualified AND budget >= 50000` → applies, list narrows, modal badge shows "2."
7. Custom-field filter row: pick a `custom_data.preferred_wood`, op `eq`, value `Teak` → backend accepts, list narrows.
8. Export CSV: click button → browser downloads `leads-<org>-<utc-date>.csv` with only the visible columns AND the active filter applied.
9. Junior sales (no `leads.export`) — Export button hidden.
10. Pipeline view unaffected; switching from list to pipeline does not break the cursor on switching back (cursor state preserved in the page signal).

## Lucide icons used

`columns-3`, `grip-vertical`, `sliders-horizontal`, `download`, `chevron-left`, `chevron-right`. Verify all registered in `app.config.ts` per the icon-registry feedback.

## Self-check vs the 10 rules

- ✅ Rule 1 — no pack imports.
- ✅ Rule 4 — score column reads from a server-supplied field; no client-side score logic. Custom-field clauses in the filter modal still resolve from the `GET /custom_field_definitions` endpoint, not hardcoded.
- ✅ Rule 5 — sidebar untouched.
- ✅ Rule 8 — 8 files (3 modified, 5 new). Well under 10.
- ✅ Rule 9 — stop-and-report after this step.
- ✅ Rule 10 — no TODOs; advanced filter ships with field-type-aware ops; CSV button gracefully handles permission denial.

## Stop-and-report template

> ✅ Step 6 complete.
> **Files changed:** 8 (3 modified leads + 5 new shared/leads components & services).
> **What you can verify (smoke on Ajay's Workspace):**
> 1. `/user/leads` shows pagination footer + page-size selector.
> 2. Columns menu hides/reorders columns; reload preserves layout.
> 3. Score column renders the colour-banded pill; sorting by score works.
> 4. Advanced filter modal builds a `status = qualified AND budget >= 50000` filter; list narrows.
> 5. Export CSV downloads a file that matches the visible filter and column choice.
> 6. Pipeline view still works; switching back to list restores cursor.
> **Tests added:** none (FE smoke). Backend tests from Step 5 cover the data contract.
> **Self-check:** all 10 rules ✅.
> Awaiting **"proceed"** before Step 7 (saved views + lead scoring rules settings page).
