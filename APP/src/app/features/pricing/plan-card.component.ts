import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { BillingCycle, Plan } from './pricing.types';

/**
 * One plan column on the pricing page.
 *
 * Inputs:
 *   - `plan` — the API plan object
 *   - `cycle` — `'monthly' | 'annual'`; drives which price + extra-seat
 *     line is shown
 *   - `cardFeatures` — the curated marketing bullets to render
 *   - `popular` — toggles the "Most popular" ribbon on the Standard tier
 *
 * The CTA is a `routerLink` to `/accounts/register` carrying `plan`
 * + `cycle` as query params so the signup flow can auto-checkout into
 * the right plan once the user has an org.
 */
@Component({
  selector: 'crm-plan-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink],
  template: `
    <article
      class="relative flex flex-col rounded-2xl border bg-white dark:bg-slate-800 p-6 shadow-sm transition-all"
      [class.border-blue-600]="popular()"
      [class.border-2]="popular()"
      [class.shadow-md]="popular()"
      [class.border-gray-200]="!popular()"
      [class.dark:border-slate-700]="!popular()"
    >
      @if (popular()) {
        <span
          class="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[11px] font-semibold uppercase tracking-wider bg-blue-600 text-white shadow"
        >
          Most popular
        </span>
      }

      <header class="mb-4">
        <h3 class="text-lg font-semibold text-gray-900 dark:text-slate-100">
          {{ plan().name }}
        </h3>
      </header>

      <div class="mb-6">
        <div class="flex items-baseline gap-1">
          <span class="text-4xl font-bold text-gray-900 dark:text-slate-100">
            \${{ displayPrice() }}
          </span>
          <span class="text-sm text-gray-500 dark:text-slate-400">/mo</span>
        </div>
        @if (cycle() === 'annual') {
          <p class="mt-1 text-xs text-gray-500 dark:text-slate-400">
            \${{ plan().pricing.annual_bundle_usd }} billed annually
            <span class="text-emerald-600 dark:text-emerald-400 font-medium">
              · save 20%
            </span>
          </p>
        }
        <p class="mt-3 text-sm text-gray-600 dark:text-slate-300">
          {{ plan().pricing.included_seats }} seats included
        </p>
        <p class="text-sm text-gray-500 dark:text-slate-400">
          +\${{ extraSeatPrice() }} per extra seat /
          {{ cycle() === 'annual' ? 'yr' : 'mo' }}
        </p>
      </div>

      <ul class="flex-1 space-y-2.5 mb-6">
        @for (feature of cardFeatures(); track feature) {
          <li class="flex items-start gap-2 text-sm text-gray-700 dark:text-slate-300">
            <lucide-icon
              name="check"
              class="w-4 h-4 mt-0.5 text-emerald-500 shrink-0"
            ></lucide-icon>
            <span>{{ feature }}</span>
          </li>
        }
      </ul>

      <a
        [routerLink]="['/accounts/register']"
        [queryParams]="ctaQueryParams()"
        class="block text-center px-4 py-2.5 rounded-lg font-medium transition-colors"
        [class.bg-blue-600]="popular()"
        [class.text-white]="popular()"
        [class.hover:bg-blue-700]="popular()"
        [class.bg-gray-100]="!popular()"
        [class.dark:bg-slate-700]="!popular()"
        [class.text-gray-900]="!popular()"
        [class.dark:text-slate-100]="!popular()"
        [class.hover:bg-gray-200]="!popular()"
        [class.dark:hover:bg-slate-600]="!popular()"
      >
        Start free trial
      </a>
    </article>
  `,
})
export class PlanCardComponent {
  readonly plan = input.required<Plan>();
  readonly cycle = input.required<BillingCycle>();
  readonly cardFeatures = input.required<readonly string[]>();
  readonly popular = input<boolean>(false);

  /**
   * Per-month-equivalent dollars. Annual bundle ÷ 12, rounded down so
   * the marketing copy never overpromises (e.g. $1392/yr → $116/mo,
   * not $116.0001).
   */
  protected readonly displayPrice = computed(() => {
    const p = this.plan().pricing;
    return this.cycle() === 'annual'
      ? Math.floor(p.annual_bundle_usd / 12)
      : p.monthly_bundle_usd;
  });

  protected readonly extraSeatPrice = computed(() => {
    const p = this.plan().pricing;
    return this.cycle() === 'annual'
      ? p.extra_seat_annual_usd
      : p.extra_seat_monthly_usd;
  });

  protected readonly ctaQueryParams = computed(() => ({
    plan: this.plan().code,
    cycle: this.cycle(),
  }));
}
