import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';

import { SeatModalService } from '../../../billing/services/seat-modal.service';
import { SubscriptionCurrent } from '../../../billing/types/subscription.types';

/**
 * Second card on the Billing settings page.
 *
 * Renders seat utilisation (`in_use / purchased`), the bundle floor,
 * the per-seat overage cost, and the "Manage seats" CTA. CTA is
 * disabled on trial (cannot buy extra seats) and on every plan in
 * 16.a — Step 17 wires the seat-management modal.
 */
@Component({
  selector: 'crm-seats-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400">
            Seats
          </p>
          <h2 class="mt-1 text-xl font-semibold text-zinc-900 dark:text-slate-100">
            Using {{ subscription().seats.in_use }} of
            {{ subscription().seats.purchased }} seats
          </h2>
          <p class="mt-1 text-sm text-zinc-500 dark:text-slate-400">
            {{ helperLine() }}
          </p>
        </div>

        <button
          type="button"
          (click)="onManage()"
          class="rounded-lg px-4 py-2 text-sm font-semibold transition-colors"
          [class.bg-zinc-100]="manageDisabled()"
          [class.text-zinc-500]="manageDisabled()"
          [class.cursor-not-allowed]="manageDisabled()"
          [class.dark:bg-slate-700]="manageDisabled()"
          [class.dark:text-slate-400]="manageDisabled()"
          [class.bg-zinc-900]="!manageDisabled()"
          [class.text-white]="!manageDisabled()"
          [class.hover:bg-zinc-800]="!manageDisabled()"
          [disabled]="manageDisabled()"
          [title]="manageTooltip()"
        >
          Manage seats
        </button>
      </div>

      <dl class="mt-6 grid gap-4 sm:grid-cols-3">
        <div>
          <dt class="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400">
            Included with plan
          </dt>
          <dd class="mt-1 text-sm font-medium text-zinc-900 dark:text-slate-100">
            {{ subscription().seats.included }} seats
          </dd>
        </div>
        <div>
          <dt class="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400">
            Active members
          </dt>
          <dd class="mt-1 text-sm font-medium text-zinc-900 dark:text-slate-100">
            {{ subscription().seats.in_use }}
          </dd>
        </div>
        <div>
          <dt class="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400">
            Extra seat
          </dt>
          <dd class="mt-1 text-sm font-medium text-zinc-900 dark:text-slate-100">
            \${{ subscription().seats.extra_seat_cost_per_period_usd }} per
            {{ subscription().billing_cycle === 'annual' ? 'year' : 'month' }}
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
    return (
      status === 'trialing' ||
      status === 'cancelled' ||
      status === 'archived'
    );
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
    return `Your plan includes ${sub.seats.included} seats. ${extra} extra at $${sub.seats.extra_seat_cost_per_period_usd}/${period}.`;
  });
}
