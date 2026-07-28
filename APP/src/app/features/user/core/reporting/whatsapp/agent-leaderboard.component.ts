import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import {
  LeaderboardReport,
  ReportRange,
  WhatsAppReportsService,
  formatDuration,
} from './whatsapp-reports.service';

type SortKey = 'median' | 'replies' | 'conversations' | 'p95' | 'name';

/**
 * Agent leaderboard (Step 20).
 *
 * Per-agent reply count, conversations handled, median + p95
 * response time. Click a row → conversations inbox filtered to that
 * agent. Default sort: fastest median first.
 *
 * AI-only conversations don't surface here (server filters
 * `sender_user_id IS NOT NULL`). Mixed conversations attribute the
 * reply count to whichever human user posted them.
 */
@Component({
  selector: 'app-wa-agent-leaderboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-subtle bg-surface p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">Agent leaderboard</p>
          <p class="text-[11px] text-muted">Who's responding fastest. AI replies excluded.</p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-muted">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        @if (r.rows.length === 0) {
          <p class="py-8 text-center text-xs text-muted">
            No human-replied conversations in this window.
          </p>
        } @else {
          <table class="w-full text-xs">
            <thead class="text-muted">
              <tr class="border-b border-subtle">
                <th class="py-1 text-left font-medium">#</th>
                <th
                  class="cursor-pointer py-1 text-left font-medium hover:text-default"
                  (click)="setSort('name')"
                >
                  Agent {{ sortMarker('name') }}
                </th>
                <th
                  class="cursor-pointer py-1 text-right font-medium hover:text-default"
                  (click)="setSort('replies')"
                >
                  Replies {{ sortMarker('replies') }}
                </th>
                <th
                  class="cursor-pointer py-1 text-right font-medium hover:text-default"
                  (click)="setSort('conversations')"
                >
                  Conversations {{ sortMarker('conversations') }}
                </th>
                <th
                  class="cursor-pointer py-1 text-right font-medium hover:text-default"
                  (click)="setSort('median')"
                >
                  Median {{ sortMarker('median') }}
                </th>
                <th
                  class="cursor-pointer py-1 text-right font-medium hover:text-default"
                  (click)="setSort('p95')"
                >
                  p95 {{ sortMarker('p95') }}
                </th>
              </tr>
            </thead>
            <tbody>
              @for (row of sortedRows(); track row.user_id; let i = $index) {
                <tr
                  class="cursor-pointer border-b border-subtle last:border-0 hover:bg-surface-2"
                  (click)="onRowClick(row.user_id)"
                >
                  <td class="py-1.5 text-muted">{{ i + 1 }}</td>
                  <td class="py-1.5 text-default">{{ row.name }}</td>
                  <td class="py-1.5 text-right text-default">{{ row.replies }}</td>
                  <td class="py-1.5 text-right text-default">
                    {{ row.conversations_handled }}
                  </td>
                  <td class="py-1.5 text-right text-default">
                    {{ formatDuration(row.median_response_seconds) }}
                  </td>
                  <td class="py-1.5 text-right text-default">
                    {{ formatDuration(row.p95_response_seconds) }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        }
      }
    </div>
  `,
})
export class AgentLeaderboardComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);

  readonly range = input.required<ReportRange>();

  protected readonly formatDuration = formatDuration;

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<LeaderboardReport | null>(null);

  protected readonly sortKey = signal<SortKey>('median');
  protected readonly sortAsc = signal<boolean>(true);

  protected setSort(key: SortKey): void {
    if (this.sortKey() === key) {
      this.sortAsc.set(!this.sortAsc());
    } else {
      this.sortKey.set(key);
      this.sortAsc.set(true);
    }
  }

  protected sortMarker(key: SortKey): string {
    if (this.sortKey() !== key) return '';
    return this.sortAsc() ? '▲' : '▼';
  }

  protected sortedRows(): LeaderboardReport['rows'] {
    const r = this.report();
    if (!r) return [];
    const key = this.sortKey();
    const asc = this.sortAsc();
    const sorted = [...r.rows].sort((a, b) => {
      const av = this.sortField(a, key);
      const bv = this.sortField(b, key);
      if (av === bv) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return av < bv ? -1 : 1;
    });
    return asc ? sorted : sorted.reverse();
  }

  private sortField(row: LeaderboardReport['rows'][number], key: SortKey): number | string | null {
    switch (key) {
      case 'name':
        return row.name.toLowerCase();
      case 'replies':
        return row.replies;
      case 'conversations':
        return row.conversations_handled;
      case 'median':
        return row.median_response_seconds;
      case 'p95':
        return row.p95_response_seconds;
    }
  }

  protected onRowClick(userId: string): void {
    this.router.navigate(['/user/conversations'], {
      queryParams: { assigned_to: userId, channel: 'whatsapp' },
    });
  }

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getAgentLeaderboard(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load agent leaderboard.');
        },
      });
  }
}
