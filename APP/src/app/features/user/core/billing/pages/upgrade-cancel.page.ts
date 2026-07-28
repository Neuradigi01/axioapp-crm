import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';

import { UpgradeModalService } from '../services/upgrade-modal.service';

/**
 * Brief landing page Stripe Checkout redirects to when the user
 * cancels payment. Mirrors the visual frame of `upgrade-success` so
 * the round-trip feels intentional rather than a 404 bounce.
 *
 * "Try again" re-opens the upgrade modal from this same page — the
 * user lands on `/user/subscription/upgrade-cancel` with the modal
 * already surfaced and can adjust their picks. Hitting Cancel inside
 * the modal returns them to this page; hitting Back navigates to the
 * Billing page.
 */
@Component({
  selector: 'crm-upgrade-cancel-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="min-h-[calc(100vh-4rem)] flex items-center justify-center p-6">
      <div
        class="w-full max-w-md rounded-2xl border border-subtle bg-surface p-8 text-center shadow-sm"
      >
        <div
          class="mx-auto inline-flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-2xl text-muted"
          aria-hidden="true"
        >
          ↺
        </div>
        <h1 class="mt-4 text-lg font-semibold text-default">Upgrade cancelled</h1>
        <p class="mt-2 text-sm text-muted">
          You weren't charged. Pick up where you left off or head back to Billing.
        </p>
        <div class="mt-5 flex items-center justify-center gap-2">
          <a
            routerLink="/user/subscription"
            class="rounded-lg px-4 py-2 text-sm font-semibold text-default hover:bg-surface-2"
          >
            Back to Billing
          </a>
          <button
            type="button"
            (click)="retry()"
            class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700"
          >
            Try again
          </button>
        </div>
      </div>
    </div>
  `,
})
export class UpgradeCancelPage {
  private readonly upgradeModal = inject(UpgradeModalService);

  protected retry(): void {
    this.upgradeModal.open();
  }
}
