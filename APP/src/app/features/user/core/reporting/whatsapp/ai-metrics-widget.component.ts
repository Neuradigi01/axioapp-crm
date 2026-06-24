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
  AIMetricsReport,
  ReportRange,
  WhatsAppReportsService,
} from './whatsapp-reports.service';

/**
 * AI metrics widget (Step 21).
 *
 * Three KPIs:
 *   1. AI response rate — share of outbound replies authored by the bot.
 *   2. Escalation rate — share of AI-handled conversations that flipped
 *      to human via the Step 19 handover pipeline.
 *   3. AI-only completion proxy — conversations the bot handled
 *      end-to-end (no human reply in the window).
 *
 * Plus a small per-reason escalation breakdown so an operator can see
 * "most of our escalations are keyword-triggered, not low-confidence".
 */
@Component({
  selector: 'app-wa-ai-metrics-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">
            AI metrics
          </p>
          <p class="text-[11px] text-zinc-500">
            Bot adoption, hand-off rate, and unattended completions.
          </p>
        </div>
        @if (loading()) {
          <span class="text-[11px] text-zinc-500">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      } @else if (report(); as r) {
        <div class="mb-4 grid grid-cols-3 gap-2">
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">AI response rate</p>
            <p class="text-lg font-semibold text-violet-700">
              {{ percent(r.ai_response_rate) }}%
            </p>
            <p class="text-[10px] text-zinc-500">
              {{ r.ai_replies }} AI / {{ r.human_replies }} human
            </p>
          </div>
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">Escalation rate</p>
            <p class="text-lg font-semibold text-amber-700">
              {{ percent(r.escalation_rate) }}%
            </p>
            <p class="text-[10px] text-zinc-500">
              {{ r.escalated_conversations }} of
              {{ r.ai_handled_conversations }} convs
            </p>
          </div>
          <div class="rounded border border-zinc-200 bg-zinc-50 px-3 py-2">
            <p class="text-[10px] uppercase text-zinc-500">AI-only completed</p>
            <p class="text-lg font-semibold text-emerald-700">
              {{ r.ai_only_completed }}
            </p>
            <p class="text-[10px] text-zinc-500">No human reply needed</p>
          </div>
        </div>

        @if (escalationReasonRows(r).length > 0) {
          <div>
            <p class="mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
              Escalation reasons
            </p>
            <ul class="space-y-0.5 text-xs">
              @for (row of escalationReasonRows(r); track row.reason) {
                <li class="flex items-center justify-between">
                  <span class="text-zinc-700">{{ humanReason(row.reason) }}</span>
                  <span class="font-medium text-zinc-900">{{ row.count }}</span>
                </li>
              }
            </ul>
          </div>
        } @else if (r.escalated_conversations === 0) {
          <p class="text-xs text-zinc-500">
            No escalations in this window — the bot handled every flagged
            conversation.
          </p>
        }
      }
    </div>
  `,
})
export class AIMetricsWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);

  readonly range = input.required<ReportRange>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<AIMetricsReport | null>(null);

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  protected percent(ratio: number): number {
    return Math.round((ratio || 0) * 100);
  }

  protected escalationReasonRows(
    r: AIMetricsReport,
  ): { reason: string; count: number }[] {
    return Object.entries(r.escalation_reasons)
      .map(([reason, count]) => ({ reason, count: count as number }))
      .sort((a, b) => b.count - a.count);
  }

  protected humanReason(reason: string): string {
    switch (reason) {
      case 'keyword':
        return 'Customer keyword';
      case 'ai_requested':
        return 'AI requested';
      case 'low_confidence':
        return 'Low confidence';
      case 'ai_invocation_failed':
        return 'LLM call failed';
      case 'send_failed':
        return 'Adapter send failed';
      default:
        return reason;
    }
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getAIMetrics(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not load AI metrics.',
          );
        },
      });
  }
}
