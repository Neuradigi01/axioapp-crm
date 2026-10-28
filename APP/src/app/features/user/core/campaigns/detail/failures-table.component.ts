import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { CampaignFailuresReport } from '../../reporting/whatsapp/whatsapp-reports.service';

/**
 * Failure-reason breakdown table (Step 21).
 *
 * Server classifies every failed campaign-message row into one of
 * six taxonomy buckets (rate_limited / invalid_number / opted_out /
 * template_paused / quality_restricted / other) and we render a
 * sorted-by-count table here with a small `sample_errors` list at
 * the bottom so the operator can drill into the "other" bucket.
 */
@Component({
  selector: 'app-campaign-failures-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    @if (report(); as r) {
      @if (r.total_failed === 0) {
        <p
          class="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-700"
        >
          No failures — every campaign message reached Meta.
        </p>
      } @else {
        <table class="w-full text-xs">
          <thead class="text-zinc-500">
            <tr class="border-b border-zinc-200">
              <th class="py-1 text-left font-medium">Reason</th>
              <th class="py-1 text-right font-medium">Count</th>
              <th class="py-1 text-right font-medium">% of failed</th>
            </tr>
          </thead>
          <tbody>
            @for (b of sortedBuckets(); track b.reason) {
              <tr class="border-b border-zinc-100 last:border-0">
                <td class="py-1 text-zinc-800">{{ b.label }}</td>
                <td class="py-1 text-right text-zinc-700">{{ b.count }}</td>
                <td class="py-1 text-right text-zinc-500">
                  {{ percent(b.count, r.total_failed) }}%
                </td>
              </tr>
            }
          </tbody>
        </table>

        @if (r.sample_errors.length > 0) {
          <details class="mt-2 text-xs text-zinc-600">
            <summary class="cursor-pointer text-zinc-500 hover:text-zinc-700">
              Sample errors ({{ r.sample_errors.length }})
            </summary>
            <ul class="mt-1 space-y-0.5 pl-4 text-[11px]">
              @for (e of r.sample_errors; track e) {
                <li class="text-zinc-600">{{ e }}</li>
              }
            </ul>
          </details>
        }
      }
    }
  `,
})
export class FailuresTableComponent {
  readonly report = input.required<CampaignFailuresReport | null>();

  protected readonly sortedBuckets = computed(() => {
    const r = this.report();
    if (!r) return [];
    return [...r.buckets].sort((a, b) => b.count - a.count);
  });

  protected percent(n: number, total: number): number {
    if (!total) return 0;
    return Math.round((n / total) * 100);
  }
}
