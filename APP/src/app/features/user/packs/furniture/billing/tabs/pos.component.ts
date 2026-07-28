import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import { CatalogApiService } from '../../../../core/catalog/catalog-api.service';
import {
  ContactListItem,
  ContactListResponse,
  ContactsApiService,
} from '../../../../core/contacts/contacts-api.service';
import { InrPipe } from '../../../../core/shared/pipes/inr.pipe';
import { extractApiError } from '@core/services/api-error.util';
import { deriveApiOrigin } from '@core/services/url.util';
import { InventoryApiService, InventoryItem } from '../../inventory/inventory-api.service';
import { BillingApiService, PaymentMethod, PosCheckoutResponse } from '../billing-api.service';

/** A line in the live cart — keyed by inventory item id. */
interface CartLine {
  inv_id: string;
  catalog_item_id: string | null;
  sku: string;
  display_name: string;
  unit_price: number;
  qty: number;
  /** Max we can sell from default warehouse — surface so the +/- buttons can clamp. */
  qty_on_hand: number;
}

type DiscountMode = 'flat' | 'percent';

const PAYMENT_METHODS: { id: PaymentMethod; label: string; icon: string }[] = [
  { id: 'cash', label: 'Cash', icon: 'banknote' },
  { id: 'card', label: 'Card', icon: 'credit-card' },
  { id: 'upi', label: 'UPI', icon: 'smartphone' },
  { id: 'emi', label: 'EMI', icon: 'wallet' },
  { id: 'cheque', label: 'Cheque', icon: 'receipt' },
  { id: 'bank', label: 'Bank', icon: 'wallet' },
];

/** Empty contact-list response stream used when the phone query is too
 * short or the lookup errors — keeps the switchMap union narrow. */
const emptyResp$ = of<ContactListResponse>({
  items: [],
  total: 0,
  page: 1,
  size: 5,
});

@Component({
  selector: 'app-fp-billing-pos',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, InrPipe],
  templateUrl: './pos.component.html',
})
export class PosTabComponent {
  private readonly api = inject(BillingApiService);
  private readonly inventoryApi = inject(InventoryApiService);
  private readonly catalogApi = inject(CatalogApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  // --- product grid -----------------------------------------------------

  protected readonly items = signal<InventoryItem[]>([]);
  protected readonly catalogPricesById = signal<Record<string, number>>({});
  protected readonly loadingItems = signal(false);
  protected readonly searchControl = new FormControl<string>('', {
    nonNullable: true,
  });

  // --- cart -------------------------------------------------------------

  protected readonly cart = signal<CartLine[]>([]);

  protected readonly cartSubtotal = computed(() =>
    this.cart().reduce((sum, l) => sum + l.unit_price * l.qty, 0),
  );

  // --- customer ---------------------------------------------------------

  protected readonly phoneControl = new FormControl<string>('', {
    nonNullable: true,
  });
  protected readonly nameControl = new FormControl<string>('', {
    nonNullable: true,
  });
  protected readonly matchedContact = signal<ContactListItem | null>(null);
  protected readonly lookupBusy = signal(false);
  private readonly phoneQuery$ = new Subject<string>();

  // --- discount ---------------------------------------------------------

  protected readonly discountMode = signal<DiscountMode>('flat');
  protected readonly discountValueControl = new FormControl<string>('', {
    nonNullable: true,
  });

  /** Computed flat discount amount (POST body always sends flat). */
  protected readonly discountAmount = computed(() => {
    const raw = this.discountValueControl.value.trim();
    const n = Number(raw || 0);
    if (!Number.isFinite(n) || n <= 0) return 0;
    if (this.discountMode() === 'flat') return n;
    // percent — clamp to [0, 100]
    const pct = Math.min(Math.max(n, 0), 100);
    return (this.cartSubtotal() * pct) / 100;
  });

  // --- payment ----------------------------------------------------------

  protected readonly paymentMethods = PAYMENT_METHODS;
  protected readonly paymentMethod = signal<PaymentMethod>('cash');

  // --- submission -------------------------------------------------------

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly lastInvoiceNumber = signal<number | null>(null);

  protected readonly canCheckout = computed(
    () =>
      this.cart().length > 0 && this.phoneControl.value.trim().length >= 3 && !this.submitting(),
  );

  /** Total *after* discount but BEFORE tax — for the bill summary box. */
  protected readonly afterDiscount = computed(() =>
    Math.max(this.cartSubtotal() - this.discountAmount(), 0),
  );

  /** Live tax estimate using the inventory item count and 18% baseline
   * — the *real* tax is applied server-side from org_settings at issue
   * time. We show this as "estimated GST" so the cashier has a number
   * to read aloud; the printed receipt always carries the authoritative
   * snapshot. */
  protected readonly taxEstimate = computed(
    () => Math.round(this.afterDiscount() * 0.18 * 100) / 100,
  );

  protected readonly grandEstimate = computed(() => this.afterDiscount() + this.taxEstimate());

  constructor() {
    this.reloadItems('');
    this.loadCatalogPrices();

    this.searchControl.valueChanges
      .pipe(debounceTime(200), distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((q) => this.reloadItems(q.trim()));

    // Auto-fill name when the user types a phone that matches a contact.
    this.phoneQuery$
      .pipe(
        debounceTime(300),
        distinctUntilChanged(),
        switchMap((q): typeof emptyResp$ => {
          if (q.length < 3) return emptyResp$;
          this.lookupBusy.set(true);
          return this.contactsApi.list({ q, size: 5 }).pipe(catchError(() => emptyResp$));
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.lookupBusy.set(false);
        const phone = this.phoneControl.value.trim();
        const hit = resp.items.find((c) => c.phone === phone) ?? null;
        this.matchedContact.set(hit);
        if (hit && !this.nameControl.value) {
          this.nameControl.setValue(hit.full_name);
        }
      });

    this.phoneControl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.phoneQuery$.next(v.trim()));
  }

  // --- product grid actions ---------------------------------------------

  protected reloadItems(q: string): void {
    this.loadingItems.set(true);
    this.inventoryApi
      .listItems({ q: q || undefined, active_only: true, size: 60 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          // Only sellable rows: positive stock + linked to catalog (POS
          // needs the catalog_item_id to drive inventory dispatch).
          this.items.set(resp.items.filter((i) => i.qty_on_hand > 0 && i.catalog_item_id !== null));
          this.loadingItems.set(false);
        },
        error: () => {
          this.items.set([]);
          this.loadingItems.set(false);
        },
      });
  }

  protected addToCart(item: InventoryItem): void {
    if (item.qty_on_hand <= 0 || item.catalog_item_id === null) return;
    const existing = this.cart().find((l) => l.inv_id === item.id);
    if (existing) {
      if (existing.qty < item.qty_on_hand) this.changeQty(item.id, +1);
      return;
    }
    this.cart.update((lines) => [
      ...lines,
      {
        inv_id: item.id,
        catalog_item_id: item.catalog_item_id,
        sku: item.sku,
        display_name: this.displayName(item),
        unit_price: this.resolveUnitPrice(item),
        qty: 1,
        qty_on_hand: item.qty_on_hand,
      },
    ]);
  }

  protected changeQty(invId: string, delta: number): void {
    this.cart.update((lines) =>
      lines
        .map((l) =>
          l.inv_id === invId
            ? {
                ...l,
                qty: Math.max(1, Math.min(l.qty + delta, l.qty_on_hand)),
              }
            : l,
        )
        .filter((l) => l.qty > 0),
    );
  }

  protected removeLine(invId: string): void {
    this.cart.update((lines) => lines.filter((l) => l.inv_id !== invId));
  }

  protected clearCart(): void {
    this.cart.set([]);
    this.discountValueControl.setValue('');
  }

  // --- customer / discount / payment ------------------------------------

  protected setDiscountMode(mode: DiscountMode): void {
    this.discountMode.set(mode);
  }

  protected setPaymentMethod(m: PaymentMethod): void {
    this.paymentMethod.set(m);
  }

  // --- checkout ---------------------------------------------------------

  protected pay(): void {
    if (!this.canCheckout()) return;
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .checkout({
        contact_phone: this.phoneControl.value.trim(),
        contact_name: this.nameControl.value.trim() || null,
        payment_method: this.paymentMethod(),
        discount_amount: this.discountAmount().toFixed(2),
        lines: this.cart().map((l) => ({
          catalog_item_id: l.catalog_item_id,
          description: l.display_name,
          qty: l.qty,
          unit_price: l.unit_price.toFixed(2),
        })),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.submitting.set(false);
          this.onCheckedOut(resp);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Checkout failed.');
        },
      });
  }

  private onCheckedOut(resp: PosCheckoutResponse): void {
    this.lastInvoiceNumber.set(resp.invoice.number);
    // Open the PDF in a new tab. Use the absolute URL so the browser
    // hits the API directly, not the Angular dev origin.
    const origin = deriveApiOrigin();
    window.open(`${origin}${resp.pdf_url}`, '_blank', 'noopener');
    // Reset cart + customer + discount but keep payment-method selection
    // so back-to-back cash sales stay fast.
    this.cart.set([]);
    this.phoneControl.setValue('');
    this.nameControl.setValue('');
    this.matchedContact.set(null);
    this.discountValueControl.setValue('');
    // Refresh product grid so quantities reflect the dispatch.
    this.reloadItems(this.searchControl.value.trim());
  }

  // --- helpers ----------------------------------------------------------

  protected displayName(item: InventoryItem): string {
    const parts: string[] = [item.sku];
    if (item.material) parts.push(item.material);
    if (item.color) parts.push(item.color);
    return parts.join(' · ');
  }

  protected resolveUnitPrice(item: InventoryItem): number {
    // Canonical price lives on the linked catalog row. We pre-load all
    // catalog prices into `catalogPricesById` once on mount so the grid
    // can render synchronously; fall back to 0 if the catalog row is
    // missing (cashier can then refuse the line at checkout).
    if (item.catalog_item_id === null) return 0;
    return this.catalogPricesById()[item.catalog_item_id] ?? 0;
  }

  private loadCatalogPrices(): void {
    this.catalogApi
      .list({ active_only: true, size: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          const map: Record<string, number> = {};
          for (const c of resp.items) {
            const n = Number(c.price);
            if (Number.isFinite(n)) map[c.id] = n;
          }
          this.catalogPricesById.set(map);
        },
        error: () => this.catalogPricesById.set({}),
      });
  }
}
