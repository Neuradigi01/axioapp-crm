import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';

import { InrPipe } from '../shared/pipes/inr.pipe';
import { Lead, LeadStatus } from './leads-api.service';

/**
 * Compact read-only card rendered inside each kanban column for a lead.
 *
 * Matches the reference Vercel UI layout: a colored initials avatar
 * (color derived deterministically from the lead's id so the same
 * card always picks the same colour), the contact's name, the lead's
 * creation date (YYYY-MM-DD), a furniture emoji + product label
 * pulled from `lead.custom_data.product` (falls back to the source
 * when no product is defined), and the budget formatted in
 * Indian-rupee groupings.
 *
 * Inputs are minimal — the parent looks up the contact summary out of
 * its cache and passes the visible fields in.
 */
const AVATAR_PALETTE: ReadonlyArray<string> = [
  'bg-emerald-200 text-emerald-800',
  'bg-sky-200 text-sky-800',
  'bg-amber-200 text-amber-800',
  'bg-rose-200 text-rose-800',
  'bg-violet-200 text-violet-800',
  'bg-cyan-200 text-cyan-800',
  'bg-orange-200 text-orange-800',
  'bg-indigo-200 text-indigo-800',
];

@Component({
  selector: 'app-lead-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe],
  templateUrl: './lead-card.component.html',
})
export class LeadCardComponent {
  readonly lead = input.required<Lead>();
  readonly contactName = input<string | null>(null);
  readonly contactPhone = input<string | null>(null);
  readonly contactSource = input<string | null>(null);

  readonly initials = computed(() => {
    const name = this.contactName() ?? '?';
    return name
      .split(/\s+/)
      .filter((p) => p.length > 0)
      .slice(0, 2)
      .map((p) => p[0]!.toUpperCase())
      .join('');
  });

  /** Deterministic colour pick from `AVATAR_PALETTE` based on lead id. */
  readonly avatarClass = computed(() => {
    const id = this.lead().id;
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) & 0x7fffffff;
    }
    return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
  });

  /** YYYY-MM-DD of the lead's created_at. */
  readonly dateLabel = computed(() => {
    const iso = this.lead().created_at;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  });

  /** Product label pulled from custom_data.product, falls back to source. */
  readonly productLabel = computed<string | null>(() => {
    const product = (this.lead().custom_data as { product?: unknown }).product;
    if (typeof product === 'string' && product.trim().length > 0) return product;
    return this.contactSource();
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
