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
    <section class="flex h-full flex-col rounded-2xl border border-subtle bg-surface p-5 shadow-sm">
      <p class="text-[13px] font-semibold text-default">Seats</p>

      <div class="mt-4 flex items-baseline gap-1">
        <span class="font-display text-[32px] font-bold leading-none tabular-nums text-default">
          {{ subscription().seats.in_use }}
        </span>
        <span class="font-mono text-[12px] text-faint">
          / {{ subscription().seats.purchased }}
        </span>
      </div>

      <p class="mt-2 text-[13px] text-muted">
        {{ seatsAvailable() }} seat{{ seatsAvailable() === 1 ? '' : 's' }} available
      </p>

      <!-- Progress bar — subtle indicator underneath the counts so the
           card still shows utilisation at a glance. -->
      <div class="mt-4 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
        <div
          class="h-full rounded-full transition-all"
          [class.bg-emerald-500]="seatTone() === 'green'"
          [class.bg-amber-500]="seatTone() === 'yellow'"
          [class.bg-red-500]="seatTone() === 'red'"
          [style.width.%]="seatPercent()"
        ></div>
      </div>

      <button
        type="button"
        (click)="onManage()"
        class="mt-auto inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-subtle bg-surface-2 px-3 py-2.5 text-[13px] font-semibold text-default transition hover:bg-surface disabled:cursor-not-allowed disabled:opacity-50"
        [disabled]="manageDisabled()"
        [title]="manageTooltip()"
      >
        Invite teammate
      </button>
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

  /** Seats not yet occupied — powers the "N seats available" line
   *  in the compact card layout. Clamped at 0 so an over-provisioned
   *  read (in_use > purchased, e.g. seat-reduction lag) doesn't
   *  render a negative. */
  protected readonly seatsAvailable = computed(() => {
    const s = this.subscription().seats;
    return Math.max(0, s.purchased - s.in_use);
  });

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
