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
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import {
  AutomationRunStatus,
  AutomationsApiService,
  RunRead,
  TriggerRead,
} from '../automations-api.service';
import { RetryModalComponent } from './retry.modal';

/**
 * Run-history page — `/user/automations/:id/runs`.
 *
 * Per-trigger table of past fires. Each row carries the run's
 * status, scheduled_at, channel_message_id (when sent), and error
 * (when failed). Click a row to expand the full event_payload JSON
 * + the resolved recipient. Failed rows show a Retry button that
 * pops a confirmation modal.
 *
 * Filters: status + since (last 24h / 7d / 30d / all). Pagination
 * at 50 per page.
 */

const PAGE_SIZE = 50;

const STATUS_OPTIONS: Array<{ value: '' | AutomationRunStatus; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'queued', label: 'Queued' },
  { value: 'dispatched', label: 'Dispatched' },
  { value: 'sent', label: 'Sent' },
  { value: 'failed', label: 'Failed' },
  { value: 'skipped', label: 'Skipped' },
];

const SINCE_OPTIONS: Array<{ value: '' | '24h' | '7d' | '30d'; label: string }> = [
  { value: '', label: 'All time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

const STATUS_PALETTE: Record<AutomationRunStatus, string> = {
  queued: 'bg-surface-2 text-default border-subtle',
  dispatched: 'bg-blue-50 text-blue-700 ring-blue-200',
  sent: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  failed: 'bg-rose-50 text-rose-700 ring-rose-200',
  skipped: 'bg-amber-50 text-amber-700 ring-amber-200',
};

@Component({
  selector: 'app-run-history-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    DatePipe,
    LucideAngularModule,
    RetryModalComponent,
  ],
  templateUrl: './run-history.page.html',
})
export class RunHistoryPageComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly STATUS_OPTIONS = STATUS_OPTIONS;
  protected readonly SINCE_OPTIONS = SINCE_OPTIONS;
  protected readonly STATUS_PALETTE = STATUS_PALETTE;
  protected readonly PAGE_SIZE = PAGE_SIZE;

  protected readonly trigger = signal<TriggerRead | null>(null);
  protected readonly items = signal<RunRead[]>([]);
  protected readonly total = signal<number>(0);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pageIndex = signal<number>(0);

  protected readonly statusFilter = signal<'' | AutomationRunStatus>('');
  protected readonly sinceFilter = signal<'' | '24h' | '7d' | '30d'>('');

  protected readonly expandedId = signal<string | null>(null);
  protected readonly retryTarget = signal<RunRead | null>(null);

  protected readonly canWrite = computed(() => this.auth.hasPermission('automations.write'));

  protected readonly triggerId = signal<string | null>(null);

  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PAGE_SIZE)));
  protected readonly hasPrev = computed(() => this.pageIndex() > 0);
  protected readonly hasNext = computed(() => this.pageIndex() < this.totalPages() - 1);

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) {
        this.triggerId.set(id);
        this.loadTrigger(id);
      }
    });

    effect(() => {
      const id = this.triggerId();
      const status = this.statusFilter();
      const since = this.sinceFilter();
      const page = this.pageIndex();
      void status;
      void since;
      void page;
      if (id) this.reload(id);
    });
  }

  private loadTrigger(id: string): void {
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (t) => this.trigger.set(t),
        error: () => this.trigger.set(null),
      });
  }

  private reload(triggerId: string): void {
    this.loading.set(true);
    this.loadError.set(null);
    const offset = this.pageIndex() * PAGE_SIZE;
    this.api
      .listRuns(triggerId, {
        status: this.statusFilter() || undefined,
        since: this.computeSinceIso() || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.items.set(res.items);
          this.total.set(res.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.items.set([]);
          this.total.set(0);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load runs.');
        },
      });
  }

  private computeSinceIso(): string | null {
    const v = this.sinceFilter();
    if (!v) return null;
    const now = new Date();
    const millis: Record<typeof v, number> = {
      '': 0,
      '24h': 24 * 3600 * 1000,
      '7d': 7 * 24 * 3600 * 1000,
      '30d': 30 * 24 * 3600 * 1000,
    } as never;
    return new Date(now.getTime() - millis[v]).toISOString();
  }

  protected onStatusChange(value: string): void {
    this.statusFilter.set(value as '' | AutomationRunStatus);
    this.pageIndex.set(0);
  }

  protected onSinceChange(value: string): void {
    this.sinceFilter.set(value as '' | '24h' | '7d' | '30d');
    this.pageIndex.set(0);
  }

  protected prevPage(): void {
    if (this.hasPrev()) this.pageIndex.update((p) => p - 1);
  }

  protected nextPage(): void {
    if (this.hasNext()) this.pageIndex.update((p) => p + 1);
  }

  protected toggleExpanded(id: string): void {
    this.expandedId.update((cur) => (cur === id ? null : id));
  }

  protected openRetry(row: RunRead): void {
    if (!this.canWrite()) return;
    this.retryTarget.set(row);
  }

  protected closeRetry(): void {
    this.retryTarget.set(null);
  }

  protected onRetried(updated: RunRead): void {
    // Optimistic patch — the deliver_run task will flip status to
    // sent/failed once it re-runs.
    this.items.update((rows) => rows.map((r) => (r.id === updated.id ? updated : r)));
    this.retryTarget.set(null);
  }

  protected payloadJson(row: RunRead): string {
    try {
      return JSON.stringify(row.event_payload, null, 2);
    } catch {
      return String(row.event_payload);
    }
  }

  protected trackById = (_: number, row: RunRead) => row.id;
}
