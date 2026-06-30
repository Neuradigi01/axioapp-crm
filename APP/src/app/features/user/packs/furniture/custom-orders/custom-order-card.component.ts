import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { CustomOrder } from './custom-orders-api.service';
import { fmtInr } from '@core/services/currency.util';

/**
 * Single kanban card for a Custom Order. Dumb component â€” gets the
 * row + an optional resolved contact-name pre-loaded by the parent.
 *
 * Layout matches the Vercel reference: title + status badge on top,
 * customer chip, materials/color row, total + advance, expected
 * delivery date, and progress hint (stage index / total).
 */
@Component({
  selector: 'app-custom-order-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './custom-order-card.component.html',
})
export class CustomOrderCardComponent {
  readonly order = input.required<CustomOrder>();
  readonly contactName = input<string | null>(null);
  readonly contactPhone = input<string | null>(null);
  readonly stageIndex = input<number | null>(null);
  readonly stageTotal = input<number | null>(null);

  protected readonly amountInr = computed(() => fmtInr(this.order().total_amount));
  protected readonly advanceInr = computed(() => fmtInr(this.order().advance_paid));

  protected readonly outstanding = computed(() => {
    const total = Number(this.order().total_amount ?? 0);
    const paid = Number(this.order().advance_paid ?? 0);
    const due = Math.max(total - paid, 0);
    return fmtInr(String(due));
  });

  protected readonly materialsSummary = computed(() => {
    const m = this.order().materials ?? {};
    const parts: string[] = [];
    for (const [k, v] of Object.entries(m)) {
      if (v === null || v === undefined || v === '') continue;
      parts.push(`${k}: ${String(v)}`);
    }
    return parts.join(' Â· ');
  });

  protected readonly deliveryLabel = computed(() => {
    const d = this.order().expected_delivery_date;
    if (!d) return null;
    const dt = new Date(d);
    if (Number.isNaN(dt.getTime())) return d;
    return dt.toLocaleDateString('en-IN', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  });

  protected readonly progressPercent = computed(() => {
    const idx = this.stageIndex();
    const total = this.stageTotal();
    if (idx === null || total === null || total <= 0) return null;
    return Math.round(((idx + 1) / total) * 100);
  });

  protected readonly stageBadgeClass = computed(() => {
    switch (this.order().pipeline_stage) {
      case 'measurement_scheduled':
        return 'bg-sky-100 text-sky-700 ring-sky-200';
      case 'design_phase':
        return 'bg-violet-100 text-violet-700 ring-violet-200';
      case 'in_production':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'qc':
        return 'bg-pink-100 text-pink-700 ring-pink-200';
      case 'installation':
        return 'bg-blue-100 text-blue-700 ring-blue-200';
      case 'delivered':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'cancelled':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  });

  protected readonly stageLabel = computed(() => {
    return this.titleCase(this.order().pipeline_stage.replace(/_/g, ' '));
  });

  private titleCase(s: string): string {
    return s.replace(/\b\w/g, (c) => c.toUpperCase());
  }
}
