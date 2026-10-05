import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import {
  CampaignFunnelReport,
  formatDuration,
} from '../../reporting/whatsapp/whatsapp-reports.service';

/**
 * Pure-presentation funnel bar list (Step 21).
 *
 * Renders each stage as a horizontal bar whose width is normalised
 * against the "targeted" stage (or whichever is largest if
 * targeted=0). Conversion rates between adjacent stages are shown
 * on the right.
 */
@Component({
  selector: 'app-campaign-funnel-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    @if (report(); as r) {
      <div class="space-y-1.5">
        @for (stage of r.stages; track stage.key; let i = $index) {
          <div class="grid grid-cols-12 items-center gap-2 text-xs">
            <span class="col-span-3 truncate font-medium text-default">
              {{ stage.label }}
            </span>
            <div class="col-span-7 h-5 overflow-hidden rounded bg-surface-2">
              <div
                class="flex h-full items-center px-2 text-[10px] font-semibold text-white"
                [class]="barColor(stage.key)"
                [style.width.%]="percentOfMax(stage.count)"
              >
                @if (percentOfMax(stage.count) > 12) {
                  {{ stage.count }}
                }
              </div>
            </div>
            <span class="col-span-2 text-right text-muted">
              @if (percentOfMax(stage.count) <= 12) {
                <span class="mr-1 text-default">{{ stage.count }}</span>
              }
              <span class="text-[10px] text-muted">
                @if (i > 0 && r.stages[0].count > 0) {
                  ({{ percent(stage.count, r.stages[0].count) }}%)
                }
              </span>
            </span>
          </div>
        }
      </div>

      <div class="mt-4 grid grid-cols-2 gap-2 text-xs">
        <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
          <p class="text-[10px] uppercase text-muted">Median time to delivery</p>
          <p class="text-sm font-semibold text-default">
            {{ formatDuration(r.delivery_median_seconds) }}
          </p>
        </div>
        <div class="rounded border border-subtle bg-surface-2 px-3 py-2">
          <p class="text-[10px] uppercase text-muted">p95</p>
          <p class="text-sm font-semibold text-default">
            {{ formatDuration(r.delivery_p95_seconds) }}
          </p>
        </div>
      </div>
    }
  `,
})
export class FunnelChartComponent {
  readonly report = input.required<CampaignFunnelReport | null>();

  protected readonly formatDuration = formatDuration;

  protected readonly maxCount = computed(() => {
    const r = this.report();
    if (!r) return 0;
    return Math.max(...r.stages.map((s) => s.count), 1);
  });

  protected percentOfMax(n: number): number {
    const m = this.maxCount();
    if (!m) return 0;
    return Math.max(0, Math.min(100, Math.round((n / m) * 100)));
  }

  protected percent(n: number, total: number): number {
    if (!total) return 0;
    return Math.round((n / total) * 100);
  }

  protected barColor(key: string): string {
    switch (key) {
      case 'targeted':
        return 'bg-slate-500';
      case 'sent':
        return 'bg-sky-500';
      case 'delivered':
        return 'bg-blue-500';
      case 'read':
        return 'bg-indigo-500';
      case 'replied':
        return 'bg-emerald-500';
      case 'converted':
        return 'bg-violet-500';
      case 'failed':
        return 'bg-red-500';
      default:
        return 'bg-slate-500';
    }
  }
}
