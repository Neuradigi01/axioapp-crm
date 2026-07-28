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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import {
  CampaignFailuresReport,
  CampaignFunnelReport,
  WhatsAppReportsService,
} from '../../reporting/whatsapp/whatsapp-reports.service';
import { AbVariantComparisonComponent } from './ab-variant-comparison.component';
import { FailuresTableComponent } from './failures-table.component';
import { FunnelChartComponent } from './funnel-chart.component';

/**
 * Campaign-detail Analytics tab (Step 21).
 *
 * Loads the funnel + failure breakdown for one campaign id and
 * renders them side-by-side. The campaign-detail page mounts this
 * component when the operator clicks the "Analytics" tab.
 *
 * Gated upstream by the `whatsapp.analytics.read` permission key;
 * the parent page hides the tab when the user lacks the grant.
 */
@Component({
  selector: 'app-campaign-analytics-tab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    FunnelChartComponent,
    FailuresTableComponent,
    AbVariantComparisonComponent,
  ],
  template: `
    <!-- Step 29 — A/B variant comparison. Renders only for A/B
         campaigns (the component itself short-circuits when the
         API returns is_ab_test=false). -->
    <div class="mb-4">
      <app-ab-variant-comparison [campaignId]="campaignId()" />
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div class="rounded-md border border-subtle bg-surface p-4">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-muted">Funnel</p>
            <p class="text-[11px] text-muted">
              Conversion attribution uses a 7-day window from message receipt.
            </p>
          </div>
          @if (funnelLoading()) {
            <span class="text-[11px] text-muted">Loading…</span>
          }
        </div>
        @if (funnelError(); as err) {
          <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {{ err }}
          </p>
        } @else {
          <app-campaign-funnel-chart [report]="funnel()" />
        }
      </div>

      <div class="rounded-md border border-subtle bg-surface p-4">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-muted">
              Failure breakdown
            </p>
            <p class="text-[11px] text-muted">Classified from Meta's error titles.</p>
          </div>
          @if (failuresLoading()) {
            <span class="text-[11px] text-muted">Loading…</span>
          }
        </div>
        @if (failuresError(); as err) {
          <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {{ err }}
          </p>
        } @else {
          <app-campaign-failures-table [report]="failures()" />
        }
      </div>
    </div>
  `,
})
export class CampaignAnalyticsTabComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly campaignId = input.required<string>();

  protected readonly funnel = signal<CampaignFunnelReport | null>(null);
  protected readonly funnelLoading = signal<boolean>(false);
  protected readonly funnelError = signal<string | null>(null);

  protected readonly failures = signal<CampaignFailuresReport | null>(null);
  protected readonly failuresLoading = signal<boolean>(false);
  protected readonly failuresError = signal<string | null>(null);

  constructor() {
    effect(() => {
      const id = this.campaignId();
      if (id) this.load(id);
    });
  }

  private load(id: string): void {
    this.funnelLoading.set(true);
    this.funnelError.set(null);
    this.api
      .getCampaignFunnel(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.funnel.set(r);
          this.funnelLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.funnelLoading.set(false);
          this.funnelError.set(extractApiError(err) ?? 'Could not load funnel.');
        },
      });

    this.failuresLoading.set(true);
    this.failuresError.set(null);
    this.api
      .getCampaignFailures(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.failures.set(r);
          this.failuresLoading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.failuresLoading.set(false);
          this.failuresError.set(extractApiError(err) ?? 'Could not load failures.');
        },
      });
  }
}
