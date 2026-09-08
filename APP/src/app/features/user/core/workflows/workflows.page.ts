import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../auth/auth.service';
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { MobileSelectComponent } from '../shared/forms/mobile-select.component';

import { FolderCreateModalComponent } from './folders/folder-create.modal.component';
import { FoldersSidebarComponent } from './folders/folders-sidebar.component';
import { RunHistoryDrawerComponent } from './run-history-drawer.component';
import { WorkflowStatusBadgeComponent } from './workflow-status-badge.component';
import {
  WorkflowFolder,
  WorkflowRead,
  WorkflowStatus,
  WorkflowsApiService,
} from './workflows-api.service';

/**
 * Workflows list — Step 13's first frontend surface.
 *
 * Two-column layout: folder sidebar + filtered grid. Filters are
 * channel-derived from `enabled_event_types` (e.g. event types
 * starting with `email.` / `whatsapp.`), category, status, and a
 * 300ms-debounced search. Bulk select supports activate / pause /
 * archive in one POST per row. "New workflow" + per-row mutation
 * affordances are hidden when the user lacks `workflows.write`.
 *
 * Step 14 will wire the row CTA to `/user/workflows/{id}` canvas;
 * for Step 13 the row click opens the canvas placeholder route via
 * `[routerLink]`.
 */

const PAGE_SIZE = 50;

const STATUS_OPTIONS: Array<{
  value: '' | WorkflowStatus;
  label: string;
}> = [
  { value: '', label: 'All statuses' },
  { value: 'draft', label: 'Draft' },
  { value: 'active', label: 'Active' },
  { value: 'paused', label: 'Paused' },
  { value: 'archived', label: 'Archived' },
];

const CATEGORY_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All categories' },
  { value: 'Sales', label: 'Sales' },
  { value: 'Marketing', label: 'Marketing' },
  { value: 'Service', label: 'Service' },
  { value: 'Internal', label: 'Internal' },
  { value: 'Custom', label: 'Custom' },
];

const CHANNEL_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'All channels' },
  { value: 'email', label: 'Email' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'sms', label: 'SMS' },
  { value: 'facebook', label: 'Facebook' },
  { value: 'instagram', label: 'Instagram' },
  { value: 'push', label: 'Push' },
];

@Component({
  selector: 'app-workflows-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    DatePipe,
    LucideAngularModule,
    WorkflowStatusBadgeComponent,
    FoldersSidebarComponent,
    FolderCreateModalComponent,
    RunHistoryDrawerComponent,
    MobileSelectComponent,
  ],
  templateUrl: './workflows.page.html',
})
export class WorkflowsPageComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly confirmDialog = inject(ConfirmDialogService);

  protected readonly STATUS_OPTIONS = STATUS_OPTIONS;
  protected readonly CATEGORY_OPTIONS = CATEGORY_OPTIONS;
  protected readonly CHANNEL_OPTIONS = CHANNEL_OPTIONS;
  protected readonly PAGE_SIZE = PAGE_SIZE;

  // List state.
  protected readonly items = signal<WorkflowRead[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pageIndex = signal<number>(0);

  // Folders.
  protected readonly folders = signal<WorkflowFolder[]>([]);
  protected readonly selectedFolderId = signal<string | null>(null);
  protected readonly showCreateFolder = signal<boolean>(false);

  // Filters.
  protected readonly statusFilter = signal<'' | WorkflowStatus>('');
  protected readonly categoryFilter = signal<string>('');
  protected readonly channelFilter = signal<string>('');
  protected readonly searchQuery = signal<string>('');
  protected readonly debouncedSearch = signal<string>('');
  // tasks/workflow-scheduling Step 5 — three-state chip: null=any,
  // true=only workflows with an active schedule,
  // false=only workflows without one.
  protected readonly scheduledFilter = signal<boolean | null>(null);

  // Bulk selection.
  protected readonly selectedIds = signal<Set<string>>(new Set());
  protected readonly mutating = signal<boolean>(false);

  /** Rows in the current page that the operator has ticked. */
  protected readonly selectedRows = computed(() => {
    const ids = this.selectedIds();
    return this.items().filter((row) => ids.has(row.id));
  });

  /** Activate is only useful when at least one selected row is NOT
   * already running. Active rows refusing re-activation is a no-op
   * server-side, but the button looking enabled when there's nothing
   * to do is misleading UX. */
  protected readonly canBulkActivate = computed(() =>
    this.selectedRows().some((r) => r.status !== 'active'),
  );

  /** Pause only makes sense when at least one selected row IS active. */
  protected readonly canBulkPause = computed(() =>
    this.selectedRows().some((r) => r.status === 'active'),
  );

  /** Archive is hidden when ANY selected row is a system default
   * (the backend refuses 409 on those) or already archived. */
  protected readonly canBulkArchive = computed(() => {
    const rows = this.selectedRows();
    if (rows.length === 0) return false;
    return rows.every((r) => r.status !== 'archived' && !r.is_system_default);
  });

  // Run-history drawer.
  protected readonly runHistoryWorkflow = signal<WorkflowRead | null>(null);

  // Per-row "more" menu.
  protected readonly openMenuId = signal<string | null>(null);

  protected readonly canWrite = computed(() => this.auth.hasPermission('workflows.write'));
  protected readonly canActivate = computed(
    () => this.auth.hasPermission('workflows.activate') || this.canWrite(),
  );
  protected readonly canClone = computed(
    () => this.auth.hasPermission('workflows.clone') || this.canWrite(),
  );

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly hasPrev = computed(() => this.pageIndex() > 0);
  protected readonly hasNext = computed(() => this.pageIndex() < this.totalPages() - 1);

  protected readonly hasFilters = computed(
    () =>
      !!this.statusFilter() ||
      !!this.categoryFilter() ||
      !!this.channelFilter() ||
      !!this.debouncedSearch() ||
      this.scheduledFilter() !== null ||
      this.selectedFolderId() !== null,
  );

  private searchTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Folders load once at page mount.
    this.api
      .listFolders()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.folders.set(rows),
        error: () => {
          // Non-fatal — the sidebar just stays empty.
        },
      });

    // Re-fetch the list on any filter / page change.
    effect(() => {
      const status = this.statusFilter();
      const category = this.categoryFilter();
      const channel = this.channelFilter();
      const folder = this.selectedFolderId();
      const q = this.debouncedSearch();
      const scheduled = this.scheduledFilter();
      const page = this.pageIndex();
      void status;
      void category;
      void channel;
      void folder;
      void q;
      void scheduled;
      void page;
      this.reload();
    });
  }

  // --- filters / search ---------------------------------------------

  protected onStatusChange(value: string): void {
    this.statusFilter.set(value as '' | WorkflowStatus);
    this.pageIndex.set(0);
  }

  protected onCategoryChange(value: string): void {
    this.categoryFilter.set(value);
    this.pageIndex.set(0);
  }

  protected onChannelChange(value: string): void {
    this.channelFilter.set(value);
    this.pageIndex.set(0);
  }

  protected onSearchInput(value: string): void {
    this.searchQuery.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => {
      this.debouncedSearch.set(value.trim());
      this.pageIndex.set(0);
    }, 300);
  }

  protected clearFilters(): void {
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.statusFilter.set('');
    this.categoryFilter.set('');
    this.channelFilter.set('');
    this.searchQuery.set('');
    this.debouncedSearch.set('');
    this.selectedFolderId.set(null);
    this.scheduledFilter.set(null);
    this.pageIndex.set(0);
  }

  /** Toggle the 3-state Scheduled chip: any → scheduled only →
   *  unscheduled only → any. */
  protected toggleScheduledFilter(): void {
    const cur = this.scheduledFilter();
    const next = cur === null ? true : cur === true ? false : null;
    this.scheduledFilter.set(next);
    this.pageIndex.set(0);
  }

  /** Human label for the current Scheduled chip state. */
  protected scheduledChipLabel(): string {
    const s = this.scheduledFilter();
    if (s === null) return 'Any';
    return s ? 'Scheduled only' : 'Unscheduled only';
  }

  protected onFolderSelected(id: string | null): void {
    this.selectedFolderId.set(id);
    this.pageIndex.set(0);
  }

  protected onNewFolderRequested(): void {
    this.showCreateFolder.set(true);
  }

  protected onFolderCreated(folder: WorkflowFolder): void {
    this.folders.update((rows) => [...rows, folder]);
    this.showCreateFolder.set(false);
  }

  protected onFolderCreateCancelled(): void {
    this.showCreateFolder.set(false);
  }

  protected onFoldersChanged(next: WorkflowFolder[]): void {
    this.folders.set(next);
  }

  // --- pagination ---------------------------------------------------

  protected nextPage(): void {
    if (this.hasNext()) this.pageIndex.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.hasPrev()) this.pageIndex.update((p) => p - 1);
  }

  // --- selection ----------------------------------------------------

  protected isSelected(id: string): boolean {
    return this.selectedIds().has(id);
  }

  protected toggleSelected(id: string, event?: Event): void {
    event?.stopPropagation();
    const ids = new Set(this.selectedIds());
    if (ids.has(id)) {
      ids.delete(id);
    } else {
      ids.add(id);
    }
    this.selectedIds.set(ids);
  }

  protected toggleSelectAll(): void {
    if (this.selectedIds().size === this.items().length) {
      this.selectedIds.set(new Set());
    } else {
      this.selectedIds.set(new Set(this.items().map((r) => r.id)));
    }
  }

  protected get isAllSelected(): boolean {
    return this.items().length > 0 && this.selectedIds().size === this.items().length;
  }

  // --- bulk actions -------------------------------------------------

  protected bulkActivate(): void {
    this.runBulk('activate');
  }

  protected bulkPause(): void {
    this.runBulk('pause');
  }

  protected async bulkArchive(): Promise<void> {
    const count = this.selectedIds().size;
    const ok = await this.confirmDialog.ask({
      title: `Archive ${count} workflow${count === 1 ? '' : 's'}?`,
      body: 'Outstanding runs continue under the archived version, but no new enrollments will happen.',
      confirmLabel: 'Archive',
      danger: true,
    });
    if (!ok) return;
    this.runBulk('archive');
  }

  private runBulk(verb: 'activate' | 'pause' | 'archive'): void {
    const ids = Array.from(this.selectedIds());
    if (ids.length === 0 || this.mutating()) return;
    this.mutating.set(true);
    this.loadError.set(null);

    const calls = ids.map((id) => {
      if (verb === 'activate') return this.api.activate(id);
      if (verb === 'pause') return this.api.pause(id);
      return this.api.archive(id);
    });

    forkJoin(calls)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.mutating.set(false);
          this.selectedIds.set(new Set());
          // Patch the local list in-place.
          this.items.update((rows) =>
            rows.map((r) => {
              const found = updated.find((u) => u.id === r.id);
              return found ?? r;
            }),
          );
        },
        error: (err: HttpErrorResponse) => {
          this.mutating.set(false);
          this.loadError.set(extractApiError(err) ?? 'Some workflows could not be updated.');
          // Refetch to reconcile.
          this.reload();
        },
      });
  }

  // --- per-row actions ----------------------------------------------

  protected toggleMenu(id: string, event: MouseEvent): void {
    event.stopPropagation();
    this.openMenuId.update((current) => (current === id ? null : id));
  }

  protected closeMenu(): void {
    this.openMenuId.set(null);
  }

  protected async onClone(row: WorkflowRead, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    this.closeMenu();
    if (!this.canClone()) return;
    const name = await this.confirmDialog.prompt({
      title: 'Clone workflow',
      body: `A copy of "${row.name}" will be created as a draft. Give the copy a name — you can rename it later.`,
      placeholder: 'Workflow name',
      initialValue: `${row.name} (copy)`,
      confirmLabel: 'Clone',
    });
    if (!name) return;
    this.api
      .clone(row.id, name.trim())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (clone) => {
          this.items.update((rows) => [clone, ...rows]);
          this.total.update((n) => n + 1);
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not clone workflow.');
        },
      });
  }

  protected async onArchiveRow(row: WorkflowRead, event: MouseEvent): Promise<void> {
    event.stopPropagation();
    this.closeMenu();
    if (!this.canWrite()) return;
    const ok = await this.confirmDialog.ask({
      title: `Archive "${row.name}"?`,
      body: 'Outstanding runs continue under the archived version, but no new enrollments will happen.',
      confirmLabel: 'Archive',
      danger: true,
    });
    if (!ok) return;
    this.api
      .archive(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.items.update((rows) => rows.map((r) => (r.id === row.id ? updated : r)));
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not archive workflow.');
        },
      });
  }

  protected openRunHistory(row: WorkflowRead, event: MouseEvent): void {
    event.stopPropagation();
    this.closeMenu();
    this.runHistoryWorkflow.set(row);
  }

  protected closeRunHistory(): void {
    this.runHistoryWorkflow.set(null);
  }

  // --- Move to folder ----------------------------------------------
  //
  // Works for every workflow — including the 15 default seeded rows
  // and any pack-installed ones — because folder membership is a
  // plain nullable FK, not part of the seed identity. Moving is
  // safe: it never touches name / category / graph, so re-seeding or
  // upgrades keep re-emitting the row with the same fingerprint and
  // the DB just reads the operator's chosen folder_id.
  //
  // Single-row and bulk share the same modal — `moveMode()` switches
  // between them. Single-row carries the target row for context;
  // bulk consumes the current `selectedIds()` set.

  protected readonly moveTargetRow = signal<WorkflowRead | null>(null);
  protected readonly moveBulkOpen = signal(false);
  protected readonly moveTargetFolderId = signal<string | null>(null);
  protected readonly moveSaving = signal(false);
  protected readonly moveError = signal<string | null>(null);

  /** `'single'` when opened from a row's kebab; `'bulk'` when opened
   *  from the multi-select bar; `null` when closed. */
  protected readonly moveMode = computed<'single' | 'bulk' | null>(() => {
    if (this.moveTargetRow() !== null) return 'single';
    if (this.moveBulkOpen()) return 'bulk';
    return null;
  });

  /** Count for the modal header. 1 for single, N for bulk. */
  protected readonly moveCount = computed(() =>
    this.moveMode() === 'bulk' ? this.selectedIds().size : 1,
  );

  /** Blocks the Move button when the selected target matches the
   *  current folder of a single row (bulk always allows submit, since
   *  rows in the set may have different current folders). */
  protected readonly moveHasChange = computed(() => {
    if (this.moveMode() !== 'single') return this.moveMode() !== null;
    const row = this.moveTargetRow();
    if (!row) return false;
    return (row.folder_id ?? null) !== this.moveTargetFolderId();
  });

  protected openMove(row: WorkflowRead, event: MouseEvent): void {
    event.stopPropagation();
    this.closeMenu();
    if (!this.canWrite()) return;
    this.moveTargetRow.set(row);
    this.moveBulkOpen.set(false);
    this.moveTargetFolderId.set(row.folder_id ?? null);
    this.moveError.set(null);
  }

  protected openBulkMove(): void {
    if (!this.canWrite() || this.selectedIds().size === 0) return;
    this.moveTargetRow.set(null);
    this.moveBulkOpen.set(true);
    this.moveTargetFolderId.set(null);
    this.moveError.set(null);
  }

  protected setMoveTargetFolder(id: string | null): void {
    this.moveTargetFolderId.set(id);
  }

  protected closeMove(): void {
    if (this.moveSaving()) return; // don't dismiss mid-request
    this.moveTargetRow.set(null);
    this.moveBulkOpen.set(false);
    this.moveTargetFolderId.set(null);
    this.moveSaving.set(false);
    this.moveError.set(null);
  }

  /** Bound to the modal's backdrop keydown so Esc closes it. Guarded
   *  by the same not-saving check as the backdrop click. */
  protected onMoveModalKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.closeMove();
  }

  protected confirmMove(): void {
    const mode = this.moveMode();
    if (mode === null) return;
    const target = this.moveTargetFolderId();

    if (mode === 'single') {
      const row = this.moveTargetRow();
      if (!row) return;
      // No-op guard: don't PATCH when nothing actually changes.
      if ((row.folder_id ?? null) === target) {
        this.closeMove();
        return;
      }
      this.moveSaving.set(true);
      this.moveError.set(null);
      this.api
        .patch(row.id, { folder_id: target })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (updated) => {
            this.items.update((rows) => rows.map((r) => (r.id === row.id ? updated : r)));
            this.moveSaving.set(false);
            this.closeMove();
            if (this.selectedFolderId() !== null) this.reload();
          },
          error: (err: HttpErrorResponse) => {
            this.moveSaving.set(false);
            this.moveError.set(extractApiError(err) ?? 'Could not move workflow.');
          },
        });
      return;
    }

    // Bulk — fan out N PATCH requests via forkJoin. Matches the
    // existing bulkActivate/pause/archive pattern; there's no
    // server-side batch endpoint by design (per-row PATCH keeps the
    // audit trail granular).
    const ids = Array.from(this.selectedIds());
    if (ids.length === 0) return;
    this.moveSaving.set(true);
    this.moveError.set(null);
    forkJoin(ids.map((id) => this.api.patch(id, { folder_id: target })))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updatedList) => {
          this.items.update((rows) =>
            rows.map((r) => {
              const found = updatedList.find((u) => u.id === r.id);
              return found ?? r;
            }),
          );
          this.moveSaving.set(false);
          this.selectedIds.set(new Set());
          this.closeMove();
          if (this.selectedFolderId() !== null) this.reload();
        },
        error: (err: HttpErrorResponse) => {
          this.moveSaving.set(false);
          this.moveError.set(extractApiError(err) ?? 'Some workflows could not be moved.');
          this.reload();
        },
      });
  }

  // --- derived helpers ---------------------------------------------

  /** Pick a representative channel chip from `enabled_event_types`. */
  protected channelOf(row: WorkflowRead): string | null {
    for (const evt of row.enabled_event_types) {
      const prefix = evt.split('.')[0];
      if (['email', 'whatsapp', 'sms', 'facebook', 'instagram', 'push'].includes(prefix)) {
        return prefix;
      }
    }
    return null;
  }

  // --- fetch --------------------------------------------------------

  private reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const offset = this.pageIndex() * PAGE_SIZE;
    this.api
      .list({
        status: this.statusFilter() || undefined,
        category: this.categoryFilter() || undefined,
        folder_id: this.selectedFolderId() || undefined,
        q: this.debouncedSearch() || undefined,
        has_schedule: this.scheduledFilter() ?? undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          // Client-side channel filter — backend doesn't filter on
          // enabled_event_types directly. Cheap because we paginate
          // server-side first.
          let rows = res.items;
          const channel = this.channelFilter();
          if (channel) {
            rows = rows.filter((r) =>
              r.enabled_event_types.some((evt) => evt.toLowerCase().startsWith(`${channel}.`)),
            );
          }
          this.items.set(rows);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load workflows.');
        },
      });
  }

  protected trackById = (_: number, row: WorkflowRead) => row.id;

  // --- tasks/workflow-scheduling Step 5 — per-workflow bulk actions --

  /** Toast-ish transient status line shown after a bulk pause/resume
   *  completes. Cleared after 4 seconds. NOT a global snack — matches
   *  the in-page `loadError` pattern used elsewhere in this file. */
  protected readonly bulkScheduleMessage = signal<string | null>(null);
  private bulkMessageTimer: ReturnType<typeof setTimeout> | null = null;

  protected pauseAllSchedules(row: WorkflowRead, event?: Event): void {
    event?.stopPropagation();
    this.openMenuId.set(null);
    if (!row.active_schedule_count) return;
    this.api
      .pauseAllSchedulesForWorkflow(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (summary) => {
          this.showBulkMessage(
            `${summary.paused} paused${
              summary.skipped ? `, ${summary.skipped} already paused` : ''
            }${summary.errored ? `, ${summary.errored} errored` : ''}.`,
          );
          // Refresh the row so the next-run column empties out.
          this.reload();
        },
        error: () => {
          this.showBulkMessage('Could not pause schedules.');
        },
      });
  }

  protected resumeAllSchedules(row: WorkflowRead, event?: Event): void {
    event?.stopPropagation();
    this.openMenuId.set(null);
    this.api
      .resumeAllSchedulesForWorkflow(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (summary) => {
          this.showBulkMessage(
            `${summary.resumed} resumed${
              summary.skipped ? `, ${summary.skipped} skipped` : ''
            }${summary.errored ? `, ${summary.errored} errored` : ''}.`,
          );
          this.reload();
        },
        error: () => {
          this.showBulkMessage('Could not resume schedules.');
        },
      });
  }

  private showBulkMessage(text: string): void {
    this.bulkScheduleMessage.set(text);
    if (this.bulkMessageTimer !== null) clearTimeout(this.bulkMessageTimer);
    this.bulkMessageTimer = setTimeout(() => {
      this.bulkScheduleMessage.set(null);
      this.bulkMessageTimer = null;
    }, 4000);
  }
}
