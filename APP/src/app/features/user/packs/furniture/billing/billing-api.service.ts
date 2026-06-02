import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { buildHttpParams } from '../../../core/shared/services/query-builder';

export type InvoiceStatus = 'draft' | 'issued' | 'paid' | 'void';
export type PaymentMethod =
  | 'cash'
  | 'card'
  | 'upi'
  | 'emi'
  | 'cheque'
  | 'bank';

export interface Invoice {
  id: string;
  org_id: string;
  number: number | null;
  contact_id: string | null;
  status: InvoiceStatus;
  subtotal: string;
  tax_amount: string;
  discount_amount: string;
  total: string;
  currency: string;
  gst_number: string | null;
  tax_rate_snapshot: string | null;
  issued_at: string | null;
  paid_at: string | null;
  payment_method: PaymentMethod | null;
  notes: string | null;
  custom_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface InvoiceLine {
  id: string;
  invoice_id: string;
  catalog_item_id: string | null;
  description: string;
  qty: number;
  unit_price: string;
  line_subtotal: string;
  tax_pct: string;
  line_total: string;
  created_at: string;
}

export interface InvoiceWithLines extends Invoice {
  lines: InvoiceLine[];
}

export interface InvoiceListResponse {
  items: Invoice[];
  total: number;
  page: number;
  size: number;
}

export interface InvoiceListQuery {
  status?: InvoiceStatus;
  contact_id?: string;
  page?: number;
  size?: number;
}

export interface Payment {
  id: string;
  invoice_id: string;
  amount: string;
  method: PaymentMethod;
  reference: string | null;
  received_at: string;
  notes: string | null;
  created_at: string;
}

export interface PaymentCreate {
  amount: string;
  method: PaymentMethod;
  reference?: string | null;
  notes?: string | null;
}

// --- POS ---------------------------------------------------------------

export interface PosLine {
  catalog_item_id?: string | null;
  description: string;
  qty: number;
  unit_price: string;
}

export interface PosCheckoutPayload {
  contact_phone: string;
  contact_name?: string | null;
  lines: PosLine[];
  payment_method: PaymentMethod;
  payment_reference?: string | null;
  discount_amount?: string;
  notes?: string | null;
}

export interface InventoryDecrementRecord {
  catalog_item_id: string;
  item_id?: string;
  qty?: number;
  skipped?: boolean;
  reason?: string;
}

export interface PosCheckoutResponse {
  invoice: InvoiceWithLines;
  pdf_url: string;
  inventory_decrements: InventoryDecrementRecord[];
}

@Injectable({ providedIn: 'root' })
export class BillingApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/invoices`;
  private readonly posBase = `${environment.apiBaseUrl}/pos`;

  list(query: InvoiceListQuery = {}): Observable<InvoiceListResponse> {
    const params = buildHttpParams({
      status: query.status,
      contact_id: query.contact_id,
      page: query.page,
      size: query.size,
    });
    return this.http.get<InvoiceListResponse>(this.base, { params });
  }

  get(id: string): Observable<InvoiceWithLines> {
    return this.http.get<InvoiceWithLines>(`${this.base}/${id}`);
  }

  listPayments(id: string): Observable<Payment[]> {
    return this.http.get<Payment[]>(`${this.base}/${id}/payments`);
  }

  recordPayment(id: string, payload: PaymentCreate): Observable<Payment> {
    return this.http.post<Payment>(`${this.base}/${id}/payments`, payload);
  }

  voidInvoice(id: string): Observable<Invoice> {
    return this.http.post<Invoice>(`${this.base}/${id}/void`, {});
  }

  /** Absolute URL for the inline PDF (works inside `window.open`). */
  pdfUrl(id: string): string {
    return `${this.base}/${id}/pdf`;
  }

  checkout(payload: PosCheckoutPayload): Observable<PosCheckoutResponse> {
    return this.http.post<PosCheckoutResponse>(
      `${this.posBase}/checkout`,
      payload,
    );
  }
}
