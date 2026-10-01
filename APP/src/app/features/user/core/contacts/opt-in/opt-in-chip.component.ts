import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { EmailOptInStatus, WhatsAppOptInStatus } from '../contacts-api.service';

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
  readonly status = input<WhatsAppOptInStatus | EmailOptInStatus | null | undefined>(
    'never_contacted',
  );
  /** Campaigns v1 Step 06 — same chip drives the Email opt-in badge.
   *  Only the tooltip mentions the channel; palette + labels stay
   *  identical because the state machines mirror each other. */
  readonly channel = input<'whatsapp' | 'email'>('whatsapp');

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
        return 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20 dark:text-emerald-300';
      case 'opted_out':
        return 'bg-red-500/10 text-red-700 ring-red-500/20 dark:text-red-300';
      case 'implicit':
        return 'bg-amber-500/10 text-amber-700 ring-amber-500/20 dark:text-amber-300';
      default:
        return 'bg-surface-2 text-muted ring-subtle';
    }
  });

  protected readonly title = computed(() => {
    const channelLabel = this.channel() === 'email' ? 'Email' : 'WhatsApp';
    switch (this.status()) {
      case 'opted_in':
        return `Explicit ${channelLabel} consent captured — campaign sends proceed.`;
      case 'opted_out':
        return `Opted out of ${channelLabel} — every campaign send is blocked.`;
      case 'implicit':
        return `No explicit ${channelLabel} consent record — campaigns show a warning.`;
      default:
        return `Never contacted on ${channelLabel}.`;
    }
  });
}
