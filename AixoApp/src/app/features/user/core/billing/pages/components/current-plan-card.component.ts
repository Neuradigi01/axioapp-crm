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
      'bg-red-500/10 text-red-400 ring-red-500/20 dark:bg-red-300 dark:text-red-500/30 dark:ring-red-300',
  },
  archived: {
    label: 'Archived',
    pillClasses: 'bg-surface-2 text-default border-subtle dark:ring-slate-600',
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
    <section class="flex h-full flex-col rounded-2xl border border-subtle bg-surface p-5 shadow-sm">
      <div class="flex items-start justify-between gap-3">
        <p class="text-[13px] font-semibold text-default">Current plan</p>
        <span
          class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ring-1"
          [class]="statusTone().pillClasses"
        >
          {{ statusTone().label }}
        </span>
      </div>

      @if (priceHeadline(); as price) {
        <div class="mt-4 flex items-baseline gap-1">
          <span class="font-display text-[32px] font-bold leading-none tabular-nums text-default">
            ₹{{ formatINR(price.amount) }}
          </span>
          <span class="font-mono text-[12px] text-faint">/{{ price.cycleLabel }}</span>
        </div>
      } @else {
        <div class="mt-4 flex items-baseline gap-1">
          <span class="font-display text-[32px] font-bold leading-none text-default">
            {{ subscription().plan.name }}
          </span>
        </div>
      }

      <p class="mt-2 text-[13px] text-muted">
        @if (priceHeadline()) {
          {{ subscription().plan.name }} · {{ contextLine() }}
        } @else {
          {{ contextLine() }}
        }
      </p>

      <button
        type="button"
        (click)="onUpgrade()"
        class="mt-5 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-2.5 text-[13px] font-semibold text-white shadow-sm transition hover:brightness-95"
      >
        Upgrade now
      </button>
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
