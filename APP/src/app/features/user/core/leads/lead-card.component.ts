import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Output,
  computed,
  inject,
  input,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { FurnitureAuthService } from '../auth/auth.service';
import { InrPipe } from '../shared/pipes/inr.pipe';
import { RelativeTimePipe } from '../shared/pipes/relative-time.pipe';
import { Lead, LeadSource, LeadStatus } from './leads-api.service';

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
  'bg-red-500/20 text-red-400',
  'bg-violet-200 text-violet-800',
  'bg-cyan-200 text-cyan-800',
  'bg-orange-200 text-orange-800',
  'bg-indigo-200 text-indigo-800',
];

@Component({
  selector: 'app-lead-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe, RelativeTimePipe, LucideAngularModule],
  templateUrl: './lead-card.component.html',
})
export class LeadCardComponent {
  private readonly auth = inject(FurnitureAuthService);

  readonly lead = input.required<Lead>();
  readonly contactName = input<string | null>(null);
  readonly contactPhone = input<string | null>(null);
  readonly contactSource = input<string | null>(null);
  /** Display label for the lead's owner — looked up by the parent
   * (leads.page.ts) from its `userMap` so the card stays dumb. */
  readonly ownerName = input<string | null>(null);

  /** Emitted when the pencil-reassign button on the card is clicked.
   * Parent (pipeline board template) opens the shared ReassignModal. */
  @Output() readonly reassignClick = new EventEmitter<MouseEvent>();

  /** Card-level permission gate — junior reps see no pencil. */
  protected readonly canReassign = computed(() => this.auth.hasPermission('leads.reassign'));

  protected onReassignClick(event: MouseEvent): void {
    // Stop the parent <button (click)="openEdit(item)"> from firing.
    event.stopPropagation();
    this.reassignClick.emit(event);
  }

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

  /**
   * F24 — stale deal warning. Returns a level:
   *   - `stale`   — no activity for ≥ 14 days (amber dot)
   *   - `rotten`  — no activity for ≥ 30 days (rose dot)
   *   - `null`    — fresh / won / lost / never-touched
   *
   * `never-touched` (last_activity_at is null) is intentionally not
   * flagged: a brand-new lead created seconds ago hasn't earned a
   * warning yet. The daily-scan Celery job could later paint these
   * amber too if the create-time is stale, but this v1 just uses
   * activity recency.
   */
  readonly stalenessLevel = computed<'stale' | 'rotten' | null>(() => {
    const lead = this.lead();
    if (lead.status !== 'active') return null;
    if (!lead.last_activity_at) return null;
    const ageMs = Date.now() - new Date(lead.last_activity_at).getTime();
    const days = ageMs / (1000 * 60 * 60 * 24);
    if (days >= 30) return 'rotten';
    if (days >= 14) return 'stale';
    return null;
  });

  readonly stalenessDotClass = computed(() => {
    switch (this.stalenessLevel()) {
      case 'rotten':
        return 'bg-red-500';
      case 'stale':
        return 'bg-amber-500';
      default:
        return null;
    }
  });

  readonly stalenessTooltip = computed(() => {
    switch (this.stalenessLevel()) {
      case 'rotten':
        return 'No activity in 30+ days — deal likely rotten';
      case 'stale':
        return 'No activity in 14+ days — stale';
      default:
        return null;
    }
  });

  /** Tailwind classes for the per-source badge. */
  readonly sourceBadgeClass = computed(() => this.classForSource(this.lead().source));

  /** Human label for the per-source badge. */
  readonly sourceBadgeLabel = computed(() => this.labelForSource(this.lead().source));

  private classForStatus(status: LeadStatus): string {
    switch (status) {
      case 'won':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'lost':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  private classForSource(source: LeadSource | undefined): string {
    switch (source) {
      case 'bulk_import':
        return 'bg-indigo-100 text-indigo-700 ring-indigo-200';
      case 'widget':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'google_ads':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'meta_ads':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      case 'whatsapp_flow':
        return 'bg-green-100 text-green-700 ring-green-200';
      case 'walk_in':
        return 'bg-teal-100 text-teal-700 ring-teal-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  private labelForSource(source: LeadSource | undefined): string {
    switch (source) {
      case 'bulk_import':
        return 'Bulk import';
      case 'widget':
        return 'Widget';
      case 'google_ads':
        return 'Google Ads';
      case 'meta_ads':
        return 'Meta Ads';
      case 'whatsapp_flow':
        return 'WhatsApp Flow';
      case 'walk_in':
        return 'Walk-in';
      default:
        return 'Manual';
    }
  }
}
