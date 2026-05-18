import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { extractApiError } from '@core/services/api-error.util';

import {
  Campaign,
  CampaignMessage,
  CampaignMessageStatus,
  CampaignStats,
  CampaignsApiService,
} from './campaigns-api.service';

const POLL_INTERVAL_MS = 5_000;

/**
 * Campaign detail â€” stats KPIs + per-message table with retry.
 *
 * Polls stats + messages every 5s while the campaign is `scheduled`
 * or `running` so the operator sees the dispatch progress without
 * refreshing. Polling stops once status flips to `done` / `failed`.
 */
@Component({
  selector: 'app-campaign-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './campaign-detail.page.html',
})
export class CampaignDetailPageComponent {
  private readonly api = inject(CampaignsApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly id: string =
    this.route.snapshot.paramMap.get('id') ?? '';

  protected readonly campaign = signal<Campaign | null>(null);
  protected readonly stats = signal<CampaignStats | null>(null);
  protected readonly messages = signal<CampaignMessage[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly retryingId = signal<string | null>(null);

  protected readonly statusBadge = computed(() => {
    const c = this.campaign();
    if (!c) return null;
    const map: Record<string, { label: string; cls: string }> = {
      draft: { label: 'Draft', cls: 'bg-zinc-100 text-zinc-700 ring-zinc-200' },
      scheduled: { label: 'Scheduled', cls: 'bg-amber-50 text-amber-700 ring-amber-200' },
      running: { label: 'Running', cls: 'bg-sky-50 text-sky-700 ring-sky-200' },
      done: { label: 'Done', cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
      failed: { label: 'Failed', cls: 'bg-rose-50 text-rose-700 ring-rose-200' },
    };
    return map[c.status];
  });

  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    if (!this.id) {
      this.loadError.set('No campaign id in URL.');
      return;
    }
    this.loadAll();
    // Tear the poll down on destroy â€” DestroyRef â†’ cleanup callback.
    this.destroyRef.onDestroy(() => this.stopPolling());
  }

  protected loadAll(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .get(this.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.campaign.set(c);
          this.maybeStartPolling();
        },
        error: (err: HttpErrorResponse) =>
          this.loadError.set(extractApiError(err) ?? 'Could not load campaign.'),
      });
    this.refreshStatsAndMessages();
  }

  protected refreshStatsAndMessages(): void {
    this.api
      .stats(this.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (s) => {
          this.stats.set(s);
          // Stop polling if the campaign reached a terminal state.
          if (s.status === 'done' || s.status === 'failed') {
            this.stopPolling();
          }
        },
        error: () => {
          /* keep last stats */
        },
      });
    this.api
      .listMessages(this.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.messages.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load messages.',
          );
        },
      });
  }

  protected retry(msg: CampaignMessage): void {
    this.retryingId.set(msg.id);
    this.api
      .retry(this.id, msg.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.retryingId.set(null);
          this.refreshStatsAndMessages();
        },
        error: (err: HttpErrorResponse) => {
          this.retryingId.set(null);
          this.loadError.set(
            extractApiError(err) ?? 'Could not retry message.',
          );
        },
      });
  }

  protected messageStatusCls(s: CampaignMessageStatus): string {
    switch (s) {
      case 'sent':
      case 'delivered':
      case 'read':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'queued':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      case 'failed':
        return 'bg-rose-50 text-rose-700 ring-rose-200';
    }
  }

  protected formatDate(iso: string | null): string {
    if (!iso) return 'â€”';
    return new Date(iso).toLocaleString();
  }

  protected shortId(id: string): string {
    return id.slice(0, 8);
  }

  private maybeStartPolling(): void {
    const c = this.campaign();
    if (!c) return;
    if (c.status === 'scheduled' || c.status === 'running') {
      if (this.pollTimer !== null) return;
      this.pollTimer = setInterval(
        () => this.refreshStatsAndMessages(),
        POLL_INTERVAL_MS,
      );
    } else {
      this.stopPolling();
    }
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

}
