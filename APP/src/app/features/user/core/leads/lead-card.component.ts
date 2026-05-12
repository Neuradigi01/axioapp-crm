import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { InrPipe } from '../shared/pipes/inr.pipe';
import { Lead, LeadStatus } from './leads-api.service';

/**
 * Small read-only card rendered inside each kanban column for a lead.
 *
 * Inputs:
 *   - `lead`: the lead row to display.
 *   - `contactName` / `contactPhone` / `contactSource`: looked up by
 *     the parent (the leads page caches contacts so we don't N+1).
 *
 * Source icon: a small set of common sources get a lucide icon
 * (walk-in → footprints, referral → user-plus); anything else falls
 * back to the source text. The card stays compact so multiple cards
 * fit comfortably per column on a kanban board.
 */
const SOURCE_ICONS: Record<string, string> = {
  walk_in: 'footprints',
  walkin: 'footprints',
  referral: 'user-plus',
  phone: 'phone',
  whatsapp: 'message-circle',
  email: 'mail',
};

@Component({
  selector: 'app-lead-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, InrPipe],
  templateUrl: './lead-card.component.html',
})
export class LeadCardComponent {
  readonly lead = input.required<Lead>();
  readonly contactName = input<string | null>(null);
  readonly contactPhone = input<string | null>(null);
  readonly contactSource = input<string | null>(null);

  readonly sourceIcon = computed<string | null>(() => {
    const src = this.contactSource();
    return src ? SOURCE_ICONS[src] ?? null : null;
  });

  readonly initials = computed(() => {
    const name = this.contactName() ?? '?';
    return name
      .split(/\s+/)
      .filter((p) => p.length > 0)
      .slice(0, 2)
      .map((p) => p[0]!.toUpperCase())
      .join('');
  });

  readonly statusPillClass = computed(() => this.classForStatus(this.lead().status));

  private classForStatus(status: LeadStatus): string {
    switch (status) {
      case 'won':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'lost':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }
}
