import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import { FeatureAccessService, PlanCode } from '../../services/feature-access.service';
import { UpgradeModalService } from '../../services/upgrade-modal.service';

export type LockedFeatureVariant = 'page' | 'inline';

/**
 * Reusable "upgrade to unlock" surface.
 *
 * Two visual variants:
 *   - `'page'` (default) — full-bleed centered card with illustration.
 *     Use when an entire route is gated.
 *   - `'inline'` — compact card without illustration. Use when one
 *     section inside an existing page is gated.
 *
 * The component is dumb — it renders the locked state every time it
 * is mounted. The "should we render this at all?" question belongs
 * to the caller (use `*crmRequiresFeature` for that). The component
 * still validates `requiredPlan` against the known tier list and
 * logs a console error on typos so misconfigured callers fail loud
 * in dev.
 */
@Component({
  selector: 'crm-locked-feature',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './locked-feature.component.html',
  styleUrl: './locked-feature.component.css',
})
export class LockedFeatureComponent {
  private readonly access = inject(FeatureAccessService);
  private readonly upgradeModal = inject(UpgradeModalService);

  /** The feature key the surface is gated on. Used to look up the
   *  default `requiredPlan` and as a console-log hint when the caller
   *  ships a typo. */
  readonly feature = input<string | null>(null);

  /** Plan code the upgrade CTA targets. If omitted, derived from
   *  `feature` via the entitlement registry. */
  readonly requiredPlan = input<PlanCode | null>(null);

  /** Headline shown above the description. Caller-supplied so each
   *  surface can speak to its own use case. */
  readonly title = input<string>('Unlock this feature');

  /** Body copy. Plain text — no HTML rendering — to keep this
   *  component XSS-safe by construction. */
  readonly description = input<string>(
    'Available on a higher plan. Upgrade to enable it for your team.',
  );

  /** Optional SVG path relative to `/assets/`. Hidden on `inline`
   *  variant regardless. */
  readonly illustrationUrl = input<string | null>(null);

  readonly variant = input<LockedFeatureVariant>('page');

  protected readonly resolvedPlan = computed<PlanCode>(() => {
    const explicit = this.requiredPlan();
    if (explicit !== null) return explicit;
    const featureKey = this.feature();
    if (featureKey !== null) {
      const fromRegistry = this.access.requiredPlanFor(featureKey);
      if (fromRegistry !== null) return fromRegistry;
      // eslint-disable-next-line no-console
      console.warn(
        `crm-locked-feature: unknown feature key %o — falling back to "standard".`,
        featureKey,
      );
    }
    return 'standard';
  });

  protected readonly planLabel = computed<string>(() => this.access.labelFor(this.resolvedPlan()));

  protected onUpgrade(): void {
    this.upgradeModal.open({ plan: this.resolvedPlan() });
  }
}
