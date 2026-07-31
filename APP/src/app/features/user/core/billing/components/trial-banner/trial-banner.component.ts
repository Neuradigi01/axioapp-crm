import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { SubscriptionStateService } from '../../services/subscription-state.service';
import { UpgradeModalService } from '../../services/upgrade-modal.service';
import { SubscriptionCurrent, SubscriptionStatus } from '../../types/subscription.types';

/** What the template renders for a given subscription state.
 *
 *  `ctaAction` decides what the button does:
 *    - `'upgrade'` opens the Step 17 upgrade modal (trial / read_only)
 *    - `'billing'` navigates to the in-app billing page (past_due
 *      needs payment-method management; archived / cancelled need
 *      operator contact via the page's footer copy)
 */
interface BannerViewModel {
  tone: 'info' | 'warning' | 'urgent';
  message: string;
  ctaLabel: string;
  ctaAction: 'upgrade' | 'billing';
}

/** Days-remaining threshold below which the trial banner flips from
 *  informational blue to a warning yellow. The countdown is computed
 *  server-side (Step 7) so we trust whatever the API hands back. */
const TRIAL_WARNING_THRESHOLD_DAYS = 3;

/**
 * Persistent status ribbon shown on every `/user/...` route.
 *
 * Reads the shared `SubscriptionStateService` and renders one of four
 * banner shapes depending on `subscription.status`:
 *
 *   - `trialing` with > 3 days  → info (blue)
 *   - `trialing` with ≤ 3 days → warning (yellow)
 *   - `read_only` (trial ended) → urgent (red)
 *   - `past_due`                 → urgent (red, "payment failed" copy)
 *   - `archived` / `cancelled`   → urgent (red, "contact support" copy)
 *   - `active`                   → hidden (returns `null` view model;
 *                                  the template omits the DOM so the
 *                                  layout has zero banner height)
 *
 * The Upgrade CTA either opens the upgrade modal directly (trial /
 * read_only) or navigates to the Billing page at `/user/subscription`
 * (past_due needs payment-method management; archived / cancelled
 * need operator contact via the page footer copy).
 */
@Component({
  selector: 'crm-trial-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './trial-banner.component.html',
  styleUrl: './trial-banner.component.css',
})
export class TrialBannerComponent {
  private readonly subscription = inject(SubscriptionStateService);
  private readonly upgradeModal = inject(UpgradeModalService);
  private readonly router = inject(Router);

  protected readonly vm = computed<BannerViewModel | null>(() => {
    const sub = this.subscription.current();
    if (sub === null) return null;
    return buildViewModel(sub);
  });

  protected onCta(): void {
    const banner = this.vm();
    if (banner === null) return;
    if (banner.ctaAction === 'upgrade') {
      this.upgradeModal.open();
      return;
    }
    this.router.navigateByUrl('/user/subscription');
  }

  /** Container classes per tone. Info uses the accent-soft AIXO strip;
   *  warning / urgent keep amber / red semantics via Tailwind's palette
   *  because those states are not accent-colored. Kept in the component
   *  (not the template) so the palette is greppable in one place. */
  protected readonly toneClasses = computed<string>(() => {
    const tone = this.vm()?.tone;
    switch (tone) {
      case 'warning':
        return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
      case 'urgent':
        return 'bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20';
      case 'info':
      default:
        return 'bg-accent-soft text-default border-subtle';
    }
  });

  protected readonly ctaClasses = computed<string>(() => {
    const tone = this.vm()?.tone;
    switch (tone) {
      case 'warning':
        return 'text-amber-700 dark:text-amber-300 hover:opacity-80';
      case 'urgent':
        return 'text-red-700 dark:text-red-300 hover:opacity-80';
      case 'info':
      default:
        return 'text-accent hover:opacity-80';
    }
  });
}

// ---------------------------------------------------------------------------
// View-model builders — kept as plain functions so the template only
// reads from one `vm` signal and the per-status copy lives next to the
// tone choice that goes with it.
// ---------------------------------------------------------------------------

function buildViewModel(sub: SubscriptionCurrent): BannerViewModel | null {
  switch (sub.status) {
    case 'active':
      return null;
    case 'trialing':
      return makeTrialVM(sub);
    case 'read_only':
      return makeExpiredVM();
    case 'past_due':
      return makePaymentFailedVM();
    case 'archived':
      return makeFinalStateVM('archived');
    case 'cancelled':
      return makeFinalStateVM('cancelled');
    default:
      return null;
  }
}

function makeTrialVM(sub: SubscriptionCurrent): BannerViewModel {
  // `trial` is guaranteed non-null when status is `trialing`, but the
  // type-system lets it be null so we default defensively.
  const daysRemaining = sub.trial?.days_remaining ?? 0;
  const isUrgent = daysRemaining <= TRIAL_WARNING_THRESHOLD_DAYS;
  const dayWord = daysRemaining === 1 ? 'day' : 'days';
  const planName = sub.plan?.name ?? 'Trial';
  return {
    tone: isUrgent ? 'warning' : 'info',
    message: isUrgent
      ? `Only ${daysRemaining} ${dayWord} left on your ${planName} trial.`
      : `You're on the ${planName} trial — ${daysRemaining} ${dayWord} left.`,
    ctaLabel: 'Upgrade',
    ctaAction: 'upgrade',
  };
}

function makeExpiredVM(): BannerViewModel {
  return {
    tone: 'urgent',
    message: 'Your trial has ended. Upgrade to continue using CRM.',
    ctaLabel: 'Upgrade',
    ctaAction: 'upgrade',
  };
}

function makePaymentFailedVM(): BannerViewModel {
  return {
    tone: 'urgent',
    message: 'Payment failed. Update your card to keep your subscription.',
    ctaLabel: 'Update payment',
    ctaAction: 'billing',
  };
}

function makeFinalStateVM(
  state: Extract<SubscriptionStatus, 'archived' | 'cancelled'>,
): BannerViewModel {
  return {
    tone: 'urgent',
    message: `Your account is ${state}.`,
    ctaLabel: 'Contact support',
    ctaAction: 'billing',
  };
}
