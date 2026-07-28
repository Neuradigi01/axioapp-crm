import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { WhatsAppOptInSource } from '../contacts-api.service';

interface SourceOption {
  value: WhatsAppOptInSource;
  label: string;
  hint: string;
}

const SOURCES: SourceOption[] = [
  {
    value: 'bulk_import',
    label: 'Existing CRM (already had consent)',
    hint: 'Default for migrated contacts — backfills as "implicit". The campaign guard warns before send.',
  },
  {
    value: 'explicit_opt_in_link',
    label: 'Customer clicked opt-in link',
    hint: 'Explicit consent captured on a landing page or QR scan. Marketing campaigns proceed without a warning.',
  },
  {
    value: 'manual_entry',
    label: 'Captured manually (call / in-store)',
    hint: 'Staff verbally captured consent. Recorded as explicit opt-in.',
  },
  {
    value: 'form_widget',
    label: 'Website form (paper-trail in JSON)',
    hint: 'Audit-grade: every imported row needs a matching consent screenshot or form submission id.',
  },
];

/**
 * Mandatory "opt-in source" step on the bulk-import wizard (Step 22).
 *
 * Rendered between mapping and dry-run. The picked source maps to:
 *
 *   * ``bulk_import``           → contact stays ``implicit`` (warn on send).
 *   * everything else           → contact promoted to ``opted_in``.
 *
 * The wizard's "Continue" button is disabled until a selection is made
 * — the DPDP rationale being: bulk-imported contacts must carry a
 * consent provenance for every row before they enter the marketing
 * funnel.
 */
@Component({
  selector: 'app-bulk-import-opt-in-step',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <fieldset class="rounded-md border border-subtle bg-surface-2 p-3">
      <legend class="px-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
        WhatsApp opt-in source
        <span class="ml-1 text-rose-600">*</span>
      </legend>
      <p class="mb-2 text-[11px] text-muted">
        How was consent captured for these contacts? DPDP requires a recorded provenance for every
        imported row.
      </p>
      <div class="space-y-1.5">
        @for (s of SOURCES; track s.value) {
          <label
            class="flex cursor-pointer items-start gap-2 rounded border border-subtle bg-surface px-2.5 py-2 text-xs transition hover:border-subtle"
            [class.border-accent]="selected() === s.value"
          >
            <input
              type="radio"
              name="bulk-opt-in-source"
              class="mt-0.5"
              [checked]="selected() === s.value"
              (change)="onPick(s.value)"
            />
            <span class="flex flex-col">
              <span class="font-medium text-default">{{ s.label }}</span>
              <span class="text-[11px] text-muted">{{ s.hint }}</span>
            </span>
          </label>
        }
      </div>
    </fieldset>
  `,
})
export class BulkImportOptInStepComponent {
  readonly selected = input<WhatsAppOptInSource | null>(null);
  readonly pick = output<WhatsAppOptInSource>();

  protected readonly SOURCES = SOURCES;

  protected onPick(value: WhatsAppOptInSource): void {
    this.pick.emit(value);
  }
}
