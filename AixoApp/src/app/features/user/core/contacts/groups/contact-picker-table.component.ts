/**
 * Paginated contact picker used by the group create/edit page.
 *
 * The first page of contacts is fetched on mount — no "type to load"
 * gate. Header search + per-column filter popovers (funnel icons on
 * Name / Source / Tag) each re-query the backend and reset to page 1.
 *
 * Row checkboxes + a header checkbox on the current page (Gmail-style —
 * selection is per-visible-page, not cross-page). Selection persists
 * as the operator paginates so they can compose a group from rows on
 * several pages. The parent binds `selectedIds` two-way; on edit,
 * pre-existing member ids are seeded in and the checkboxes render
 * checked automatically.
 */
import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  model,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { ContactListItem, ContactsApiService } from '../contacts-api.service';
import { extractApiError } from '@core/services/api-error.util';

type FilterKey = 'name' | 'source' | 'tag';

const PAGE_SIZE = 20;

@Component({
  selector: 'app-contact-picker-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, ReactiveFormsModule],
  templateUrl: './contact-picker-table.component.html',
})
export class ContactPickerTableComponent {
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** Two-way bound. Parent seeds it with a group's existing member ids
   *  on edit; the picker mutates it as the operator checks / unchecks
   *  rows on any page. */
  readonly selectedIds = model<Set<string>>(new Set());

  // Column filter form controls — each one is bound to a text input
  // inside its own popover. Values persist even when a popover is
  // closed so the operator can layer filters.
  protected readonly nameCtrl = new FormControl<string>('', { nonNullable: true });
  protected readonly sourceCtrl = new FormControl<string>('', { nonNullable: true });
  protected readonly tagCtrl = new FormControl<string>('', { nonNullable: true });

  /** Which column filter popover is currently open, or `null` for none. */
  protected readonly openFilter = signal<FilterKey | null>(null);

  // Table data + paging state.
  protected readonly rows = signal<ContactListItem[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly page = signal(1);
  protected readonly total = signal(0);
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));

  private readonly fetchTrigger$ = new Subject<void>();

  // Header checkbox tri-state derived from the current page contents.
  protected readonly pageSelectionState = computed<'none' | 'some' | 'all'>(() => {
    const ids = this.selectedIds();
    const rows = this.rows();
    if (rows.length === 0) return 'none';
    let hit = 0;
    for (const r of rows) if (ids.has(r.id)) hit++;
    if (hit === 0) return 'none';
    if (hit === rows.length) return 'all';
    return 'some';
  });

  /** Whether any column filter is currently applied — controls the
   *  visibility of the "Clear filters" link. */
  protected readonly hasActiveFilter = computed(() => {
    // Read the form-value signals via the effect below by touching
    // `filterVersion` — form controls don't natively emit as signals.
    this.filterVersion();
    return !!(
      this.nameCtrl.value.trim() ||
      this.sourceCtrl.value.trim() ||
      this.tagCtrl.value.trim()
    );
  });

  // Bumped whenever any filter control emits, so the `hasActiveFilter`
  // computed re-runs. Form control valueChanges aren't signals natively.
  private readonly filterVersion = signal(0);

  /** id → contact, accumulated as rows are loaded onto any page or
   *  fetched by the missing-id hydrate below. Powers the "Selected
   *  contacts" chip strip so operators can see names of contacts
   *  they've picked from earlier pages / from the seeded edit set. */
  protected readonly hydratedById = signal<Map<string, ContactListItem>>(new Map());

  /** Ordered list of contact rows for the selected-chip strip. Rows we
   *  haven't been able to hydrate yet (very brief window while the
   *  fetch is in flight) render with a short-id placeholder so the
   *  count and the chip strip agree. */
  protected readonly selectedChips = computed<ContactListItem[]>(() => {
    const cache = this.hydratedById();
    return Array.from(this.selectedIds(), (id) => {
      const hit = cache.get(id);
      if (hit) return hit;
      return {
        id,
        full_name: 'Contact ' + id.slice(0, 8),
        phone: null,
        email: null,
      } as ContactListItem;
    });
  });

  constructor() {
    // Filter typing is debounced HERE (at the input source) so the
    // fetch stream itself stays snappy — pagination clicks and the
    // initial page load fire immediately.
    for (const ctrl of [this.nameCtrl, this.sourceCtrl, this.tagCtrl]) {
      ctrl.valueChanges
        .pipe(debounceTime(250), takeUntilDestroyed(this.destroyRef))
        .subscribe(() => {
          this.filterVersion.update((n) => n + 1);
          this._onFilterChange();
        });
    }

    this.fetchTrigger$
      .pipe(
        switchMap(() => {
          this.loading.set(true);
          this.loadError.set(null);
          return this.contactsApi
            .list({
              ...this._currentQuery(),
              page: this.page(),
              size: PAGE_SIZE,
              exclude_anonymised: true,
            })
            .pipe(
              catchError((err: HttpErrorResponse) => {
                this.loadError.set(extractApiError(err) ?? 'Could not load contacts.');
                return of({ items: [], total: 0, page: 1, size: PAGE_SIZE });
              }),
            );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((res) => {
        this.rows.set(res.items);
        this.total.set(res.total);
        this.loading.set(false);
        // Add every visible row to the hydration cache so the selected
        // chip strip has real names for anything picked on this page.
        this._addToCache(res.items);
      });

    // Fire the first page load immediately (synchronously in the
    // constructor). No microtask wait, no debounce — the moment the
    // component mounts, the request is on the wire.
    this.fetchTrigger$.next();

    // Hydrate any selected id we don't yet have contact data for. Fires
    // once when the parent seeds an existing group's members on edit,
    // and any time an operator checks a row we haven't cached yet
    // (rare — checking a row means it's on the current page, which is
    // already cached — but this closes the loop.)
    effect(() => this._hydrateMissingSelected());
  }

  // ── UI actions ────────────────────────────────────────────────────

  protected toggleFilter(key: FilterKey): void {
    this.openFilter.set(this.openFilter() === key ? null : key);
  }

  protected closeFilter(): void {
    this.openFilter.set(null);
  }

  protected clearFilter(key: FilterKey): void {
    if (key === 'name') this.nameCtrl.setValue('');
    if (key === 'source') this.sourceCtrl.setValue('');
    if (key === 'tag') this.tagCtrl.setValue('');
    this.openFilter.set(null);
  }

  protected clearAllFilters(): void {
    this.nameCtrl.setValue('', { emitEvent: false });
    this.sourceCtrl.setValue('', { emitEvent: false });
    this.tagCtrl.setValue('');
    // Emitting on the last setValue is enough to trigger one fetch.
  }

  protected onRowToggle(id: string, checked: boolean): void {
    const next = new Set(this.selectedIds());
    if (checked) next.add(id);
    else next.delete(id);
    this.selectedIds.set(next);
  }

  protected onHeaderToggle(): void {
    const state = this.pageSelectionState();
    const next = new Set(this.selectedIds());
    if (state === 'all') {
      for (const r of this.rows()) next.delete(r.id);
    } else {
      for (const r of this.rows()) next.add(r.id);
    }
    this.selectedIds.set(next);
  }

  protected clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  protected goToPage(next: number): void {
    if (next < 1 || next > this.totalPages()) return;
    this.page.set(next);
    this.closeFilter();
    this.fetchTrigger$.next();
  }

  protected isChecked(id: string): boolean {
    return this.selectedIds().has(id);
  }

  // ── internals ─────────────────────────────────────────────────────

  private _onFilterChange(): void {
    this.page.set(1);
    this.fetchTrigger$.next();
  }

  private _addToCache(items: ContactListItem[]): void {
    if (items.length === 0) return;
    this.hydratedById.update((prev) => {
      const next = new Map(prev);
      for (const it of items) next.set(it.id, it);
      return next;
    });
  }

  /** In-flight guard so the hydrate effect doesn't fire twice for the
   *  same set of missing ids (e.g. Angular re-runs the effect after
   *  the cache write below settles the selected chips). */
  private _hydratingIds = new Set<string>();

  private _hydrateMissingSelected(): void {
    const ids = this.selectedIds();
    const cache = this.hydratedById();
    const missing: string[] = [];
    for (const id of ids) {
      if (!cache.has(id) && !this._hydratingIds.has(id)) missing.push(id);
    }
    if (missing.length === 0) return;
    for (const id of missing) this._hydratingIds.add(id);
    this.contactsApi
      .hydrateByIds(missing)
      .pipe(
        catchError(() => of([] as ContactListItem[])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        for (const id of missing) this._hydratingIds.delete(id);
        this._addToCache(rows);
      });
  }

  private _currentQuery(): { q?: string; source?: string; tag?: string } {
    const out: { q?: string; source?: string; tag?: string } = {};
    const q = this.nameCtrl.value.trim();
    const source = this.sourceCtrl.value.trim();
    const tag = this.tagCtrl.value.trim();
    if (q) out.q = q;
    if (source) out.source = source;
    if (tag) out.tag = tag;
    return out;
  }
}
