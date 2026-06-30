import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  TemplatePerformance,
  TemplatePerformanceRange,
  WhatsAppTemplateRead,
  WhatsAppTemplatesApiService,
} from './whatsapp-templates-api.service';

/**
 * Per-template performance card
 * (whatsapp-platform-upgrade Step 10).
 *
 * Stat-card grid (Sent / Delivered / Read / Replied / Click-through /
 * Failed) + daily line chart drawn as inline SVG + failure breakdown
 * table. Range toggle (7d / 30d / 90d) re-fetches on click.
 *
 * Empty-state: the same backend returns zero counts when the template
 * has never been sent — the component shows a friendly empty banner
 * instead of an all-zero chart.
 */

const RANGES: Array<{ key: TemplatePerformanceRange; label: string }> = [
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: '90d', label: 'Last 90 days' },
];

@Component({
  selector: 'app-template-performance',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, RouterLink],
  template: `
    <div class="space-y-4">
      <!-- Header -->
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-zinc-900">
            {{ template.name }}
          </h2>
          <p class="text-xs text-zinc-500">
            {{ template.category }} · {{ template.language }} ·
            {{ template.submission_status }}
          </p>
        </div>
        <div class="flex items-center gap-1 rounded-md border border-zinc-200 bg-white p-0.5">
          @for (r of RANGES; track r.key) {
            <button
              type="button"
              (click)="setRange(r.key)"
              [class]="
                'rounded-md px-2.5 py-1 text-xs font-medium transition ' +
                (range() === r.key ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100')
              "
            >
              {{ r.label }}
            </button>
          }
        </div>
      </div>

      @if (loadError(); as err) {
        <div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {{ err }}
        </div>
      }

      @if (loading()) {
        <div
          class="rounded-md border border-zinc-200 bg-white px-6 py-12 text-center text-sm text-zinc-500"
        >
          Loading metrics…
        </div>
      } @else if (data(); as d) {
        @if (d.sent === 0 && d.failed === 0) {
          <div class="rounded-md border border-zinc-200 bg-white px-6 py-12 text-center">
            <lucide-icon name="trending-up" class="mx-auto mb-2 h-8 w-8 text-zinc-300" />
            <p class="text-sm font-medium text-zinc-700">No data yet.</p>
            <p class="mt-1 text-xs text-zinc-500">
              Send this template in a campaign to see metrics here.
            </p>
          </div>
        } @else {
          <!-- Stat-card grid -->
          <div class="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Sent</p>
              <p class="mt-1 text-2xl font-semibold text-zinc-900">
                {{ d.sent }}
              </p>
            </div>
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                Delivered
              </p>
              <p class="mt-1 text-2xl font-semibold text-zinc-900">
                {{ d.delivered }}
              </p>
              <p class="text-[10px] text-zinc-500">{{ d.delivery_rate }}%</p>
            </div>
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Read</p>
              <p class="mt-1 text-2xl font-semibold text-zinc-900">
                {{ d.read }}
              </p>
              <p class="text-[10px] text-zinc-500">{{ d.read_rate }}%</p>
            </div>
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Replied</p>
              <p class="mt-1 text-2xl font-semibold text-zinc-900">
                {{ d.replied }}
              </p>
              <p class="text-[10px] text-zinc-500">{{ d.reply_rate }}%</p>
            </div>
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
                Click-through
              </p>
              <p class="mt-1 text-2xl font-semibold text-zinc-900">
                {{ d.click_through }}
              </p>
            </div>
            <div class="rounded-md border border-zinc-200 bg-white p-3">
              <p class="text-[10px] font-semibold uppercase tracking-wide text-zinc-500">Failed</p>
              <p class="mt-1 text-2xl font-semibold text-rose-700">
                {{ d.failed }}
              </p>
            </div>
          </div>

          <!-- Chart + failure table -->
          <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div class="rounded-md border border-zinc-200 bg-white p-4 lg:col-span-2">
              <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                Daily trend
              </p>
              @if (d.daily.length === 0) {
                <p class="py-4 text-center text-xs text-zinc-500">
                  Not enough data for a trend chart yet.
                </p>
              } @else {
                <svg viewBox="0 0 600 160" class="h-32 w-full" preserveAspectRatio="none">
                  <!-- Axis baseline -->
                  <line x1="0" y1="150" x2="600" y2="150" stroke="#e4e4e7" stroke-width="1" />
                  <!-- Sent (zinc-900) -->
                  <polyline
                    [attr.points]="chartLine('sent')"
                    fill="none"
                    stroke="#18181b"
                    stroke-width="2"
                  />
                  <!-- Delivered (emerald-500) -->
                  <polyline
                    [attr.points]="chartLine('delivered')"
                    fill="none"
                    stroke="#10b981"
                    stroke-width="2"
                  />
                  <!-- Read (sky-500) -->
                  <polyline
                    [attr.points]="chartLine('read')"
                    fill="none"
                    stroke="#0ea5e9"
                    stroke-width="2"
                  />
                  <!-- Failed (rose-500) -->
                  <polyline
                    [attr.points]="chartLine('failed')"
                    fill="none"
                    stroke="#f43f5e"
                    stroke-width="2"
                  />
                </svg>
                <div class="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-zinc-600">
                  <span class="inline-flex items-center gap-1">
                    <span class="inline-block h-2 w-2 rounded-full bg-zinc-900"></span>
                    Sent
                  </span>
                  <span class="inline-flex items-center gap-1">
                    <span class="inline-block h-2 w-2 rounded-full bg-emerald-500"></span>
                    Delivered
                  </span>
                  <span class="inline-flex items-center gap-1">
                    <span class="inline-block h-2 w-2 rounded-full bg-sky-500"></span>
                    Read
                  </span>
                  <span class="inline-flex items-center gap-1">
                    <span class="inline-block h-2 w-2 rounded-full bg-rose-500"></span>
                    Failed
                  </span>
                </div>
              }
            </div>

            <div class="rounded-md border border-zinc-200 bg-white p-4">
              <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                Failure breakdown
              </p>
              @if (d.failures.length === 0) {
                <p class="py-4 text-center text-xs text-zinc-500">No failures in this range. 🎉</p>
              } @else {
                <ul class="divide-y divide-zinc-100">
                  @for (f of d.failures; track f.bucket) {
                    <li class="flex items-center justify-between py-1.5 text-xs">
                      <span class="text-zinc-700">{{ f.label }}</span>
                      <span class="font-semibold text-zinc-900">
                        {{ f.count }}
                      </span>
                    </li>
                  }
                </ul>
              }
            </div>
          </div>

          @if (d.used_in_campaigns > 0) {
            <p class="text-xs text-zinc-500">
              Used in
              <a routerLink="/user/campaigns" class="font-semibold text-zinc-900 underline"
                >{{ d.used_in_campaigns }}
                {{ d.used_in_campaigns === 1 ? 'campaign' : 'campaigns' }}</a
              >.
            </p>
          }
        }
      }
    </div>
  `,
})
export class TemplatePerformanceComponent {
  private readonly api = inject(WhatsAppTemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly RANGES = RANGES;

  @Input({ required: true }) template!: WhatsAppTemplateRead;

  protected readonly range = signal<TemplatePerformanceRange>('30d');
  protected readonly data = signal<TemplatePerformance | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    // Refetch whenever the range changes. Skip in SSR by gating on a
    // mounted template input via a guard inside `fetch`.
    effect(() => {
      this.range();
      this.fetch();
    });
  }

  protected setRange(r: TemplatePerformanceRange): void {
    this.range.set(r);
  }

  protected chartLine(key: 'sent' | 'delivered' | 'read' | 'failed'): string {
    const d = this.data();
    if (!d || d.daily.length === 0) return '';
    const max = d.daily.reduce((m, b) => Math.max(m, b.sent, b.delivered, b.read, b.failed), 0);
    if (max === 0) return '';
    const width = 600;
    const height = 150;
    const step = d.daily.length > 1 ? width / (d.daily.length - 1) : 0;
    return d.daily
      .map((bucket, i) => {
        const x = i * step;
        const y = height - (bucket[key] / max) * height;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  }

  private fetch(): void {
    if (!this.template) return;
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .performance(this.template.id, this.range())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.data.set(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.data.set(null);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load template metrics.');
        },
      });
  }
}
