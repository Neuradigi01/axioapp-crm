import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Inline opt-in warning rendered above the campaign create / dispatch
 * button (Step 22).
 *
 * Three visual states keyed off the per-status counts the campaign
 * preview endpoint already returns:
 *
 *   * Clean — every audience contact is ``opted_in``. Banner hidden.
 *   * Warn  — implicit / never_contacted contacts in the audience.
 *             Banner is amber: "N contacts will be sent without
 *             explicit consent." Operator can still proceed.
 *   * Block — opted-out contacts in the audience. Banner is rose:
 *             "M contacts will be skipped by the send guard."
 *
 * Implementation note — the campaign create modal already has an
 * audience-size signal; this component is intentionally
 * presentation-only (no fetch, no API calls). The parent computes
 * the counts and passes them in as inputs.
 */
@Component({
  selector: 'app-campaign-opt-in-warning',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    @if (severity() !== 'clean') {
      <div
        [class]="
          'rounded-md border px-3 py-2 text-xs ' +
          (severity() === 'block'
            ? 'border-rose-200 bg-rose-50 text-rose-700'
            : 'border-amber-200 bg-amber-50 text-amber-800')
        "
      >
        <p class="font-semibold">
          {{
            severity() === 'block'
              ? 'Send guard will skip contacts.'
              : 'Sending without explicit consent.'
          }}
        </p>
        <ul class="mt-1 space-y-0.5">
          @if (optedOut() > 0) {
            <li>
              <strong>{{ optedOut() }}</strong> opted-out contacts will be skipped automatically
              (DPDP compliance).
            </li>
          }
          @if (implicit() > 0) {
            <li>
              <strong>{{ implicit() }}</strong> contacts have only implicit consent. Marketing
              templates may be flagged by Meta if recipients report your number.
            </li>
          }
          @if (neverContacted() > 0) {
            <li>
              <strong>{{ neverContacted() }}</strong> contacts have no opt-in record — first
              WhatsApp message from your business.
            </li>
          }
        </ul>
      </div>
    }
  `,
})
export class CampaignOptInWarningComponent {
  readonly optedIn = input<number>(0);
  readonly implicit = input<number>(0);
  readonly optedOut = input<number>(0);
  readonly neverContacted = input<number>(0);

  protected readonly severity = computed<'clean' | 'warn' | 'block'>(() => {
    if (this.optedOut() > 0) return 'block';
    if (this.implicit() > 0 || this.neverContacted() > 0) return 'warn';
    return 'clean';
  });
}
