import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, Input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

export type KpiFormat = 'number' | 'currency' | 'percent';
export type KpiDeltaDirection = 'up' | 'down' | 'flat';

/**
 * Pure presentation tile for a single KPI: big number, label, optional
 * delta pill (top-right), optional link wrap. Skeleton state when the
 * parent is still loading. Wires up in Step 5 against `/dashboard/summary`.
 *
 * Formatting:
 *   number   → `Intl.NumberFormat` (locale-default grouping).
 *   currency → `Intl.NumberFormat` INR, no fractional digits, matches
 *              the existing dashboard's `formatCurrency` helper.
 *   percent  → number + `%`, one decimal place when the value has one.
 */
@Component({
  selector: 'app-dashboard-kpi-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink],
  templateUrl: './dashboard-kpi-tile.component.html',
})
export class DashboardKpiTileComponent {
  @Input({ required: true })
  set label(value: string) {
    this._label.set(value);
  }
  get label(): string {
    return this._label();
  }

  @Input({ required: true })
  set value(value: number | string) {
    this._value.set(value);
  }
  get value(): number | string {
    return this._value();
  }

  @Input()
  set format(value: KpiFormat) {
    this._format.set(value);
  }
  get format(): KpiFormat {
    return this._format();
  }

  @Input()
  set deltaPct(value: number | null) {
    this._deltaPct.set(value);
  }
  get deltaPct(): number | null {
    return this._deltaPct();
  }

  @Input()
  set deltaDirection(value: KpiDeltaDirection | null) {
    this._deltaDirection.set(value);
  }
  get deltaDirection(): KpiDeltaDirection | null {
    return this._deltaDirection();
  }

  @Input()
  set link(value: string | null) {
    this._link.set(value);
  }
  get link(): string | null {
    return this._link();
  }

  @Input()
  set loading(value: boolean) {
    this._loading.set(value);
  }
  get loading(): boolean {
    return this._loading();
  }

  private readonly _label = signal<string>('');
  private readonly _value = signal<number | string>(0);
  private readonly _format = signal<KpiFormat>('number');
  private readonly _deltaPct = signal<number | null>(null);
  private readonly _deltaDirection = signal<KpiDeltaDirection | null>(null);
  private readonly _link = signal<string | null>(null);
  private readonly _loading = signal<boolean>(false);

  protected readonly formattedValue = computed(() => {
    const raw = this._value();
    const fmt = this._format();
    if (fmt === 'currency') return this.formatCurrency(raw);
    if (fmt === 'percent') return this.formatPercent(raw);
    return this.formatNumber(raw);
  });

  protected readonly deltaLabel = computed(() => {
    const dir = this._deltaDirection();
    const pct = this._deltaPct();
    if (dir === null || pct === null) return null;
    const arrow = dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→';
    return `${arrow} ${Math.abs(pct).toFixed(1)}%`;
  });

  protected readonly deltaPillClass = computed(() => {
    const dir = this._deltaDirection();
    if (dir === 'up') return 'bg-emerald-50 text-emerald-700 ring-emerald-200';
    if (dir === 'down') return 'bg-rose-50 text-rose-700 ring-rose-200';
    return 'bg-zinc-100 text-zinc-600 ring-zinc-200';
  });

  private formatCurrency(value: number | string): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'INR',
        maximumFractionDigits: 0,
      }).format(n);
    } catch {
      return `₹${n.toLocaleString()}`;
    }
  }

  private formatPercent(value: number | string): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    return `${n.toFixed(1)}%`;
  }

  private formatNumber(value: number | string): string {
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return String(value);
    return new Intl.NumberFormat().format(n);
  }
}
