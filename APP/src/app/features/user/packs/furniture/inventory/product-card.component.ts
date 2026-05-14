import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';

import { InventoryItem } from './inventory-api.service';

/**
 * Single inventory card. Stock badge logic:
 *
 *   qty_on_hand <= 0                   → Out of Stock (red)
 *   qty_on_hand <= reorder_level (> 0) → Low Stock    (amber)
 *   is_best_seller                     → Best Seller  (violet)
 *   otherwise                          → In Stock     (emerald)
 *
 * A Best-Seller flag overrides "In Stock" but is dimmed to a
 * secondary pill when the stock is low/out so the user always sees
 * the more urgent state first.
 */
@Component({
  selector: 'app-fp-product-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [],
  templateUrl: './product-card.component.html',
})
export class ProductCardComponent {
  readonly item = input.required<InventoryItem>();
  readonly warehouseLabel = input<string | null>(null);

  protected readonly primaryBadge = computed<{ label: string; cls: string }>(() => {
    const i = this.item();
    if (i.qty_on_hand <= 0) {
      return {
        label: 'Out of Stock',
        cls: 'bg-rose-50 text-rose-700 ring-rose-200',
      };
    }
    if (i.reorder_level > 0 && i.qty_on_hand <= i.reorder_level) {
      return {
        label: 'Low Stock',
        cls: 'bg-amber-50 text-amber-700 ring-amber-200',
      };
    }
    return {
      label: 'In Stock',
      cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    };
  });

  protected readonly showBestSeller = computed(() => this.item().is_best_seller);

  protected readonly thumbnailBg = computed(() => {
    // Deterministic colour per item id so the same SKU always gets
    // the same pastel background until real photos land.
    const palette = [
      'bg-rose-100',
      'bg-amber-100',
      'bg-emerald-100',
      'bg-sky-100',
      'bg-violet-100',
      'bg-fuchsia-100',
    ];
    let h = 0;
    for (const c of this.item().id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return palette[h % palette.length];
  });

  protected readonly thumbnailGlyph = computed(() => {
    const m = (this.item().material || '').toLowerCase();
    if (m.includes('wood')) return '🪵';
    if (m.includes('metal')) return '🔩';
    if (m.includes('glass')) return '🪟';
    if (m.includes('uphol')) return '🛋️';
    return '📦';
  });

  protected dimensionsLabel(): string {
    const d = this.item().dimensions ?? {};
    const w = d['width'] ?? d['w'];
    const dpth = d['depth'] ?? d['d'];
    const h = d['height'] ?? d['h'];
    const parts = [w, dpth, h].filter((v) => v !== undefined && v !== null);
    return parts.length ? parts.join(' × ') : '';
  }
}
