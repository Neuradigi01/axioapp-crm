import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import { OutcomesReport, ReportRange, WhatsAppReportsService } from './whatsapp-reports.service';

/**
 * Outcomes widget (Step 20).
 *
 * Two stacks side-by-side: status distribution (open / snoozed /
 * closed) and the top-N tag breakdown. Tag chips link into the
 * conversations inbox with a pre-filled `tag_ids` query param —
 * fulfilling the spec's drilldown requirement.
 */
@Component({
  selector: 'app-wa-outcomes-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <div class="rounded-md border border-zinc-200 bg-white p-4">
      <div class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500">Outcomes</p>
          <p class="text-[11px] text-zinc-500">Conversation status mix + top tag breakdown.</p>
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
        @if (r.total === 0) {
          <p class="py-8 text-center text-xs text-zinc-500">
            No active conversations in this window.
          </p>
        } @else {
          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <p class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                By status ({{ r.total }} total)
              </p>
              @for (s of r.by_status; track s.key) {
                <div
                  (click)="onStatusClick(s.key)"
                  class="mb-1 cursor-pointer rounded border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 transition hover:border-zinc-300"
                  role="button"
                  [attr.aria-label]="'Filter conversations by status ' + s.label"
                  tabindex="0"
                  (keydown.enter)="onStatusClick(s.key)"
                >
                  <div class="flex items-center justify-between text-xs">
                    <span class="font-medium text-zinc-700">{{ s.label }}</span>
                    <span class="text-zinc-500">
                      {{ s.count }} ({{ percent(s.count, r.total) }}%)
                    </span>
                  </div>
                  <div class="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200">
                    <div
                      class="h-full rounded-full"
                      [style.width.%]="percent(s.count, r.total)"
                      [class]="statusBarColor(s.key)"
                    ></div>
                  </div>
                </div>
              }
            </div>

            <div>
              <p class="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                By tag (top {{ r.by_tag.length }})
              </p>
              @if (r.by_tag.length === 0) {
                <p class="text-xs text-zinc-500">No tags assigned in this window.</p>
              } @else {
                @for (t of r.by_tag; track t.key) {
                  <div
                    (click)="onTagClick(t.key)"
                    class="mb-1 cursor-pointer rounded border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 transition hover:border-zinc-300"
                    role="button"
                    [attr.aria-label]="'Filter conversations by tag ' + t.label"
                    tabindex="0"
                    (keydown.enter)="onTagClick(t.key)"
                  >
                    <div class="flex items-center justify-between text-xs">
                      <span class="font-medium text-zinc-700">{{ t.label }}</span>
                      <span class="text-zinc-500">{{ t.count }}</span>
                    </div>
                  </div>
                }
              }
            </div>
          </div>
        }
      }
    </div>
  `,
})
export class OutcomesWidgetComponent {
  private readonly api = inject(WhatsAppReportsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly router = inject(Router);

  readonly range = input.required<ReportRange>();

  protected readonly loading = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly report = signal<OutcomesReport | null>(null);

  constructor() {
    effect(() => {
      const r = this.range();
      this.fetch(r);
    });
  }

  protected percent(n: number, total: number): number {
    if (!total) return 0;
    return Math.round((n / total) * 100);
  }

  protected statusBarColor(key: string): string {
    switch (key) {
      case 'open':
        return 'bg-emerald-500';
      case 'snoozed':
        return 'bg-amber-500';
      case 'closed':
        return 'bg-zinc-500';
      default:
        return 'bg-zinc-400';
    }
  }

  protected onStatusClick(status: string): void {
    this.router.navigate(['/user/conversations'], {
      queryParams: { status, channel: 'whatsapp' },
    });
  }

  protected onTagClick(tagId: string): void {
    this.router.navigate(['/user/conversations'], {
      queryParams: { tag_ids: tagId, channel: 'whatsapp' },
    });
  }

  private fetch(range: ReportRange): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getOutcomes(range)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (r) => {
          this.report.set(r);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load outcomes.');
        },
      });
  }
}
