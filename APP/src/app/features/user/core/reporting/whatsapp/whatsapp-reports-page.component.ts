import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  signal,
} from '@angular/core';

import { AdRoiWidgetComponent } from './ad-roi-widget.component';
import { AgentLeaderboardComponent } from './agent-leaderboard.component';
import { AIMetricsWidgetComponent } from './ai-metrics-widget.component';
import { CostWidgetComponent } from './cost-widget.component';
import { OutcomesWidgetComponent } from './outcomes-widget.component';
import { QualityTimelineComponent } from './quality-timeline.component';
import { ResponseTimeWidgetComponent } from './response-time-widget.component';
import { VolumeWidgetComponent } from './volume-widget.component';
import {
  ReportGranularity,
  ReportRange,
} from './whatsapp-reports.service';

/**
 * WhatsApp Reports page (whatsapp-platform-upgrade Step 20).
 *
 * Manager-facing dashboard with four widgets:
 *
 *   1. Volume — sent / received / failed / AI traffic over time.
 *   2. Response time — first-staff-reply latency + histogram + per-agent.
 *   3. Outcomes — status mix + tag breakdown with inbox drilldown.
 *   4. Agent leaderboard — sortable by replies / median / p95.
 *
 * Shared controls at the top of the page: range (7d / 30d / 90d) and
 * granularity (day / hour, where hour is disabled for 90d to keep the
 * server bucket cap of 100 honest). Each widget reacts to signal
 * inputs and re-fetches.
 *
 * Route gating: `whatsapp.analytics.read` (registered by the reporting
 * module descriptor). Sidebar entry is hidden for roles without the
 * key, so junior sales doesn't see "is WhatsApp working?" dashboards.
 */
@Component({
  selector: 'app-whatsapp-reports-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    VolumeWidgetComponent,
    ResponseTimeWidgetComponent,
    OutcomesWidgetComponent,
    AgentLeaderboardComponent,
    CostWidgetComponent,
    QualityTimelineComponent,
    AIMetricsWidgetComponent,
    AdRoiWidgetComponent,
  ],
  template: `
    <div class="space-y-4 p-4">
      <header class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-zinc-900">WhatsApp reports</h1>
          <p class="text-xs text-zinc-500">
            Is WhatsApp working? Who's responding fastest?
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <div
            class="inline-flex items-center rounded-md border border-zinc-300 bg-white p-0.5 text-xs"
            role="tablist"
            aria-label="Date range"
          >
            @for (r of RANGES; track r.key) {
              <button
                type="button"
                role="tab"
                [class]="
                  'rounded px-2.5 py-1 ' +
                  (range() === r.key
                    ? 'bg-zinc-900 text-white'
                    : 'text-zinc-700 hover:bg-zinc-100')
                "
                (click)="setRange(r.key)"
              >
                {{ r.label }}
              </button>
            }
          </div>

          <div
            class="inline-flex items-center rounded-md border border-zinc-300 bg-white p-0.5 text-xs"
            role="tablist"
            aria-label="Granularity"
          >
            @for (g of GRANULARITIES; track g.key) {
              <button
                type="button"
                role="tab"
                [disabled]="granularityDisabled(g.key)"
                [class]="
                  'rounded px-2.5 py-1 ' +
                  (granularity() === g.key
                    ? 'bg-zinc-900 text-white'
                    : 'text-zinc-700 hover:bg-zinc-100') +
                  (granularityDisabled(g.key) ? ' cursor-not-allowed opacity-40' : '')
                "
                (click)="setGranularity(g.key)"
                [title]="granularityDisabled(g.key) ? 'Hour granularity is only available for 7d and 30d ranges' : ''"
              >
                {{ g.label }}
              </button>
            }
          </div>
        </div>
      </header>

      <app-wa-volume-widget [range]="range()" [granularity]="granularity()" />

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <app-wa-response-time-widget [range]="range()" />
        <app-wa-outcomes-widget [range]="range()" />
      </div>

      <app-wa-agent-leaderboard [range]="range()" />

      <!-- Step 21 — cost + quality timeline + AI metrics. -->
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <app-wa-cost-widget [range]="range()" />
        <app-wa-ai-metrics-widget [range]="range()" />
      </div>

      <app-wa-quality-timeline [range]="range()" />

      <!-- Step 24 — click-to-WhatsApp ad ROI. -->
      <app-wa-ad-roi-widget [range]="range()" />
    </div>
  `,
})
export class WhatsAppReportsPageComponent {
  protected readonly RANGES: ReadonlyArray<{ key: ReportRange; label: string }> = [
    { key: '7d', label: 'Last 7 days' },
    { key: '30d', label: 'Last 30 days' },
    { key: '90d', label: 'Last 90 days' },
  ];
  protected readonly GRANULARITIES: ReadonlyArray<{
    key: ReportGranularity;
    label: string;
  }> = [
    { key: 'day', label: 'Day' },
    { key: 'hour', label: 'Hour' },
  ];

  protected readonly range = signal<ReportRange>('7d');
  protected readonly granularity = signal<ReportGranularity>('day');

  protected granularityDisabled(g: ReportGranularity): boolean {
    return g === 'hour' && this.range() === '90d';
  }

  protected setRange(r: ReportRange): void {
    this.range.set(r);
    if (this.granularityDisabled(this.granularity())) {
      this.granularity.set('day');
    }
  }

  protected setGranularity(g: ReportGranularity): void {
    if (this.granularityDisabled(g)) return;
    this.granularity.set(g);
  }
}
