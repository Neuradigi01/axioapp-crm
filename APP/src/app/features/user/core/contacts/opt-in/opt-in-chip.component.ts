import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';

import { WhatsAppOptInStatus } from '../contacts-api.service';

/**
 * Status chip for the contacts list + detail header (Step 22).
 *
 * Four states; classes match the broader Tailwind palette used
 * across the user app. The "Never contacted" pill is intentionally
 * the zinc default — it's the new-contact baseline, not a
 * warning, and we don't want to scream at every fresh CRM lead.
 */
@Component({
  selector: 'app-opt-in-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <span
      [class]="
        'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ' +
        classes()
      "
      [title]="title()"
    >
      {{ label() }}
    </span>
  `,
})
export class OptInChipComponent {
  readonly status = input<WhatsAppOptInStatus | null | undefined>(
    'never_contacted',
  );

  protected readonly label = computed(() => {
    switch (this.status()) {
      case 'opted_in':
        return 'Opted in';
      case 'opted_out':
        return 'Opted out';
      case 'implicit':
        return 'Implicit';
      default:
        return 'Never contacted';
    }
  });

  protected readonly classes = computed(() => {
    switch (this.status()) {
      case 'opted_in':
        return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
      case 'opted_out':
        return 'bg-rose-50 text-rose-700 ring-rose-200';
      case 'implicit':
        return 'bg-amber-50 text-amber-700 ring-amber-200';
      default:
        return 'bg-zinc-100 text-zinc-600 ring-zinc-200';
    }
  });

  protected readonly title = computed(() => {
    switch (this.status()) {
      case 'opted_in':
        return 'Explicit consent captured — campaign sends proceed.';
      case 'opted_out':
        return 'Opted out — every campaign send is blocked.';
      case 'implicit':
        return 'No explicit consent record — campaigns show a warning.';
      default:
        return 'Never contacted on WhatsApp.';
    }
  });
}
