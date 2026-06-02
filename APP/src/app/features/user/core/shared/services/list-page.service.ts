import { Injectable, computed, signal } from '@angular/core';

/**
 * Component-scoped state holder for a paginated list page.
 *
 * Consolidates the pagination / selection / bulk-modal signal cluster
 * that every list page used to redeclare:
 *
 *   - core list state: `items / total / loading / loadError`
 *   - pagination:      `page / pageSize / totalPages` (computed)
 *   - selection:       `selectedIds / selectedCount / allOnPageSelected`
 *   - bulk modal:      `bulkModal / bulkSubmitting / bulkError`
 *
 * The actual data load is the page's responsibility — its api service
 * knows the request shape, the response envelope, and any filter
 * pre-processing. The page calls `state.loading.set(true)` →
 * `state.items.set(rows)` + `state.total.set(n)` → `state.loading.set(false)`
 * inside its own `load()` method. This service holds the state; it
 * does not own the network.
 *
 * Provided per-component (`providers: [ListPageState]`) so each list
 * page gets its own isolated instance.
 *
 * @example
 *   class ContactsListState extends ListPageState<ContactListItem> {}
 *
 *   @Component({
 *     providers: [ContactsListState],
 *   })
 *   class ContactsListPageComponent {
 *     protected readonly state = inject(ContactsListState);
 *
 *     load() {
 *       this.state.loading.set(true);
 *       this.api.list({...}).subscribe({
 *         next: (res) => {
 *           this.state.items.set(res.items);
 *           this.state.total.set(res.total);
 *           this.state.loading.set(false);
 *         },
 *         error: (err) => {
 *           this.state.loadError.set(err.message);
 *           this.state.loading.set(false);
 *         },
 *       });
 *     }
 *   }
 */
@Injectable()
export class ListPageState<T extends { id: string }> {
  // --- Core list state -----------------------------------------------

  readonly items = signal<T[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly loadError = signal<string | null>(null);

  // --- Pagination ----------------------------------------------------

  readonly page = signal<number>(1);
  readonly pageSize = signal<number>(25);

  readonly totalPages = computed(() => {
    const total = this.total();
    if (total === 0) return 1;
    return Math.max(1, Math.ceil(total / this.pageSize()));
  });

  // --- Selection -----------------------------------------------------

  readonly selectedIds = signal<Set<string>>(new Set());

  readonly selectedCount = computed(() => this.selectedIds().size);

  /** Header-checkbox state: true only when every visible row is selected. */
  readonly allOnPageSelected = computed(() => {
    const items = this.items();
    if (items.length === 0) return false;
    const sel = this.selectedIds();
    return items.every((i) => sel.has(i.id));
  });

  // --- Bulk-modal state ----------------------------------------------

  /** Which bulk modal is open (keyed by string — page defines the set
   * e.g. `'reassign' | 'tag' | 'delete'`). `null` means closed. */
  readonly bulkModal = signal<string | null>(null);
  readonly bulkSubmitting = signal<boolean>(false);
  readonly bulkError = signal<string | null>(null);

  // --- Pagination actions --------------------------------------------

  setPage(p: number): void {
    this.page.set(Math.max(1, Math.floor(p)));
  }

  setPageSize(size: number): void {
    this.pageSize.set(Math.max(1, Math.min(200, Math.floor(size))));
    // New page size invalidates the current page index.
    this.page.set(1);
  }

  // --- Selection actions --------------------------------------------

  toggleSelection(id: string): void {
    this.selectedIds.update((sel) => {
      const next = new Set(sel);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  selectAllOnPage(): void {
    this.selectedIds.set(new Set(this.items().map((i) => i.id)));
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  // --- Bulk-modal actions -------------------------------------------

  openBulkModal(key: string): void {
    this.bulkModal.set(key);
    this.bulkError.set(null);
    this.bulkSubmitting.set(false);
  }

  closeBulkModal(): void {
    this.bulkModal.set(null);
    this.bulkError.set(null);
    this.bulkSubmitting.set(false);
  }
}
