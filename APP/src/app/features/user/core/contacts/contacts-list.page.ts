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
import { Router } from '@angular/router';
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
import { FurnitureAuthService } from '../auth/auth.service';
import { BulkAction, BulkActionBarComponent } from '../shared/bulk-action-bar/bulk-action-bar.component';
import { ConfirmDialogComponent } from '../shared/confirm-dialog/confirm-dialog.component';
import { MailLinkDirective } from '../shared/directives/mail-link.directive';
import { PhoneLinkDirective } from '../shared/directives/phone-link.directive';
import {
  UrlFilterStateConfig,
  UrlFilterStateDirective,
} from '../shared/directives/url-filter-state.directive';
import { WhatsappLinkDirective } from '../shared/directives/whatsapp-link.directive';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import { ReassignConfirm, ReassignModalComponent } from '../shared/reassign-modal/reassign-modal.component';
import { UsersDirectoryService } from '../shared/services/users-directory.service';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

@Component({
  selector: 'app-contacts-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    LucideAngularModule,
    ContactFormModalComponent,
    RelativeTimePipe,
    BulkActionBarComponent,
    ReassignModalComponent,
    ConfirmDialogComponent,
    PhoneLinkDirective,
    WhatsappLinkDirective,
    MailLinkDirective,
    UrlFilterStateDirective,
  ],
  templateUrl: './contacts-list.page.html',
})
export class ContactsListPageComponent {
  protected readonly initials = initials;
  private readonly api = inject(ContactsApiService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly auth = inject(FurnitureAuthService);
  private readonly usersDir = inject(UsersDirectoryService);

  readonly items = signal<ContactListItem[]>([]);
  readonly total = signal<number>(0);
  readonly loading = signal(false);
  readonly loadError = signal<string | null>(null);

  readonly page = signal<number>(1);
  /** Page-size dropdown choices. 25 is the default; bigger pages are
   * useful when a manager is doing a sweeping review of unassigned
   * rows but expensive on slow networks. */
  readonly pageSize = signal<number>(25);
  /** Backwards-compat alias for the prior constant `size` — many
   * template + handler call-sites still read it as `size()`. */
  protected get size(): number {
    return this.pageSize();
  }

  readonly searchControl = new FormControl('', { nonNullable: true });
  readonly sourceControl = new FormControl('', { nonNullable: true });
  readonly tagControl = new FormControl('', { nonNullable: true });
  /** Assignee filter. Empty = all, `'me'` resolves to current user, or a user UUID. */
  readonly assigneeControl = new FormControl<string>('', { nonNullable: true });

  /** Sort state. Defaults match the backend (`created_at desc`). */
  readonly sortKey = signal<ContactSortKey>('created_at');
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
  private readonly tagFilter = toSignal(
    this.tagControl.valueChanges.pipe(distinctUntilChanged()),
    { initialValue: '' },
  );

  /** Distinct source/tag chips for filter dropdowns â€” derived from the loaded page. */
  readonly sourceOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.items()) {
      if (item.source) set.add(item.source);
    }
    return [...set].sort();
  });

  readonly tagOptions = computed(() => {
    const set = new Set<string>();
    for (const item of this.items()) {
      for (const t of item.tags) set.add(t);
    }
    return [...set].sort();
  });

  readonly totalPages = computed(() => {
    const total = this.total();
    if (total === 0) return 1;
    return Math.ceil(total / this.size);
  });

  // --- Multi-select + bulk actions -------------------------------------------

  /** Row-id set for multi-select. Powers the BulkActionBar + bulk endpoints. */
  readonly selectedIds = signal<Set<string>>(new Set());

  readonly selectedCount = computed(() => this.selectedIds().size);

  /** Header checkbox state — true only when every visible row is selected. */
  readonly allOnPageSelected = computed(() => {
    const ids = this.items();
    if (ids.length === 0) return false;
    const sel = this.selectedIds();
    return ids.every((i) => sel.has(i.id));
  });

  /** Bulk-action menu. Each action is hide-don't-disable gated by permission. */
  readonly bulkActions = computed<BulkAction[]>(() => [
    { key: 'reassign', label: 'Reassign to…', icon: 'user-cog', permissionKey: 'contacts.reassign' },
    { key: 'tag', label: 'Add tag', icon: 'tag', permissionKey: 'contacts.write' },
    { key: 'delete', label: 'Delete', icon: 'trash-2', danger: true, permissionKey: 'contacts.write' },
  ]);

  /** Which bulk modal is open (one at a time). */
  readonly bulkModal = signal<'reassign' | 'tag' | 'delete' | null>(null);
  readonly bulkSubmitting = signal(false);
  readonly bulkError = signal<string | null>(null);
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
      defaultValue: 'created_at',
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
      read: () => String(this.page()),
      write: (v) => {
        const n = Number.parseInt(v, 10);
        if (Number.isFinite(n) && n >= 1) this.page.set(n);
      },
      queryKey: 'page',
      defaultValue: '1',
    },
    size: {
      read: () => String(this.pageSize()),
      write: (v) => {
        const n = Number.parseInt(v, 10);
        if (n === 25 || n === 50 || n === 100) this.pageSize.set(n);
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
    // Initial load â€” runs after the effect below subscribes to the filter signals.
    this.reload();

    // Reactive: any filter change resets to page 1 and re-fetches.
    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.sourceControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.tagControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
        this.reload();
      });
    this.assigneeControl.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.page.set(1);
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
    this.page.set(1);
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
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({
        q: this.q() || undefined,
        source: this.sourceFilter() || undefined,
        tag: this.tagFilter() || undefined,
        assigned_to_id: this.resolveAssignee(),
        sort: this.sortKey(),
        order: this.sortOrder(),
        page: this.page(),
        size: this.size,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.items.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loadError.set(extractApiError(err) ?? 'Could not load contacts.');
          this.loading.set(false);
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
    if (target < 1 || target > this.totalPages() || target === this.page()) return;
    this.page.set(target);
    this.reload();
  }

  protected setPageSize(target: number): void {
    if (target !== 25 && target !== 50 && target !== 100) return;
    if (target === this.pageSize()) return;
    this.pageSize.set(target);
    this.page.set(1);
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
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.triggerDownload(blob);
          this.exporting.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.exporting.set(false);
          this.loadError.set(
            extractApiError(err) ??
              'Could not export. Narrow the filter and try again.',
          );
        },
      });
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
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  protected toggleAllOnPage(): void {
    const ids = this.items().map((i) => i.id);
    const sel = this.selectedIds();
    const allSelected = ids.length > 0 && ids.every((id) => sel.has(id));
    if (allSelected) {
      // Drop just the visible rows; preserve any cross-page selections.
      this.selectedIds.update((set) => {
        const next = new Set(set);
        for (const id of ids) next.delete(id);
        return next;
      });
    } else {
      this.selectedIds.update((set) => {
        const next = new Set(set);
        for (const id of ids) next.add(id);
        return next;
      });
    }
  }

  protected clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  protected onBulkAction(key: string): void {
    this.bulkError.set(null);
    if (key === 'reassign') this.bulkModal.set('reassign');
    else if (key === 'tag') {
      this.tagInputControl.setValue('');
      this.bulkModal.set('tag');
    } else if (key === 'delete') this.bulkModal.set('delete');
  }

  protected closeBulkModal(): void {
    this.bulkModal.set(null);
    this.bulkError.set(null);
    this.bulkSubmitting.set(false);
  }

  protected onBulkReassign(payload: ReassignConfirm): void {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkReassign(ids, { userId: payload.userId, note: payload.note })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(extractApiError(err) ?? 'Could not reassign.');
        },
      });
  }

  protected onBulkDelete(): void {
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkDelete(ids)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(extractApiError(err) ?? 'Could not delete.');
        },
      });
  }

  protected onBulkAddTag(): void {
    const tag = this.tagInputControl.value.trim();
    if (!tag) {
      this.bulkError.set('Enter a tag.');
      return;
    }
    const ids = [...this.selectedIds()];
    if (ids.length === 0) return;
    this.bulkSubmitting.set(true);
    this.bulkError.set(null);
    this.api
      .bulkAddTag(ids, tag)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.bulkSubmitting.set(false);
          this.clearSelection();
          this.closeBulkModal();
          this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.bulkSubmitting.set(false);
          this.bulkError.set(extractApiError(err) ?? 'Could not add tag.');
        },
      });
  }

}
