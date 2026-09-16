import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injectable,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
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
import { ColumnFilterComponent } from '../shared/table-filters/column-filter.component';
import type { ColumnFilterOption } from '../shared/table-filters/column-filter.types';
import { extractApiError } from '@core/services/api-error.util';
import { initials } from '@core/services/text.util';

@Injectable()
class ContactsListState extends ListPageState<ContactListItem> {}

@Component({
  selector: 'app-contacts-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DecimalPipe,
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
    ColumnFilterComponent,
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

  /** Column-header filter state — one signal per filterable column.
   *  Held as `string[]` (not `Set`) so URL persistence can `.join(',')`
   *  round-trip cleanly and the API service can serialize repeated
   *  params via `buildHttpParams`. `[]` means no filter on the column. */
  readonly sourceFilter = signal<string[]>([]);
  readonly tagFilter = signal<string[]>([]);
  /** Owner UUIDs. The current user's own UUID is offered as an option
   *  labelled "Me" so the previous "assignee=me" behaviour is preserved
   *  without a magic string. */
  readonly assigneeFilter = signal<string[]>([]);

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

  /** Distinct source options for the column-header filter popover.
   *  Contacts store `source` as free-form text — some rows use raw
   *  enum keys ("google_ads"), others use pretty labels ("Google Ads"),
   *  and casing varies ("facebook" vs "Facebook Ads"). Collapse to
   *  one canonical entry per lowercase key so the popover doesn't
   *  show the same source twice. `value` is the original raw string
   *  of the first occurrence (what the backend filter matches on);
   *  `label` is the display-only prettified version. */
  /** Source column-filter options. Fixed list mirroring the Add Lead
   *  modal + Contact create form, so every canonical source shows up
   *  in the popover regardless of what data currently exists.
   *
   *  Previously derived from `state.items()`, but that had two bugs:
   *  contacts created via the Add Lead modal don't have `source`
   *  populated (source lives on the LEAD row), so the popover came
   *  back empty for orgs whose contacts came in through that path.
   *  Second, filtering to a source that no live contact matched hid
   *  it from the popover entirely — no way to switch back off the
   *  filter without a page reload. */
  readonly sourceOptions = computed<ColumnFilterOption[]>(() => [
    { value: 'manual', label: 'Manual' },
    { value: 'walk_in', label: 'Walk-in' },
    { value: 'widget', label: 'Forms' },
    { value: 'google_ads', label: 'Google Ads' },
    { value: 'meta_ads', label: 'Meta Ads' },
    { value: 'whatsapp_flow', label: 'WhatsApp' },
    { value: 'bulk_import', label: 'Bulk import' },
  ]);

  /** Prettify a raw source token ("google_ads" → "Google Ads"). Same
   *  logic as leads.page.ts; kept local so contacts doesn't take a
   *  dependency on the leads module. */
  private prettifySource(raw: string): string {
    const trimmed = raw.trim();
    if (!trimmed) return trimmed;
    if (/\s/.test(trimmed) && trimmed !== trimmed.toLowerCase()) return trimmed;
    return trimmed.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }

  readonly tagOptions = computed<ColumnFilterOption[]>(() => {
    const set = new Set<string>();
    for (const item of this.state.items()) {
      for (const t of item.tags) set.add(t);
    }
    return [...set].sort().map((t) => ({ value: t, label: t }));
  });

  /** Owner options for the Owner column popover — every active org
   *  user, with the current user pinned first as "Me" so the previous
   *  "quick-filter to my rows" affordance is still one click away. */
  readonly assigneeOptions = computed<ColumnFilterOption[]>(() => {
    const me = this.auth.currentUserId();
    const rows = this.users();
    const out: ColumnFilterOption[] = [];
    if (me) {
      const meUser = rows.find((u) => u.id === me);
      out.push({ value: me, label: meUser ? `Me (${meUser.full_name})` : 'Me' });
    }
    for (const u of rows) {
      if (u.id === me) continue;
      out.push({ value: u.id, label: u.full_name });
    }
    return out;
  });

  // --- Multi-select + bulk actions -------------------------------------------

  readonly tagInputControl = new FormControl<string>('', { nonNullable: true });

  /** CSV export progress (single in-flight at a time). */
  readonly exporting = signal(false);

  /** URL ↔ filter state map. Wires every filter signal / FormControl to a
   * query-param key so refresh / share / browser-back preserve the view.
   * `replaceUrl: true` keeps history clean while typing in the search box.
   *
   * Column filters serialize as comma-separated values on the URL
   * (`?source=Website,Walk-in`) so the shape stays a single string per
   * key — matches every other UrlFilterEntry contract and keeps
   * shared URLs compact. */
  readonly urlState: UrlFilterStateConfig = {
    q: {
      read: () => this.searchControl.value,
      write: (v) => this.searchControl.setValue(v),
      queryKey: 'q',
    },
    source: {
      read: () => this.sourceFilter().join(','),
      write: (v) => this.sourceFilter.set(this.parseCsvFilter(v)),
      queryKey: 'source',
    },
    tag: {
      read: () => this.tagFilter().join(','),
      write: (v) => this.tagFilter.set(this.parseCsvFilter(v)),
      queryKey: 'tag',
    },
    assignee: {
      read: () => this.assigneeFilter().join(','),
      write: (v) => this.assigneeFilter.set(this.parseCsvFilter(v)),
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

    // Reactive: search box change resets to page 1 and re-fetches.
    // Column-header filters call `onColumnFilterChange` directly so
    // they follow the same reset-and-reload path without a separate
    // valueChanges pipeline. Drive the reload off the `q()` signal
    // (already debounced+distinct via toSignal on the same control)
    // — subscribing a second time to `valueChanges` with its own
    // debounce raced against the signal write and could `reload()`
    // with the previous `q` value.
    let initialQ = true;
    effect(() => {
      // Track q() so the effect re-runs on debounced search changes.
      this.q();
      if (initialQ) {
        initialQ = false;
        return;
      }
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
  }

  /** Column-filter popover callback — write the new selection, reset
   *  to page 1, refetch. Used by every filterable header. */
  protected onColumnFilterChange(target: 'source' | 'tag' | 'assignee', values: string[]): void {
    if (target === 'source') this.sourceFilter.set(values);
    else if (target === 'tag') this.tagFilter.set(values);
    else this.assigneeFilter.set(values);
    this.state.page.set(1);
    this.reload();
  }

  /** Parse a comma-separated URL filter value ("Website,Walk-in") into
   *  a de-duped `string[]`. Trims each part; drops empties. Symmetric
   *  with `read: () => filter.join(',')` in `urlState`. */
  private parseCsvFilter(raw: string): string[] {
    if (!raw) return [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const part of raw.split(',')) {
      const trimmed = part.trim();
      if (!trimmed || seen.has(trimmed)) continue;
      seen.add(trimmed);
      out.push(trimmed);
    }
    return out;
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

  /** Owner UUIDs to send with the list / export call. `[]` → skip. */
  private resolveAssignee(): string[] | undefined {
    const raw = this.assigneeFilter();
    return raw.length > 0 ? raw : undefined;
  }

  /** Display label for the Owner column. Tries the cached users
   * directory; falls back to "Unassigned" / "Unknown". */
  protected ownerLabel(assignedTo: string | null): string {
    if (!assignedTo) return 'Unassigned';
    return this.userMap().get(assignedTo) ?? 'Unknown';
  }

  /** Monotonic request id — bumped on every `reload()`, checked in the
   *  response callback so a slow earlier response can't overwrite a
   *  faster later one when the user changes filters quickly. */
  private reloadSeq = 0;

  protected reload(): void {
    const seq = ++this.reloadSeq;
    this.state.loading.set(true);
    this.state.loadError.set(null);
    const sources = this.sourceFilter();
    const tags = this.tagFilter();
    this.api
      .list({
        q: this.q() || undefined,
        source: sources.length > 0 ? sources : undefined,
        tag: tags.length > 0 ? tags : undefined,
        assigned_to_id: this.resolveAssignee(),
        sort: this.sortKey(),
        order: this.sortOrder(),
        page: this.state.page(),
        size: this.state.pageSize(),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          if (seq !== this.reloadSeq) return;
          this.state.items.set(resp.items);
          this.state.total.set(resp.total);
          this.state.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          if (seq !== this.reloadSeq) return;
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
    const sources = this.sourceFilter();
    const tags = this.tagFilter();
    this.api
      .exportCsv({
        q: this.q() || undefined,
        source: sources.length > 0 ? sources : undefined,
        tag: tags.length > 0 ? tags : undefined,
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
