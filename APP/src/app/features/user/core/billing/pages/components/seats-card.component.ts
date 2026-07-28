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
      class="flex h-full flex-col rounded-xl border border-subtle bg-surface p-6 shadow-sm dark:border-subtle dark:bg-accent"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex items-center gap-3">
          <div
            class="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100 dark:bg-blue-950 dark:text-blue-300 dark:ring-blue-900"
          >
            <lucide-icon name="users" size="18" aria-hidden="true"></lucide-icon>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-muted dark:text-faint">
              Seats
            </p>
            <h2 class="text-base font-semibold text-default dark:text-default">Team seats</h2>
          </div>
        </div>

        <button
          type="button"
          (click)="onManage()"
          class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors"
          [class.cursor-not-allowed]="manageDisabled()"
          [class.border-subtle]="manageDisabled()"
          [class.text-faint]="manageDisabled()"
          [class.dark:border-subtle]="manageDisabled()"
          [class.dark:text-muted]="manageDisabled()"
          [class.border-subtle]="!manageDisabled()"
          [class.bg-surface]="!manageDisabled()"
          [class.text-default]="!manageDisabled()"
          [class.hover:bg-surface-2]="!manageDisabled()"
          [class.dark:border-subtle]="!manageDisabled()"
          [class.dark:bg-surface]="!manageDisabled()"
          [class.dark:text-default]="!manageDisabled()"
          [class.dark:hover:bg-surface]="!manageDisabled()"
          [disabled]="manageDisabled()"
          [title]="manageTooltip()"
        >
          Manage
        </button>
      </div>

      <div class="mt-5">
        <div class="flex items-baseline justify-between">
          <p class="text-sm text-muted dark:text-faint">In use</p>
          <p class="text-sm font-semibold tabular-nums text-default dark:text-default">
            {{ subscription().seats.in_use }} / {{ subscription().seats.purchased }}
          </p>
        </div>
        <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-surface-2 dark:bg-surface">
          <div
            class="h-full rounded-full transition-all"
            [class.bg-emerald-500]="seatTone() === 'green'"
            [class.bg-amber-500]="seatTone() === 'yellow'"
            [class.bg-rose-500]="seatTone() === 'red'"
            [style.width.%]="seatPercent()"
          ></div>
        </div>
        <p class="mt-2 text-xs text-muted dark:text-faint">
          {{ helperLine() }}
        </p>
      </div>

      <dl class="mt-6 grid flex-1 gap-4 sm:grid-cols-3">
        <div>
          <dt class="text-[11px] font-medium uppercase tracking-wide text-muted dark:text-faint">
            Included
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-default dark:text-default">
            {{ subscription().seats.included }}
          </dd>
        </div>
        <div>
          <dt class="text-[11px] font-medium uppercase tracking-wide text-muted dark:text-faint">
            Active
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-default dark:text-default">
            {{ subscription().seats.in_use }}
          </dd>
        </div>
        <div>
          <dt class="text-[11px] font-medium uppercase tracking-wide text-muted dark:text-faint">
            Extra seat
          </dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-default dark:text-default">
            {{ '$' + subscription().seats.extra_seat_cost_per_period_usd }}
            <span class="text-xs font-normal text-muted dark:text-faint">
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
