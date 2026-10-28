import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { SeatModalService } from '../../services/seat-modal.service';
import { SubscriptionCurrent } from '../../types/subscription.types';

/**
 * Second card on the Billing settings page.
 *
 * Renders seat utilisation (`in_use / purchased`) with a visual
 * progress bar, the bundle floor, the per-seat overage cost, and the
 * "Manage seats" CTA. CTA is disabled on trial (cannot buy extra
 * seats) and on cancelled / archived (terminal states).
 */
@Component({
  selector: 'crm-seats-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <section
      class="flex h-full flex-col rounded-xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <div
            class="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-950 dark:text-blue-300 dark:ring-blue-900"
          >
            <lucide-icon name="users" size="18" aria-hidden="true"></lucide-icon>
          </div>
          <div>
            <p
              class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400"
            >
              Seats
            </p>
            <h2 class="text-base font-semibold text-zinc-900 dark:text-slate-100">Team seats</h2>
          </div>
        </div>

        <button
          type="button"
          (click)="onManage()"
          class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors"
          [class.cursor-not-allowed]="manageDisabled()"
          [class.border-zinc-200]="manageDisabled()"
          [class.text-zinc-400]="manageDisabled()"
          [class.dark:border-slate-700]="manageDisabled()"
          [class.dark:text-slate-500]="manageDisabled()"
          [class.border-zinc-300]="!manageDisabled()"
          [class.bg-white]="!manageDisabled()"
          [class.text-zinc-700]="!manageDisabled()"
          [class.hover:bg-zinc-50]="!manageDisabled()"
          [class.dark:border-slate-600]="!manageDisabled()"
          [class.dark:bg-slate-700]="!manageDisabled()"
          [class.dark:text-slate-200]="!manageDisabled()"
          [class.dark:hover:bg-slate-600]="!manageDisabled()"
          [disabled]="manageDisabled()"
          [title]="manageTooltip()"
        >
          Manage
        </button>
      </div>

      <div class="mt-5">
        <div class="flex items-baseline justify-between">
          <p class="text-sm text-zinc-600 dark:text-slate-400">In use</p>
          <p class="text-sm font-semibold tabular-nums text-zinc-900 dark:text-slate-100">
            {{ subscription().seats.in_use }} / {{ subscription().seats.purchased }}
          </p>
        </div>
        <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-slate-700">
          <div
            class="h-full rounded-full transition-all"
            [class.bg-emerald-500]="seatTone() === 'green'"
            [class.bg-amber-500]="seatTone() === 'yellow'"
            [class.bg-rose-500]="seatTone() === 'red'"
            [style.width.%]="seatPercent()"
          ></div>
        </div>
        <p class="mt-2 text-xs text-zinc-500 dark:text-slate-400">
          {{ helperLine() }}
        </p>
      </div>

      <dl class="mt-6 grid flex-1 gap-4 sm:grid-cols-3">
        <div>
          <dt
            class="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400"
          >
            Included
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-zinc-900 dark:text-slate-100">
            {{ subscription().seats.included }}
          </dd>
        </div>
        <div>
          <dt
            class="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400"
          >
            Active
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-zinc-900 dark:text-slate-100">
            {{ subscription().seats.in_use }}
          </dd>
        </div>
        <div>
          <dt
            class="text-[11px] font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400"
          >
            Extra seat
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-zinc-900 dark:text-slate-100">
            {{ '$' + subscription().seats.extra_seat_cost_per_period_usd }}
            <span class="text-xs font-normal text-zinc-500 dark:text-slate-400">
              /{{ subscription().billing_cycle === 'annual' ? 'yr' : 'mo' }}
            </span>
          </dd>
        </div>
      </dl>
    </section>
  `,
})
export class SeatsCardComponent {
  private readonly seatModal = inject(SeatModalService);

  readonly subscription = input.required<SubscriptionCurrent>();

  /** Trial subs cannot buy seats (server rejects); cancelled /
   *  archived are terminal. Active / past_due / read_only let the
   *  Owner adjust seats — past_due in particular because reducing
   *  seats to the in-use floor can be a cost-recovery move. */
  protected readonly manageDisabled = computed(() => {
    const status = this.subscription().status;
    return status === 'trialing' || status === 'cancelled' || status === 'archived';
  });

  protected readonly manageTooltip = computed(() => {
    const sub = this.subscription();
    switch (sub.status) {
      case 'trialing':
        return 'Seats can only be managed after upgrading from trial';
      case 'cancelled':
        return 'Subscription is cancelled — contact support to reactivate';
      case 'archived':
        return 'Account is archived';
      default:
        return '';
    }
  });

  protected onManage(): void {
    this.seatModal.open();
  }

  protected readonly seatPercent = computed(() => {
    const seats = this.subscription().seats;
    if (seats.purchased <= 0) return 0;
    return Math.min(100, Math.round((seats.in_use / seats.purchased) * 100));
  });

  protected readonly seatTone = computed<'green' | 'yellow' | 'red'>(() => {
    const pct = this.seatPercent();
    if (pct >= 90) return 'red';
    if (pct >= 70) return 'yellow';
    return 'green';
  });

  protected readonly helperLine = computed(() => {
    const sub = this.subscription();
    if (sub.status === 'trialing') {
      return `Trial includes ${sub.seats.included} seats; cannot add more until you upgrade.`;
    }
    const extra = Math.max(0, sub.seats.purchased - sub.seats.included);
    if (extra === 0) {
      return `Your plan includes ${sub.seats.included} seats.`;
    }
    const period = sub.billing_cycle === 'annual' ? 'yr' : 'mo';
    return `${extra} extra at $${sub.seats.extra_seat_cost_per_period_usd}/${period} on top of the ${sub.seats.included} included.`;
  });
}
