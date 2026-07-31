import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';
import { dashboardRange, type DashboardRange } from '../shared/dashboard-range.signal';

interface FunnelStageBucket {
  stage_id: string;
  stage_name: string;
  stage_order: number;
  count: number;
  value_sum: number;
}

interface DashboardFunnelResponse {
  range: DashboardRange;
  scope: 'org' | 'personal';
  total_leads_in_range: number;
  stages: FunnelStageBucket[];
  won_count: number;
  lost_count: number;
}

/**
 * AIXO "Deal pipeline" signature strip — a hero card at the top of the
 * dashboard that summarises every active pipeline stage in one horizontal
 * row. Reuses the existing `/dashboard/funnel` endpoint (extended in Step
 * … to include per-stage `value_sum`) so no duplicate query is issued.
 *
 * Stage dots cycle through five accent-varied hues so a New / Contacted /
 * Qualified / Proposal / Won pipeline renders with distinct colours even
 * on custom pipelines with different stage names.
 *
 * The gradient overlay (`accent-soft → transparent 55%`) matches AIXO's
 * signature card and lets the card sit on top of the plain surface
 * without needing its own border-only chrome.
 */
@Component({
  selector: 'app-deal-pipeline-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  templateUrl: './deal-pipeline-strip.component.html',
})
export class DealPipelineStripComponent {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);

  /** Monotonic tick from the dashboard page's Refresh button. Same
   *  shape as the funnel/trend widgets — flipping it re-fires the
   *  effect and re-runs `load`, even if `dashboardRange` is unchanged. */
  readonly refreshTick = input<number>(0);

  protected readonly data = signal<DashboardFunnelResponse | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadedAt = signal<Date | null>(null);

  /** "updated Xm ago" mono text on the strip header — refreshed via
   *  the parent's `refreshTick` and by the internal effect. */
  protected readonly agoLabel = signal<string>('just now');

  /** Deterministic dot colour per stage index. Five hues cycled so a
   *  many-stage custom pipeline still renders distinct colours. */
  private readonly STAGE_DOTS: string[] = [
    '#4F46E5', // indigo (accent default)
    '#0EA5E9', // sky
    '#8B5CF6', // violet
    '#F59E0B', // amber
    '#10B981', // emerald
    '#EF4444', // red
  ];

  protected readonly stageCards = computed(() => {
    const d = this.data();
    if (!d) return [];
    return d.stages.map((s, i) => ({
      ...s,
      dot: this.STAGE_DOTS[i % this.STAGE_DOTS.length],
    }));
  });

  /** Client-side sum ceiling so per-stage progress bars scale to the
   *  largest count in the set instead of the absolute lead total. */
  protected readonly maxCount = computed(() => {
    const d = this.data();
    if (!d || d.stages.length === 0) return 1;
    return Math.max(1, ...d.stages.map((s) => s.count));
  });

  constructor() {
    effect(() => {
      const r = dashboardRange();
      this.refreshTick();
      this.load(r);
    });
    // Refresh the "Xm ago" label once a minute so it stays truthful
    // without paying for a re-fetch. Cleared automatically when the
    // component is destroyed.
    const timer = setInterval(() => this.recomputeAgoLabel(), 60_000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected formatCurrency(value: number): string {
    if (!value) return '$0';
    try {
      const abs = Math.abs(value);
      if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
      if (abs >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
      return `$${value.toFixed(0)}`;
    } catch {
      return `$${value}`;
    }
  }

  private recomputeAgoLabel(): void {
    const t = this.loadedAt();
    if (!t) return;
    const diff = Math.floor((Date.now() - t.getTime()) / 60_000);
    if (diff < 1) this.agoLabel.set('just now');
    else if (diff === 1) this.agoLabel.set('1m ago');
    else if (diff < 60) this.agoLabel.set(`${diff}m ago`);
    else this.agoLabel.set(`${Math.floor(diff / 60)}h ago`);
  }

  private load(range: DashboardRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.http
      .get<DashboardFunnelResponse>(`${environment.apiBaseUrl}/dashboard/funnel`, {
        params: { range },
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.data.set(res);
          this.loadedAt.set(new Date());
          this.recomputeAgoLabel();
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? "Couldn't load pipeline.");
          this.loading.set(false);
        },
      });
  }
}
