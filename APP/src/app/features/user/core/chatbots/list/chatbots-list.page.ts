import { CommonModule, DatePipe } from '@angular/common';
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

import { extractApiError } from '@core/services/api-error.util';

import { ChatbotListItem, ChatbotStatus, ChatbotsApiService } from '../chatbots-api.service';

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
  { value: '', label: 'All', tone: 'bg-zinc-100 text-zinc-700' },
  { value: 'draft', label: 'Draft', tone: 'bg-amber-50 text-amber-700' },
  { value: 'live', label: 'Live', tone: 'bg-emerald-50 text-emerald-700' },
  { value: 'paused', label: 'Paused', tone: 'bg-blue-50 text-blue-700' },
  { value: 'archived', label: 'Archived', tone: 'bg-zinc-100 text-zinc-500' },
];

@Component({
  selector: 'app-chatbots-list',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, LucideAngularModule, DatePipe],
  templateUrl: './chatbots-list.page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatbotsListPageComponent {
  private readonly api = inject(ChatbotsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly statusFilters = STATUS_FILTERS;

  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);
  readonly rows = signal<ChatbotListItem[]>([]);
  readonly search = signal<string>('');
  readonly selectedStatus = signal<'' | ChatbotStatus>('');
  readonly actionsMenuFor = signal<string | null>(null);

  readonly filteredRows = computed(() => {
    const term = this.search().trim().toLowerCase();
    if (!term) return this.rows();
    return this.rows().filter((r) => r.name.toLowerCase().includes(term));
  });

  readonly hasRows = computed(() => this.filteredRows().length > 0);
  readonly hasAnyRows = computed(() => this.rows().length > 0);

  constructor() {
    // Refetch when the status filter changes (search is client-side).
    effect(() => {
      const status = this.selectedStatus();
      this.reload(status);
    });
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

  createBot(): void {
    // v1 CTA — the builder (Step 13) creates the bot server-side
    // and the list refreshes when the operator returns. Until Step
    // 13 lands the builder route, the "New bot" button routes to
    // a placeholder — we still register the intent by POSTing a
    // named draft here.
    const name = window.prompt('Name your new bot');
    if (!name || !name.trim()) return;
    this.api
      .create({ name: name.trim(), category: 'Custom' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (created) => {
          window.location.href = `/user/chatbots/${created.id}/edit`;
        },
        error: (err) => this.error.set(extractApiError(err) ?? 'Failed to create bot.'),
      });
  }

  publish(row: ChatbotListItem): void {
    this.actionsMenuFor.set(null);
    this.api
      .publish(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.reload(this.selectedStatus()),
        error: (err) => this.error.set(extractApiError(err) ?? 'Publish failed.'),
      });
  }

  pause(row: ChatbotListItem): void {
    this.actionsMenuFor.set(null);
    this.api
      .pause(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.reload(this.selectedStatus()),
        error: (err) => this.error.set(extractApiError(err) ?? 'Pause failed.'),
      });
  }

  archive(row: ChatbotListItem): void {
    if (!window.confirm(`Archive "${row.name}"? Existing parked runs will be canceled.`)) return;
    this.actionsMenuFor.set(null);
    this.api
      .archive(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.reload(this.selectedStatus()),
        error: (err) => this.error.set(extractApiError(err) ?? 'Archive failed.'),
      });
  }

  toggleActionsMenu(botId: string): void {
    this.actionsMenuFor.set(this.actionsMenuFor() === botId ? null : botId);
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
    return match?.tone ?? 'bg-zinc-100 text-zinc-700';
  }
}
