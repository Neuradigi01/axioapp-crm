import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import {
  Chart,
  BarController,
  BarElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  ChartConfiguration,
} from 'chart.js';
import { BaseChartDirective } from 'ng2-charts';

import { extractApiError } from '@core/services/api-error.util';
import {
  EmbedApiService,
  EmbedSubmissionListResponse,
  EmbedSubmissionOutcome,
  EmbedSubmissionRead,
  EmbedSubmissionSummary,
} from './embed-api.service';


// Tree-shaking-friendly Chart.js registration (matches the calls-
// analytics tab's pattern).
Chart.register(
  BarElement,
  BarController,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
);


type RangePreset = '24h' | '7d' | '30d';

interface OutcomeBadge {
  label: string;
  cls: string;
}


/**
 * Submission log sub-tab. Three stacked sections drive Owner/Admin
 * operational visibility for the embed widget:
 *
 *   1. **Counts card** — 4 cells (Accepted / Spam / Rate-limited /
 *      Errors) for the current range.
 *   2. **Stacked bar chart** — per-day, last 30 days (regardless of
 *      the table range), so trend visibility doesn't depend on which
 *      filter is active.
 *   3. **Paginated table** — outcome filter + range preset + page
 *      controls. Accepted rows surface a "View lead" router link.
 *
 * Time-range presets (24h / 7d / 30d) drive BOTH the table query and
 * the counts card. The chart stays at 30 days to give consistent
 * trend context regardless of the active filter.
 */
@Component({
  selector: 'app-embed-submission-log',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [BaseChartDirective, RouterLink],
  templateUrl: './submission-log.component.html',
})
export class SubmissionLogComponent {
  private readonly api = inject(EmbedApiService);
  private readonly destroyRef = inject(DestroyRef);

  // --- Filters ---------------------------------------------------------
  protected readonly outcomeFilter = signal<EmbedSubmissionOutcome | null>(
    null,
  );
  protected readonly rangePreset = signal<RangePreset>('7d');
  protected readonly page = signal(1);
  protected readonly pageSize = 25;

  // Static filter chip options. Held as component fields (not inline
  // template arrays) so Angular's strict-template type-checker can
  // narrow the literal types into `setOutcome`/`setRange`.
  protected readonly outcomeOptions: ReadonlyArray<{
    value: EmbedSubmissionOutcome | null;
    label: string;
  }> = [
    { value: null, label: 'All' },
    { value: 'accepted', label: 'Accepted' },
    { value: 'rejected_spam', label: 'Spam' },
    { value: 'rate_limited', label: 'Rate-limited' },
    { value: 'invalid_payload', label: 'Errors' },
  ];

  protected readonly rangeOptions: ReadonlyArray<RangePreset> = [
    '24h',
    '7d',
    '30d',
  ];

  // --- Server-fetched state -------------------------------------------
  protected readonly listLoading = signal(false);
  protected readonly listError = signal<string | null>(null);
  protected readonly listResponse = signal<EmbedSubmissionListResponse | null>(
    null,
  );

  protected readonly summaryLoading = signal(false);
  protected readonly summaryError = signal<string | null>(null);
  protected readonly summary = signal<EmbedSubmissionSummary | null>(null);

  // --- Derived state --------------------------------------------------

  protected readonly totalPages = computed<number>(() => {
    const resp = this.listResponse();
    if (!resp) return 1;
    return Math.max(1, Math.ceil(resp.total / resp.page_size));
  });

  /** Stacked-bar chart data — one bar per day, four series per outcome. */
  protected readonly chartData = computed<ChartConfiguration<'bar'>['data']>(
    () => {
      const s = this.summary();
      if (!s) return { labels: [], datasets: [] };
      return {
        labels: s.by_day.map((b) => b.day.slice(5)), // "05-22"
        datasets: [
          {
            label: 'Accepted',
            backgroundColor: '#10b981',
            data: s.by_day.map((b) => b.accepted),
          },
          {
            label: 'Spam',
            backgroundColor: '#f97316',
            data: s.by_day.map((b) => b.rejected_spam),
          },
          {
            label: 'Rate-limited',
            backgroundColor: '#f59e0b',
            data: s.by_day.map((b) => b.rate_limited),
          },
          {
            label: 'Errors',
            backgroundColor: '#ef4444',
            data: s.by_day.map((b) => b.invalid_payload),
          },
        ],
      };
    },
  );

  protected readonly chartOptions: ChartConfiguration<'bar'>['options'] = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { position: 'bottom', labels: { boxWidth: 10 } },
    },
    scales: {
      x: { stacked: true, ticks: { font: { size: 10 } } },
      y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
    },
  };

  constructor() {
    // Re-fetch the list whenever a filter or the page changes.
    effect(() => {
      // Track these so the effect re-runs on change.
      this.outcomeFilter();
      this.rangePreset();
      this.page();
      this.reloadList();
    });
    // Summary always reflects the last 30 days; load once at mount.
    this.reloadSummary();
  }

  // --- Handlers --------------------------------------------------------

  protected setOutcome(value: EmbedSubmissionOutcome | null): void {
    this.outcomeFilter.set(value);
    this.page.set(1);
  }

  protected setRange(preset: RangePreset): void {
    this.rangePreset.set(preset);
    this.page.set(1);
  }

  protected nextPage(): void {
    if (this.page() < this.totalPages()) this.page.update((p) => p + 1);
  }

  protected prevPage(): void {
    if (this.page() > 1) this.page.update((p) => p - 1);
  }

  protected refresh(): void {
    this.reloadList();
    this.reloadSummary();
  }

  // --- Fetchers --------------------------------------------------------

  private reloadList(): void {
    this.listLoading.set(true);
    this.listError.set(null);
    const range = this.computeRange(this.rangePreset());
    this.api
      .listSubmissions({
        outcome: this.outcomeFilter() ?? undefined,
        from: range.from,
        to: range.to,
        page: this.page(),
        page_size: this.pageSize,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.listResponse.set(resp);
          this.listLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.listLoading.set(false);
          this.listError.set(
            extractApiError(err) ?? 'Could not load submission log.',
          );
        },
      });
  }

  private reloadSummary(): void {
    this.summaryLoading.set(true);
    this.summaryError.set(null);
    const range = this.computeRange('30d');
    this.api
      .getSubmissionSummary(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.summary.set(resp);
          this.summaryLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.summaryLoading.set(false);
          this.summaryError.set(
            extractApiError(err) ?? 'Could not load summary.',
          );
        },
      });
  }

  // --- Helpers ---------------------------------------------------------

  private computeRange(preset: RangePreset): { from: string; to: string } {
    const to = new Date();
    const from = new Date();
    const days = preset === '24h' ? 1 : preset === '7d' ? 7 : 30;
    from.setUTCDate(from.getUTCDate() - days);
    return { from: from.toISOString(), to: to.toISOString() };
  }

  protected outcomeBadge(outcome: EmbedSubmissionOutcome): OutcomeBadge {
    switch (outcome) {
      case 'accepted':
        return {
          label: 'Accepted',
          cls: 'bg-emerald-100 text-emerald-700 ring-emerald-200',
        };
      case 'rejected_spam':
        return {
          label: 'Spam',
          cls: 'bg-orange-100 text-orange-700 ring-orange-200',
        };
      case 'rate_limited':
        return {
          label: 'Rate-limited',
          cls: 'bg-amber-100 text-amber-700 ring-amber-200',
        };
      case 'invalid_payload':
        return {
          label: 'Error',
          cls: 'bg-red-100 text-red-700 ring-red-200',
        };
    }
  }

  /** Strip protocol + path → just the hostname for the table cell. */
  protected hostOf(url: string | null): string {
    if (!url) return '—';
    try {
      return new URL(url).hostname;
    } catch {
      return url.length > 32 ? url.slice(0, 32) + '…' : url;
    }
  }

  protected relativeTime(iso: string | null): string {
    if (!iso) return '—';
    const ms = Date.now() - new Date(iso).getTime();
    const minutes = Math.floor(ms / 60_000);
    if (minutes < 1) return 'just now';
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }

  /** Cell-level helper for the "Submitted" column tooltip. */
  protected formatAbsolute(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  /** Quick-count helper for the counts card. */
  protected countOf(
    summary: EmbedSubmissionSummary,
    outcome: EmbedSubmissionOutcome,
  ): number {
    return summary.by_outcome[outcome] ?? 0;
  }

  /** Type-narrowing helper so the template can pass into `submissionTrackBy`. */
  protected trackById = (_: number, item: EmbedSubmissionRead): string =>
    item.id;
}
