import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  IntegrationsApiService,
  WhatsAppPhoneHealth,
  WhatsAppQualityRating,
} from '../../settings/integrations/integrations-api.service';

/**
 * Phone-health card (whatsapp-platform-upgrade Step 12).
 *
 * Single component combining the spec's three sub-components
 * (card + quality timeline + recovery checklist) for tighter shared
 * state. Renders:
 *
 *  - Quality badge (🟢 / 🟡 / 🔴 / ❔)
 *  - Messaging tier badge + 24-hr usage bar
 *  - Verified name + throughput + restrictions banner
 *  - 30-day timeline as inline SVG (one bar per event-day)
 *  - Recovery checklist (visible only when keys present)
 */

const QUALITY_BADGE: Record<
  WhatsAppQualityRating,
  { emoji: string; label: string; classes: string }
> = {
  GREEN: {
    emoji: '🟢',
    label: 'Green',
    classes: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  },
  YELLOW: {
    emoji: '🟡',
    label: 'Yellow',
    classes: 'bg-amber-50 text-amber-700 ring-amber-200',
  },
  RED: {
    emoji: '🔴',
    label: 'Red',
    classes: 'bg-rose-50 text-rose-700 ring-rose-200',
  },
  UNKNOWN: {
    emoji: '❔',
    label: 'Unknown',
    classes: 'bg-zinc-100 text-zinc-600 ring-zinc-200',
  },
};

const QUALITY_TOOLTIP: Record<WhatsAppQualityRating, string> = {
  GREEN: 'High-quality conversations. No restrictions.',
  YELLOW:
    'Quality has dropped recently. Address the recovery items below to avoid a tier downgrade.',
  RED: 'Quality is critically low. Meta may restrict or suspend the number if not addressed.',
  UNKNOWN:
    'Health data is not yet available. The hourly refresh will populate it within an hour.',
};

const RECOVERY_COPY: Record<string, { title: string; body: string }> = {
  quality_degraded: {
    title: 'Quality has dropped',
    body: 'Reduce broadcast volume, audit recent template content, and pause low-engagement campaigns.',
  },
  restricted: {
    title: 'Meta has restricted this number',
    body: 'Review the restriction reason in Meta Business Manager. Restrictions typically lift after the expiration timestamp.',
  },
  name_status_pending: {
    title: 'Verified name not yet approved',
    body: 'Display name changes take Meta 1–3 business days. Customers see the phone number until approval lands.',
  },
  low_tier: {
    title: 'Send more to grow the tier',
    body: 'Meta promotes the tier (1K → 10K → 100K) based on send volume + delivery quality over rolling 7-day windows.',
  },
};


@Component({
  selector: 'app-phone-health-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  template: `
    <div class="space-y-3">
      @if (loadError(); as err) {
        <div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {{ err }}
        </div>
      }

      @if (loading() && !data()) {
        <div class="rounded-md border border-zinc-200 bg-white px-4 py-6 text-center text-sm text-zinc-500">
          Loading health…
        </div>
      } @else if (data(); as h) {
        <!-- Top row: badges + refresh -->
        <div class="flex flex-wrap items-center justify-between gap-3 rounded-md border border-zinc-200 bg-white p-3">
          <div class="flex flex-wrap items-center gap-2">
            <span
              [class]="
                'inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ' +
                QUALITY_BADGE[h.quality_rating].classes
              "
              [title]="QUALITY_TOOLTIP[h.quality_rating]"
            >
              <span>{{ QUALITY_BADGE[h.quality_rating].emoji }}</span>
              Quality: {{ QUALITY_BADGE[h.quality_rating].label }}
            </span>
            @if (h.tier_label) {
              <span class="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-700 ring-1 ring-zinc-200">
                Tier · {{ h.tier_label }}
              </span>
            }
            @if (h.verified_name) {
              <span class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
                <lucide-icon name="check-circle-2" size="10" />
                {{ h.verified_name }}
              </span>
            }
            @if (h.throughput) {
              <span class="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-0.5 text-[11px] font-medium text-zinc-700 ring-1 ring-zinc-200">
                <lucide-icon name="zap" size="10" />
                {{ h.throughput }} msg/s
              </span>
            }
          </div>
          <button
            type="button"
            (click)="refresh()"
            [disabled]="refreshing()"
            class="inline-flex items-center gap-1 rounded-md border border-zinc-300 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          >
            <lucide-icon name="refresh-cw" size="12" />
            {{ refreshing() ? 'Refreshing…' : 'Refresh' }}
          </button>
        </div>

        <!-- 24-hr usage bar (unless unlimited tier) -->
        @if (!h.is_unlimited && h.daily_limit > 0) {
          <div class="rounded-md border border-zinc-200 bg-white p-3">
            <div class="mb-1 flex items-center justify-between text-xs">
              <span class="font-medium text-zinc-700">24-hour usage</span>
              <span class="text-zinc-600">
                {{ h.used_today | number }} / {{ h.daily_limit | number }}
                ({{ h.usage_percent }}%)
              </span>
            </div>
            <div class="h-2 w-full overflow-hidden rounded-full bg-zinc-100">
              <div
                [class]="
                  'h-full rounded-full transition-all ' +
                  (h.usage_percent < 70
                    ? 'bg-emerald-500'
                    : h.usage_percent < 90
                      ? 'bg-amber-500'
                      : 'bg-rose-500')
                "
                [style.width.%]="h.usage_percent"
              ></div>
            </div>
          </div>
        }

        <!-- Restrictions banner -->
        @if (h.restrictions.length > 0) {
          <div class="rounded-md border border-rose-200 bg-rose-50 p-3">
            <p class="flex items-center gap-1 text-sm font-semibold text-rose-800">
              <lucide-icon name="alert-triangle" size="14" />
              Meta has restricted this number
            </p>
            <ul class="mt-1 space-y-0.5 text-xs text-rose-700">
              @for (r of h.restrictions; track $index) {
                <li>
                  • {{ asString(r['restriction_type']) || 'Restriction' }}
                  @if (r['expiration']) {
                    — lifts {{ asString(r['expiration']) }}
                  }
                </li>
              }
            </ul>
          </div>
        }

        <!-- Recovery checklist -->
        @if (h.recovery_keys.length > 0) {
          <div class="rounded-md border border-amber-200 bg-amber-50 p-3">
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-800">
              Recovery checklist
            </p>
            <ul class="space-y-2">
              @for (key of h.recovery_keys; track key) {
                @if (RECOVERY_COPY[key]; as copy) {
                  <li class="text-xs">
                    <p class="font-medium text-amber-900">{{ copy.title }}</p>
                    <p class="text-amber-800">{{ copy.body }}</p>
                  </li>
                }
              }
            </ul>
          </div>
        }

        <!-- Timeline chart (last 30 days) -->
        @if (h.events.length > 0) {
          <div class="rounded-md border border-zinc-200 bg-white p-3">
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              Last 30 days
            </p>
            <ul class="space-y-1.5">
              @for (e of h.events; track e.id) {
                <li class="flex items-center gap-2 text-xs">
                  <span
                    [class]="
                      'inline-flex h-2 w-2 shrink-0 rounded-full ' +
                      eventDotClass(e.event_type)
                    "
                  ></span>
                  <span class="font-medium text-zinc-700">
                    {{ eventLabel(e.event_type) }}
                  </span>
                  <span class="text-zinc-500">
                    @if (e.old_value && e.new_value) {
                      {{ formatValue(e.old_value) }} →
                      {{ formatValue(e.new_value) }}
                    } @else if (e.new_value) {
                      {{ formatValue(e.new_value) }}
                    }
                  </span>
                  <span class="ml-auto text-[10px] text-zinc-400">
                    {{ e.occurred_at | date: 'short' }}
                  </span>
                </li>
              }
            </ul>
          </div>
        }

        @if (h.health_synced_at) {
          <p class="text-[10px] text-zinc-500">
            Synced from Meta: {{ h.health_synced_at | date: 'short' }}
          </p>
        }
      }
    </div>
  `,
})
export class PhoneHealthCardComponent {
  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly QUALITY_BADGE = QUALITY_BADGE;
  protected readonly QUALITY_TOOLTIP = QUALITY_TOOLTIP;
  protected readonly RECOVERY_COPY = RECOVERY_COPY;

  protected readonly data = signal<WhatsAppPhoneHealth | null>(null);
  protected readonly loading = signal<boolean>(false);
  protected readonly refreshing = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.load();
  }

  protected load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .getWhatsAppPhoneHealth()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (h) => {
          this.data.set(h);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load phone health.',
          );
        },
      });
  }

  protected refresh(): void {
    this.refreshing.set(true);
    this.api
      .refreshWhatsAppPhoneHealth()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (h) => {
          this.data.set(h);
          this.refreshing.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.refreshing.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not refresh phone health.',
          );
        },
      });
  }

  protected eventDotClass(eventType: string): string {
    switch (eventType) {
      case 'tier_change':
        return 'bg-emerald-500';
      case 'quality_change':
        return 'bg-amber-500';
      case 'restriction_added':
        return 'bg-rose-500';
      case 'restriction_lifted':
        return 'bg-sky-500';
      default:
        return 'bg-zinc-400';
    }
  }

  protected eventLabel(eventType: string): string {
    switch (eventType) {
      case 'quality_change':
        return 'Quality';
      case 'tier_change':
        return 'Tier';
      case 'name_status_change':
        return 'Name status';
      case 'restriction_added':
        return 'Restriction added';
      case 'restriction_lifted':
        return 'Restriction lifted';
      default:
        return eventType;
    }
  }

  protected formatValue(value: Record<string, unknown> | null): string {
    if (!value) return '';
    if ('value' in value) {
      const v = value['value'];
      return v === null || v === undefined ? '—' : String(v);
    }
    return JSON.stringify(value);
  }

  protected asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }
}
