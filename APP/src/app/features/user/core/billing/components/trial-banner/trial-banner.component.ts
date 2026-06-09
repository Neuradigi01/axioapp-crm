import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';

import { SubscriptionStateService } from '../../services/subscription-state.service';
import {
  SubscriptionCurrent,
  SubscriptionStatus,
} from '../../types/subscription.types';

/** What the template renders for a given subscription state. */
interface BannerViewModel {
  tone: 'info' | 'warning' | 'urgent';
  message: string;
  ctaLabel: string;
  ctaTarget: string;
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
 * The Upgrade CTA targets the in-app billing page at
 * `/user/settings/billing` for now. Step 17 will swap this for an
 * `(click)` that opens the upgrade modal.
 */
@Component({
  selector: 'crm-trial-banner',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, RouterLink],
  templateUrl: './trial-banner.component.html',
  styleUrl: './trial-banner.component.css',
})
export class TrialBannerComponent {
  private readonly subscription = inject(SubscriptionStateService);

  protected readonly vm = computed<BannerViewModel | null>(() => {
    const sub = this.subscription.current();
    if (sub === null) return null;
    return buildViewModel(sub);
  });

  /** Container classes per tone — kept in the component (not the
   *  template) so the colour palette is greppable in one place. */
  protected readonly toneClasses = computed<string>(() => {
    const tone = this.vm()?.tone;
    switch (tone) {
      case 'warning':
        return 'bg-amber-50 dark:bg-amber-950 text-amber-900 dark:text-amber-200 border-amber-200 dark:border-amber-800';
      case 'urgent':
        return 'bg-red-50 dark:bg-red-950 text-red-900 dark:text-red-200 border-red-200 dark:border-red-900';
      case 'info':
      default:
        return 'bg-blue-50 dark:bg-blue-950 text-blue-900 dark:text-blue-200 border-blue-200 dark:border-blue-900';
    }
  });

  protected readonly ctaClasses = computed<string>(() => {
    const tone = this.vm()?.tone;
    switch (tone) {
      case 'warning':
        return 'bg-amber-600 hover:bg-amber-700 text-white';
      case 'urgent':
        return 'bg-red-600 hover:bg-red-700 text-white';
      case 'info':
      default:
        return 'bg-blue-600 hover:bg-blue-700 text-white';
    }
  });
}


// ---------------------------------------------------------------------------
// View-model builders — kept as plain functions so the template only
// reads from one `vm` signal and the per-status copy lives next to the
// tone choice that goes with it.
// ---------------------------------------------------------------------------


function buildViewModel(
  sub: SubscriptionCurrent,
): BannerViewModel | null {
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
  return {
    tone: isUrgent ? 'warning' : 'info',
    message: isUrgent
      ? `Only ${daysRemaining} ${dayWord} left on your trial.`
      : `You're on a 14-day trial. ${daysRemaining} ${dayWord} left.`,
    ctaLabel: 'Upgrade',
    ctaTarget: '/user/settings/billing',
  };
}


function makeExpiredVM(): BannerViewModel {
  return {
    tone: 'urgent',
    message: 'Your trial has ended. Upgrade to continue using CRM.',
    ctaLabel: 'Upgrade',
    ctaTarget: '/user/settings/billing',
  };
}


function makePaymentFailedVM(): BannerViewModel {
  return {
    tone: 'urgent',
    message: 'Payment failed. Update your card to keep your subscription.',
    ctaLabel: 'Update payment',
    ctaTarget: '/user/settings/billing',
  };
}


function makeFinalStateVM(
  state: Extract<SubscriptionStatus, 'archived' | 'cancelled'>,
): BannerViewModel {
  return {
    tone: 'urgent',
    message: `Your account is ${state}.`,
    ctaLabel: 'Contact support',
    ctaTarget: '/user/settings/billing',
  };
}
