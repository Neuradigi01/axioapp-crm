import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { catchError, of, switchMap } from 'rxjs';

import { environment } from '../../../../../../environments/environment';
import { ContactsApiService } from '../../../core/contacts/contacts-api.service';
import { InrPipe } from '../../../core/shared/pipes/inr.pipe';
import {
  BillingApiService,
  InvoiceStatus,
  InvoiceWithLines,
  Payment,
} from './billing-api.service';

/**
 * `/billing/invoices/:id` — full invoice view with line items, payment
 * history, and a Print/PDF button. The PDF link is the absolute API URL
 * so `window.open` hits the API origin directly (no Angular proxy).
 */
@Component({
  selector: 'app-fp-invoice-detail-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, InrPipe],
  templateUrl: './invoice-detail.page.html',
})
export class InvoiceDetailPageComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(BillingApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly invoice = signal<InvoiceWithLines | null>(null);
  protected readonly payments = signal<Payment[]>([]);
  protected readonly contactName = signal<string | null>(null);
  protected readonly contactPhone = signal<string | null>(null);
  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  protected readonly apiOrigin = this.deriveApiOrigin();

  protected readonly pdfHref = computed(() => {
    const inv = this.invoice();
    return inv ? `${this.apiOrigin}${this.api.pdfUrl(inv.id)}` : '';
  });

  protected readonly invoiceNumber = computed(() => {
    const inv = this.invoice();
    if (!inv || inv.number === null) return '— draft —';
    return `INV-${String(inv.number).padStart(4, '0')}`;
  });

  constructor() {
    this.route.paramMap
      .pipe(
        switchMap((p) => {
          const id = p.get('id');
          if (!id) return of(null);
          this.loading.set(true);
          this.loadError.set(null);
          return this.api.get(id).pipe(
            catchError((err: HttpErrorResponse) => {
              this.loadError.set(
                this.extractError(err) ?? 'Could not load invoice.',
              );
              this.loading.set(false);
              return of(null);
            }),
          );
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((inv) => {
        if (!inv) return;
        this.invoice.set(inv);
        this.loading.set(false);
        this.loadPayments(inv.id);
        if (inv.contact_id) this.loadContact(inv.contact_id);
      });
  }

  protected statusBadgeClass(status: InvoiceStatus): string {
    switch (status) {
      case 'paid':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'issued':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'draft':
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
      case 'void':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-zinc-100 text-zinc-700 ring-zinc-200';
    }
  }

  protected formatDateTime(iso: string | null | undefined): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  protected paymentLabel(method: string | null): string {
    if (!method) return '—';
    return method.toUpperCase();
  }

  private loadPayments(id: string): void {
    this.api
      .listPayments(id)
      .pipe(
        catchError(() => of<Payment[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => this.payments.set(rows));
  }

  private loadContact(id: string): void {
    this.contactsApi
      .get(id)
      .pipe(
        catchError(() => of(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((c) => {
        if (c) {
          this.contactName.set(c.full_name);
          this.contactPhone.set(c.phone);
        }
      });
  }

  private deriveApiOrigin(): string {
    try {
      return new URL(environment.apiBaseUrl, window.location.origin).origin;
    } catch {
      return '';
    }
  }

  private extractError(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
