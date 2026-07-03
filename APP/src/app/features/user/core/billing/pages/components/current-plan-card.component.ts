import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { UpgradeModalService } from '../../services/upgrade-modal.service';
import { SubscriptionCurrent } from '../../types/subscription.types';

interface StatusTone {
  readonly label: string;
  readonly pillClasses: string;
}

const STATUS_TONES: Record<string, StatusTone> = {
  active: {
    label: 'Active',
    pillClasses:
      'bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-900',
  },
  trialing: {
    label: 'Trial',
    pillClasses:
      'bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:ring-blue-900',
  },
  past_due: {
    label: 'Past due',
    pillClasses:
      'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-900',
  },
  read_only: {
    label: 'Read only',
    pillClasses:
      'bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-900',
  },
  cancelled: {
    label: 'Cancelled',
    pillClasses:
      'bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:ring-rose-900',
  },
  archived: {
    label: 'Archived',
    pillClasses:
      'bg-zinc-100 text-zinc-700 ring-zinc-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600',
  },
};

/**
 * Hero card on the Billing settings page.
 *
 * Renders plan name + status pill + headline price + per-status
 * context (trial countdown / renewal date) plus the primary "Upgrade
 * plan" CTA. Detail grid summarises billing cycle and period dates.
 */
@Component({
  selector: 'crm-current-plan-card',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <section
      class="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div class="flex flex-wrap items-start justify-between gap-4 p-6">
        <div class="min-w-0">
          <div class="flex items-center gap-2">
            <p
              class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400"
            >
              Current plan
            </p>
            <span
              class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1"
              [class]="statusTone().pillClasses"
            >
              {{ statusTone().label }}
            </span>
          </div>
          <h2 class="mt-2 text-2xl font-semibold tracking-tight text-zinc-900 dark:text-slate-100">
            {{ subscription().plan.name }}
          </h2>
          @if (priceHeadline(); as price) {
            <div class="mt-2 flex items-baseline gap-1.5">
              <span class="text-3xl font-semibold tabular-nums text-zinc-900 dark:text-slate-100">
                ₹{{ formatINR(price.amount) }}
              </span>
              <span class="text-sm text-zinc-500 dark:text-slate-400">
                {{ '/' + price.cycleLabel }}
              </span>
            </div>
          }
          <p class="mt-2 text-sm text-zinc-600 dark:text-slate-400">
            {{ contextLine() }}
          </p>
        </div>

        <button
          type="button"
          (click)="onUpgrade()"
          class="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-zinc-900 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-zinc-800 dark:bg-white dark:text-zinc-900 dark:hover:bg-zinc-200"
        >
          Upgrade plan
          <lucide-icon name="arrow-right" size="14" aria-hidden="true"></lucide-icon>
        </button>
      </div>

      <dl
        class="grid gap-px border-t border-zinc-200 bg-zinc-200 sm:grid-cols-2 dark:border-slate-700 dark:bg-slate-700"
      >
        @for (row of detailRows(); track row.label) {
          <div class="bg-zinc-50 px-6 py-4 dark:bg-slate-800/60">
            <dt
              class="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-slate-400"
            >
              {{ row.label }}
            </dt>
            <dd class="mt-1 text-sm font-medium tabular-nums text-zinc-900 dark:text-slate-100">
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

  protected readonly statusTone = computed<StatusTone>(() => {
    const s = this.subscription().status;
    return STATUS_TONES[s] ?? STATUS_TONES['archived'];
  });

  /** Headline price block. Hidden for trial / cancelled / archived
   *  where a price isn't meaningful — the context line covers those. */
  protected readonly priceHeadline = computed<{ amount: number; cycleLabel: string } | null>(() => {
    const sub = this.subscription();
    if (sub.status === 'trialing' || sub.status === 'cancelled' || sub.status === 'archived') {
      return null;
    }
    return {
      amount: this.cyclePrice(sub),
      cycleLabel: sub.billing_cycle === 'annual' ? 'yr' : 'mo',
    };
  });

  /** Subhead copy. Differs by status:
   *   - trialing → "N days left in trial"
   *   - active → "Renews on YYYY-MM-DD"
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
      case 'active':
        return `Renews on ${formatDate(sub.period.renews_at)}`;
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
    // India-first CRM → INR. Future currency toggle will pick USD when
    // the user is a global customer.
    return sub.billing_cycle === 'annual'
      ? sub.plan.annual_bundle_inr
      : sub.plan.monthly_bundle_inr;
  }

  protected formatINR(amount: number): string {
    return amount.toLocaleString('en-IN');
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
