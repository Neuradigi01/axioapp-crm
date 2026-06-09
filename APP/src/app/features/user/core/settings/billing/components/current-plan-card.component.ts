import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
} from '@angular/core';

import { UpgradeModalService } from '../../../billing/services/upgrade-modal.service';
import { SubscriptionCurrent } from '../../../billing/types/subscription.types';

/**
 * Top card on the Billing settings page.
 *
 * Renders plan name + per-status context (trial countdown / cycle
 * cost / renewal date) plus the primary "Upgrade plan" CTA. The CTA
 * is currently disabled — Step 17 will wire the upgrade modal and
 * enable it.
 */
@Component({
  selector: 'crm-current-plan-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400">
            Current plan
          </p>
          <h2 class="mt-1 text-xl font-semibold text-zinc-900 dark:text-slate-100">
            {{ subscription().plan.name }}
          </h2>
          <p class="mt-1 text-sm text-zinc-500 dark:text-slate-400">
            {{ contextLine() }}
          </p>
        </div>

        <button
          type="button"
          (click)="onUpgrade()"
          class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-zinc-800"
        >
          Upgrade plan
        </button>
      </div>

      <dl class="mt-6 grid gap-4 sm:grid-cols-2">
        @for (row of detailRows(); track row.label) {
          <div>
            <dt class="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400">
              {{ row.label }}
            </dt>
            <dd class="mt-1 text-sm font-medium text-zinc-900 dark:text-slate-100">
              {{ row.value }}
            </dd>
          </div>
        }
      </dl>
    </section>
  `,
})
export class CurrentPlanCardComponent {
  private readonly upgradeModal = inject(UpgradeModalService);

  readonly subscription = input.required<SubscriptionCurrent>();

  protected onUpgrade(): void {
    // Pre-fill the modal with the current cycle so changing plans
    // inside the same cycle is a single click; the user can flip the
    // toggle if they want to switch.
    const sub = this.subscription();
    this.upgradeModal.open({ cycle: sub.billing_cycle });
  }

  /** Headline copy under the plan name. Differs by status:
   *   - trialing → "N days left in trial"
   *   - active → "$X/mo, renews on YYYY-MM-DD"
   *   - read_only / past_due / archived / cancelled → human-readable
   *     state description; the trial banner (Step 15) carries the
   *     urgent CTA so this card stays informational.
   */
  protected readonly contextLine = computed(() => {
    const sub = this.subscription();
    switch (sub.status) {
      case 'trialing': {
        const days = sub.trial?.days_remaining ?? 0;
        return `${days} day${days === 1 ? '' : 's'} remaining in your trial`;
      }
      case 'active': {
        const price = this.cyclePrice(sub);
        const cycleLabel = sub.billing_cycle === 'annual' ? 'yr' : 'mo';
        const renews = formatDate(sub.period.renews_at);
        return `$${price}/${cycleLabel}, renews on ${renews}`;
      }
      case 'past_due':
        return 'Payment failed — update your card to continue';
      case 'read_only':
        return 'Trial ended — upgrade to restore write access';
      case 'archived':
        return 'Account archived — contact support to restore';
      case 'cancelled':
        return 'Subscription cancelled';
      default:
        return '';
    }
  });

  protected readonly detailRows = computed(() => {
    const sub = this.subscription();
    const rows: Array<{ label: string; value: string }> = [];
    if (sub.status === 'trialing' && sub.trial !== null) {
      rows.push({ label: 'Trial started', value: formatDate(sub.trial.started_at) });
      rows.push({ label: 'Trial ends', value: formatDate(sub.trial.ends_at) });
    } else {
      rows.push({ label: 'Billing cycle', value: capitalize(sub.billing_cycle) });
      rows.push({ label: 'Current period ends', value: formatDate(sub.period.end) });
    }
    return rows;
  });

  private cyclePrice(sub: SubscriptionCurrent): number {
    return sub.billing_cycle === 'annual'
      ? sub.plan.annual_bundle_usd
      : sub.plan.monthly_bundle_usd;
  }
}


/** ISO-8601 string → `YYYY-MM-DD`. The page is admin-facing — short
 *  date is more readable than long-form locale. */
function formatDate(iso: string): string {
  return iso.slice(0, 10);
}


function capitalize(value: string): string {
  return value.length === 0 ? value : value[0].toUpperCase() + value.slice(1);
}
