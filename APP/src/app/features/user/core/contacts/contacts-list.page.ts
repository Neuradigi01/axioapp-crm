import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged } from 'rxjs/operators';

import {
  Contact,
  ContactCreate,
  ContactListItem,
  ContactSortKey,
  ContactUpdate,
  ContactsApiService,
  SortOrder,
} from './contacts-api.service';
import { ContactFormModalComponent } from './contact-form-modal.component';
import { OptInChipComponent } from './opt-in/opt-in-chip.component';
import { FurnitureAuthService } from '../auth/auth.service';
import { BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { MailLinkDirective } from '../shared/directives/mail-link.directive';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import {
  ReassignConfirm,
  ReassignModalComponent,
} from '../shared/reassign-modal/reassign-modal.component';
import { ListPageState } from '../shared/services/list-page.service';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

class ContactsListState extends ListPageState<ContactListItem> {}

@Component({
  selector: 'app-contacts-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    RouterLink,
    ContactFormModalComponent,
    RelativeTimePipe,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    MailLinkDirective,
    UrlFilterStateDirective,
    OptInChipComponent,
  ],
  providers: [ContactsListState],
  templateUrl: './contacts-list.page.html',
})
export class ContactsListPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  protected readonly state = inject(ContactsListState);

  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  readonly tagControl = new FormControl('', { nonNullable: true });
  /** Assignee filter. Empty = all, `'me'` resolves to current user, or a user UUID. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** Sort state. Defaults to ``last_activity_at desc`` so contacts the
   *  operator just touched (via a fresh lead / new contact / edit)
   *  surface at the top — matches the standard CRM "recency wins"
   *  expectation. Falls back to ``created_at desc`` as a secondary
   *  ordering on the backend for rows with no activity yet. */
  readonly sortKey = signal<ContactSortKey>('last_activity_at');
  readonly sortOrder = signal<SortOrder>('desc');

  /** Cached list of users for the assignee dropdown. */
  readonly users = toSignal(this.usersDir.list(), { initialValue: [] });

  /** Owner-id → "Full Name" lookup so the list row can show a name
   * without round-tripping to the backend. Tolerates a missing user
   * (deactivated mid-session) by falling back to "Unknown". */
  readonly userMap = computed(() => {
    const map = new Map<string, string>();
    for (const u of this.users()) map.set(u.id, u.full_name);
    return map;
  });

  private readonly q = toSignal(
    this.searchControl.valueChanges.pipe(debounceTime(200), distinctUntilChanged()),
    { initialValue: '' },
  );
  private readonly sourceFilter = toSignal(
    this.sourceControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );
  private readonly tagFilter = toSignal(this.tagControl.valueChanges.pipe(distinctUntilChanged()), {
    initialValue: '',
  });

  /** Distinct source/tag chips for filter dropdowns — derived from the loaded page. */
  readonly sourceOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.state.items()) {
      if (item.source) set.add(item.source);
    }
    return [...set].sort();
  });

  readonly tagOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.state.items()) {
      for (const t of item.tags) set.add(t);
    }
    return [...set].sort();
  });

  // --- Multi-select + bulk actions -------------------------------------------

  readonly tagInputControl = new FormControl<string>('', { nonNullable: true });

  /** CSV export progress (single in-flight at a time). */
  readonly exporting = signal(false);

  /** URL ↔ filter state map. Wires every filter signal / FormControl to a
   * query-param key so refresh / share / browser-back preserve the view.
   * `replaceUrl: true` keeps history clean while typing in the search box. */
  readonly urlState: UrlFilterStateConfig = {
    q: {
      read: () => this.searchControl.value,
      write: (v) => this.searchControl.setValue(v),
      queryKey: 'q',
    },
    source: {
      read: () => this.sourceControl.value,
      write: (v) => this.sourceControl.setValue(v),
      queryKey: 'source',
    },
    tag: {
      read: () => this.tagControl.value,
      write: (v) => this.tagControl.setValue(v),
      queryKey: 'tag',
    },
    assignee: {
      read: () => this.assigneeControl.value,
      write: (v) => this.assigneeControl.setValue(v),
      queryKey: 'assignee',
    },
    sort: {
      read: () => this.sortKey(),
      write: (v) => {
        if (v === 'full_name' || v === 'created_at' || v === 'last_activity_at') {
          this.sortKey.set(v);
        }
      },
      queryKey: 'sort',
      defaultValue: 'last_activity_at',
    },
    order: {
      read: () => this.sortOrder(),
      write: (v) => {
        if (v === 'asc' || v === 'desc') this.sortOrder.set(v);
      },
      queryKey: 'order',
      defaultValue: 'desc',
    },
    page: {
      read: () => String(this.state.page()),
      write: (v) => {
        const n = Number.parseInt(v, 10);
        if (Number.isFinite(n) && n >= 1) this.state.page.set(n);
      },
      queryKey: 'page',
      defaultValue: '1',
    },
    size: {
      read: () => String(this.state.pageSize()),
      write: (v) => {
        const n = Number.parseInt(v, 10);
        if (n === 25 || n === 50 || n === 100) this.state.pageSize.set(n);
      },
      queryKey: 'size',
      defaultValue: '25',
    },
  };

  /** Modal state: null = closed, undefined = create, Contact = edit. */
  readonly modalState = signal<Contact | null | undefined>(null);
  readonly modalOpen = computed(() => this.modalState() !== null);
  readonly editingContact = computed<Contact | null>(() => {
    const v = this.modalState();
    return v === undefined ? null : (v ?? null);
  });
  readonly submitting = signal(false);
  readonly formError = signal<string | null>(null);

  constructor() {
    this.state.bulkActions.set([
      {
        key: 'reassign',
        label: 'Reassign to…',
        icon: 'user-cog',
        permissionKey: 'contacts.reassign',
      },
      { key: 'tag', label: 'Add tag', icon: 'tag', permissionKey: 'contacts.write' },
      {
        key: 'delete',
        label: 'Delete',
        icon: 'trash-2',
        danger: true,
        permissionKey: 'contacts.write',
      },
    ]);
    // Initial load — runs after the effect below subscribes to the filter signals.
    this.reload();

    // Reactive: any filter change resets to page 1 and re-fetches.
    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.state.page.set(1);
        this.reload();
      });
    this.sourceControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.state.page.set(1);
        this.reload();
      });
    this.tagControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.state.page.set(1);
        this.reload();
      });
    // Honour `/user/contacts?new=1` (used by the dashboard quick-action)
    // so landing on the page from elsewhere drops the user straight
    // into the create-contact modal. Strip the param after consuming
    // it so a refresh doesn't re-open.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      if (params.get('new') !== null && this.modalState() === null) {
        this.openCreate();
        this.router.navigate([], {
          relativeTo: this.route,
          queryParams: { new: null },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      }
    });

    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.state.page.set(1);
        this.reload();
      });
  }

  /** Click a sortable header. Same key → flip order; new key → reset to a
   * sensible default (ascending for `full_name`, descending for the
   * timestamp columns where the user usually wants newest first). */
  protected toggleSort(key: ContactSortKey): void {
    if (this.sortKey() === key) {
      this.sortOrder.update((o) => (o === 'asc' ? 'desc' : 'asc'));
    } else {
      this.sortKey.set(key);
      this.sortOrder.set(key === 'full_name' ? 'asc' : 'desc');
    }
    this.state.page.set(1);
    this.reload();
  }

  /** Resolve the assignee filter to a UUID. `'me'` reads the current user
   * id from `FurnitureAuthService` (populated by `/users/me`). Empty
   * string means "no filter". */
  private resolveAssignee(): string | undefined {
    const raw = this.assigneeControl.value;
    if (!raw) return undefined;
    if (raw === 'me') return this.auth.currentUserId() ?? undefined;
    return raw;
  }

  /** Display label for the Owner column. Tries the cached users
   * directory; falls back to "Unassigned" / "Unknown". */
  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  protected reload(): void {
    this.state.loading.set(true);
    this.state.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        tag: this.tagFilter() || undefined,
        assigned_to_id: this.resolveAssignee(),
        sort: this.sortKey(),
        order: this.sortOrder(),
        page: this.state.page(),
        size: this.state.pageSize(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.state.items.set(resp.items);
          this.state.total.set(resp.total);
          this.state.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.state.items.set([]);
          this.state.total.set(0);
          this.state.loadError.set(extractApiError(err) ?? 'Could not load contacts.');
          this.state.loading.set(false);
        },
      });
  }

  protected onRowClick(item: ContactListItem): void {
    this.router.navigate(['/user/contacts', item.id]);
  }

  protected openCreate(): void {
    this.formError.set(null);
    this.modalState.set(undefined);
  }

  protected closeModal(): void {
    this.modalState.set(null);
    this.formError.set(null);
    this.submitting.set(false);
  }

  protected onSave(event: { create?: ContactCreate; update?: ContactUpdate }): void {
    if (event.create) {
      this.submitCreate(event.create);
    } else if (event.update) {
      const existing = this.editingContact();
      if (existing) this.submitUpdate(existing.id, event.update);
    }
  }

  protected goToPage(target: number): void {
    if (target < 1 || target > this.state.totalPages() || target === this.state.page()) return;
    this.state.page.set(target);
    this.reload();
  }

  protected setPageSize(target: number): void {
    if (target !== 25 && target !== 50 && target !== 100) return;
    if (target === this.state.pageSize()) return;
    this.state.pageSize.set(target);
    this.state.page.set(1);
    this.reload();
  }

  protected onExportCsv(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    this.api
      .exportCsv({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        tag: this.tagFilter() || undefined,
        assigned_to_id: this.resolveAssignee(),
        // Passthrough any `custom.<key>=<value>` params already present
        // on the URL so the export mirrors the on-screen filter set.
        // The list page has no UI to set these today; the export path
        // shouldn't lose them the moment we add one.
        customFilters: this._readCustomFiltersFromUrl(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.triggerDownload(blob);
          this.exporting.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.exporting.set(false);
          this.state.loadError.set(
            extractApiError(err) ?? 'Could not export. Narrow the filter and try again.',
          );
        },
      });
  }

  /** Pull every `custom.<key>` query param off the current URL and
   *  return them as a `{key: value}` map for `exportCsv`. Returns
   *  undefined when the URL carries none — the API service skips the
   *  passthrough on undefined. */
  private _readCustomFiltersFromUrl(): Record<string, string> | undefined {
    const map = this.route.snapshot.queryParamMap;
    const out: Record<string, string> = {};
    for (const key of map.keys) {
      if (!key.startsWith('custom.') || key.length <= 'custom.'.length) continue;
      const value = map.get(key);
      if (value != null) out[key.slice('custom.'.length)] = value;
    }
    return Object.keys(out).length > 0 ? out : undefined;
  }

  /** Browser-side blob → download. Synthesises a hidden anchor so the
   * file lands on disk without leaving the SPA. Filename comes from
   * the response Content-Disposition (set by the backend); browsers
   * generally honour it on same-origin downloads. */
  private triggerDownload(blob: Blob): void {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // Filename fallback when Content-Disposition isn't honoured.
    a.download = 'contacts.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  private submitCreate(payload: ContactCreate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .create(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not create contact.');
        },
      });
  }

  private submitUpdate(id: string, payload: ContactUpdate): void {
    this.submitting.set(true);
    this.formError.set(null);
    this.api
      .update(id, payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.closeModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.formError.set(extractApiError(err) ?? 'Could not save contact.');
        },
      });
  }

  // --- Bulk-selection handlers ---------------------------------------------

  protected toggleRow(id: string, event: Event): void {
    // Stop the row's `(click)` from navigating to detail.
    event.stopPropagation();
    this.state.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected toggleAllOnPage(): void {
    const ids = this.state.items().map((i) => i.id);
    const sel = this.state.selectedIds();
    const allSelected = ids.length > 0 && ids.every((id) => sel.has(id));
    if (allSelected) {
      // Drop just the visible rows; preserve any cross-page selections.
      this.state.selectedIds.update((set) => {
        const next = new Set(set);
        for (const id of ids) next.delete(id);
        return next;
      });
    } else {
      this.state.selectedIds.update((set) => {
        const next = new Set(set);
        for (const id of ids) next.add(id);
        return next;
      });
    }
  }

  protected clearSelection(): void {
    this.state.selectedIds.set(new Set());
  }

  protected onBulkAction(key: string): void {
    this.state.bulkError.set(null);
    if (key === 'reassign') this.state.bulkModal.set('reassign');
    else if (key === 'tag') {
      this.tagInputControl.setValue('');
      this.state.bulkModal.set('tag');
    } else if (key === 'delete') this.state.bulkModal.set('delete');
  }

  protected closeBulkModal(): void {
    this.state.bulkModal.set(null);
    this.state.bulkError.set(null);
    this.state.bulkSubmitting.set(false);
  }

  protected onBulkReassign(payload: ReassignConfirm): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not reassign.');
        },
      });
  }

  protected onBulkDelete(): void {
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkDelete(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not delete.');
        },
      });
  }

  protected onBulkAddTag(): void {
    const tag = this.tagInputControl.value.trim();
    if (!tag) {
      this.state.bulkError.set('Enter a tag.');
      return;
    }
    const ids = [...this.state.selectedIds()];
    if (ids.length === 0) return;
    this.state.bulkSubmitting.set(true);
    this.state.bulkError.set(null);
    this.api
      .bulkAddTag(ids, tag)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.state.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.state.bulkSubmitting.set(false);
          this.state.bulkError.set(extractApiError(err) ?? 'Could not add tag.');
        },
      });
  }
}
