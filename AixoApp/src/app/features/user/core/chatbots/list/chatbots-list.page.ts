import { CommonModule, DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { debounceTime, distinctUntilChanged, skip, switchMap, tap } from 'rxjs';

import { extractApiError } from '@core/services/api-error.util';

import { FurnitureAuthService } from '../../auth/auth.service';
import { ConfirmDialogComponent } from '../../shared/confirm-dialog/confirm-dialog.component';
import { ChatbotListItem, ChatbotStatus, ChatbotsApiService } from '../chatbots-api.service';
import { ChatbotCreateModalComponent } from './create-bot-modal/create-bot-modal.component';

/**
 * Chatbots list page (tasks/chatbot-builder Step 12).
 *
 * Route: `/user/chatbots`. Sidebar entry appears automatically via
 * the module-registry consumer (Step 3 backend `ModuleDescriptor`).
 *
 * v1 shape: header + status filter chips + search + table +
 * per-row actions menu. Folders sidebar is scaffolded but the
 * folder-CRUD endpoints aren't in Step 3 (deferred to a follow-up).
 * The list still respects `?folder_id=` when a folder id is
 * present in the URL — future Step-15 export/import can land the
 * folder UI without changing this page's shape.
 */

const PAGE_SIZE = 100;

interface StatusFilter {
  value: '' | ChatbotStatus;
  label: string;
  tone: string;
}

const STATUS_FILTERS: StatusFilter[] = [
  { value: '', label: 'All', tone: 'bg-surface-2 text-default' },
  { value: 'draft', label: 'Draft', tone: 'bg-amber-500/15 text-amber-500' },
  { value: 'live', label: 'Live', tone: 'bg-emerald-500/15 text-emerald-500' },
  { value: 'paused', label: 'Paused', tone: 'bg-sky-500/15 text-sky-500' },
  { value: 'archived', label: 'Archived', tone: 'bg-surface-2 text-muted' },
];

@Component({
  selector: 'app-chatbots-list',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    DatePipe,
    ConfirmDialogComponent,
    ChatbotCreateModalComponent,
  ],
  templateUrl: './chatbots-list.page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatbotsListPageComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);

  readonly statusFilters = STATUS_FILTERS;

  readonly loading = signal<boolean>(true);
  readonly error = signal<string | null>(null);
  readonly rows = signal<ChatbotListItem[]>([]);
  readonly search = signal<string>('');
  readonly selectedStatus = signal<'' | ChatbotStatus>('');
  readonly actionsMenuFor = signal<string | null>(null);
  /** Which row's mutation is in flight — disables the kebab affordances
   *  so operators can't double-fire publish / pause / archive. */
  readonly actionInFlight = signal<string | null>(null);

  readonly createModalOpen = signal<boolean>(false);
  readonly createSubmitting = signal<boolean>(false);
  readonly createError = signal<string | null>(null);

  readonly archiveTarget = signal<ChatbotListItem | null>(null);
  readonly archiveSubmitting = signal<boolean>(false);
  readonly archiveError = signal<string | null>(null);

  // Permission gates. Aligned with the backend keys documented in
  // chatbots-api.service.ts / chatbots/permissions.py:
  //   chatbots.view    → land on this page (route guard)
  //   chatbots.edit    → create / patch / pause / import
  //   chatbots.publish → publish / rollback
  //   chatbots.delete  → archive
  readonly canEdit = computed(() => this.auth.currentPermissions().includes('chatbots.edit'));
  readonly canPublish = computed(() => this.auth.currentPermissions().includes('chatbots.publish'));
  readonly canDelete = computed(() => this.auth.currentPermissions().includes('chatbots.delete'));

  readonly filteredRows = computed(() => {
    const term = this.search().trim().toLowerCase();
    if (!term) return this.rows();
    return this.rows().filter((r) => r.name.toLowerCase().includes(term));
  });

  readonly hasRows = computed(() => this.filteredRows().length > 0);
  /** Org has zero rows AND no active filter/search → show the big
   *  "create your first bot" empty state. */
  readonly emptyState = computed(
    () =>
      !this.loading() &&
      this.rows().length === 0 &&
      this.selectedStatus() === '' &&
      !this.search().trim(),
  );
  /** Org has rows but the current filter/search produced nothing —
   *  show a smaller "no matches" panel, NOT the empty-org CTA. */
  readonly filteredEmpty = computed(() => !this.loading() && !this.hasRows() && !this.emptyState());

  constructor() {
    // Reactive refetch on status change. skip(1) drops toObservable's
    // initial replay so we don't double-fetch — reload() below owns the
    // first load. switchMap cancels stale in-flight requests so rapid
    // pill-clicking always paints the latest server state. Search stays
    // client-side (already client-filtered from the loaded page).
    toObservable(this.selectedStatus)
      .pipe(
        skip(1),
        debounceTime(200),
        distinctUntilChanged(),
        tap(() => {
          this.loading.set(true);
          this.error.set(null);
        }),
        switchMap((status) =>
          this.api.list({ status: status || undefined, limit: PAGE_SIZE, offset: 0 }),
        ),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Failed to load chat bots.');
          this.loading.set(false);
        },
      });
    this.reload(this.selectedStatus());
  }

  private reload(status: '' | ChatbotStatus): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .list({ status: status || undefined, limit: PAGE_SIZE, offset: 0 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.rows.set(rows);
          this.loading.set(false);
        },
        error: (err) => {
          this.error.set(extractApiError(err) ?? 'Failed to load chat bots.');
          this.loading.set(false);
        },
      });
  }

  openCreateModal(): void {
    this.createError.set(null);
    this.createModalOpen.set(true);
  }

  closeCreateModal(): void {
    if (this.createSubmitting()) return;
    this.createModalOpen.set(false);
  }

  submitCreateBot(payload: { name: string; description: string | null }): void {
    const name = payload.name.trim();
    if (!name) return;
    this.createSubmitting.set(true);
    this.createError.set(null);
    this.api
      .create({ name, description: payload.description, category: 'Custom' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (created) => {
          this.createSubmitting.set(false);
          this.createModalOpen.set(false);
          this.router.navigate(['/user/chatbots', created.id, 'edit']);
        },
        error: (err) => {
          this.createError.set(extractApiError(err) ?? 'Failed to create bot.');
          this.createSubmitting.set(false);
        },
      });
  }

  publish(row: ChatbotListItem): void {
    if (!this.canPublish() || this.actionInFlight()) return;
    this.actionsMenuFor.set(null);
    this.actionInFlight.set(row.id);
    this.api
      .publish(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.actionInFlight.set(null);
          // Patch the row in place — a full reload would flash a page
          // skeleton for a single-row status change and, on a filtered
          // view, snap the row out from under the operator mid-click.
          this.rows.update((rows) =>
            rows.map((r) => (r.id === row.id ? { ...r, status: updated.status } : r)),
          );
        },
        error: (err) => {
          this.actionInFlight.set(null);
          this.error.set(extractApiError(err) ?? 'Publish failed.');
        },
      });
  }

  pause(row: ChatbotListItem): void {
    if (!this.canEdit() || this.actionInFlight()) return;
    this.actionsMenuFor.set(null);
    this.actionInFlight.set(row.id);
    this.api
      .pause(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.actionInFlight.set(null);
          this.rows.update((rows) =>
            rows.map((r) => (r.id === row.id ? { ...r, status: updated.status } : r)),
          );
        },
        error: (err) => {
          this.actionInFlight.set(null);
          this.error.set(extractApiError(err) ?? 'Pause failed.');
        },
      });
  }

  archive(row: ChatbotListItem): void {
    if (!this.canDelete() || this.actionInFlight()) return;
    this.actionsMenuFor.set(null);
    this.archiveError.set(null);
    this.archiveTarget.set(row);
  }

  cancelArchive(): void {
    if (this.archiveSubmitting()) return;
    this.archiveTarget.set(null);
  }

  confirmArchive(): void {
    const row = this.archiveTarget();
    if (!row) return;
    this.archiveSubmitting.set(true);
    this.archiveError.set(null);
    this.api
      .archive(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.archiveSubmitting.set(false);
          this.archiveTarget.set(null);
          // Patch in place; if the operator is filtered to a non-archived
          // status the row falls off the next reactive refetch anyway.
          this.rows.update((rows) =>
            rows.map((r) => (r.id === row.id ? { ...r, status: 'archived' as ChatbotStatus } : r)),
          );
        },
        error: (err) => {
          this.archiveError.set(extractApiError(err) ?? 'Archive failed.');
          this.archiveSubmitting.set(false);
        },
      });
  }

  /** Step 15 — download a portable export of the bot as JSON. */
  exportBot(row: ChatbotListItem): void {
    this.actionsMenuFor.set(null);
    this.api
      .export(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (envelope) => {
          const blob = new Blob([JSON.stringify(envelope, null, 2)], {
            type: 'application/json',
          });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `${row.name.replace(/[^a-z0-9]+/gi, '_')}.chatbot.json`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        },
        error: (err) => this.error.set(extractApiError(err) ?? 'Export failed.'),
      });
  }

  /** Step 15 — file picker → parse → POST to /import. */
  onImportFile(evt: Event): void {
    const input = evt.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    file
      .text()
      .then((text) => {
        let envelope: unknown;
        try {
          envelope = JSON.parse(text);
        } catch {
          this.error.set('Selected file is not valid JSON.');
          return;
        }
        this.api
          .import({ envelope: envelope as never, name_override: null })
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: (result) => {
              if (result.conflicts.length) {
                const msg = result.conflicts.map((c) => `${c.kind}: ${c.detail}`).join(' · ');
                this.error.set(`Imported with conflicts: ${msg}`);
              }
              this.router.navigate(['/user/chatbots', result.created_bot_id, 'edit']);
            },
            error: (err) => this.error.set(extractApiError(err) ?? 'Import failed.'),
          });
      })
      .finally(() => {
        input.value = ''; // reset picker so the same file can be re-selected
      });
  }

  toggleActionsMenu(botId: string, event: MouseEvent): void {
    event.stopPropagation();
    this.actionsMenuFor.update((cur) => (cur === botId ? null : botId));
  }

  closeKebab(): void {
    this.actionsMenuFor.set(null);
  }

  triggerSummary(row: ChatbotListItem): string {
    const cfg = row.trigger_config;
    if (cfg.mode === 'keyword') {
      const count = cfg.keywords?.length ?? 0;
      return count === 0 ? 'No keywords set' : `${count} keyword${count === 1 ? '' : 's'}`;
    }
    if (cfg.mode === 'regex') {
      return cfg.regex_pattern ? 'Regex pattern' : 'Regex (not configured)';
    }
    return 'Any message';
  }

  statusTone(status: ChatbotStatus): string {
    const match = STATUS_FILTERS.find((f) => f.value === status);
    return match?.tone ?? 'bg-surface-2 text-default';
  }
}
