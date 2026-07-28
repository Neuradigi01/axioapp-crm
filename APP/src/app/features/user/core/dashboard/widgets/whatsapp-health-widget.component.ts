import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import {
  IntegrationsApiService,
  WhatsAppPhoneHealth,
  WhatsAppQualityRating,
} from '../../settings/integrations/integrations-api.service';

/**
 * Dashboard widget — WhatsApp health at a glance
 * (whatsapp-platform-upgrade Step 12).
 *
 * Compact card showing quality + tier + 24-hour usage; click routes
 * to the Integrations page where the full phone-health card lives.
 * Auto-hides if WhatsApp isn't connected (409 from the API).
 */

const QUALITY_DOT: Record<WhatsAppQualityRating, string> = {
  GREEN: 'bg-emerald-500',
  YELLOW: 'bg-amber-500',
  RED: 'bg-red-500',
  UNKNOWN: 'bg-surface-2',
};

const QUALITY_LABEL: Record<WhatsAppQualityRating, string> = {
  GREEN: 'Green',
  YELLOW: 'Yellow',
  RED: 'Red',
  UNKNOWN: 'Unknown',
};

@Component({
  selector: 'app-whatsapp-health-widget',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, LucideAngularModule],
  template: `
    @if (data(); as h) {
      <a
        routerLink="/user/integrations"
        class="block rounded-md border border-subtle bg-surface p-3 transition hover:border-subtle hover:shadow-sm"
      >
        <div class="flex items-center justify-between">
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">WhatsApp health</p>
          <lucide-icon name="arrow-right" class="h-3 w-3 text-faint" />
        </div>
        <div class="mt-2 flex items-center gap-2">
          <span
            [class]="'inline-block h-2.5 w-2.5 rounded-full ' + QUALITY_DOT[h.quality_rating]"
          ></span>
          <span class="text-sm font-medium text-default">
            {{ QUALITY_LABEL[h.quality_rating] }}
          </span>
          @if (h.tier_label) {
            <span class="text-xs text-muted">·</span>
            <span class="text-xs text-muted">{{ h.tier_label }}</span>
          }
        </div>
        @if (!h.is_unlimited && h.daily_limit > 0) {
          <p class="mt-1 text-[11px] text-muted">
            {{ h.used_today | number }} / {{ h.daily_limit | number }} today
          </p>
        }
        @if (h.restrictions.length > 0) {
          <p
            class="mt-1 inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-[10px] font-medium text-red-400"
          >
            <lucide-icon name="alert-triangle" size="10" />
            Restricted
          </p>
        }
      </a>
    }
  `,
})
export class WhatsAppHealthWidgetComponent {
  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly QUALITY_DOT = QUALITY_DOT;
  protected readonly QUALITY_LABEL = QUALITY_LABEL;

  protected readonly data = signal<WhatsAppPhoneHealth | null>(null);

  constructor() {
    this.api
      .getWhatsAppPhoneHealth()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (h) => this.data.set(h),
        // Silent: 409 (not connected) is the natural empty state.
        error: (_err: HttpErrorResponse) => this.data.set(null),
      });
  }
}
