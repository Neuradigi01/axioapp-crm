import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { ContactsApiService } from '../../../../core/contacts/contacts-api.service';
import { InrPipe } from '../../../../core/shared/pipes/inr.pipe';
import { extractApiError } from '@core/services/api-error.util';
import { BillingApiService, Invoice, InvoiceStatus } from '../billing-api.service';

type StatusFilter = 'all' | InvoiceStatus;

interface ContactSummary {
  id: string;
  full_name: string;
  phone: string | null;
}

@Component({
  selector: 'app-fp-billing-invoices',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule, InrPipe],
  templateUrl: './invoices.component.html',
})
export class InvoicesTabComponent {
  private readonly api = inject(BillingApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly invoices = signal<Invoice[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly statusFilter = signal<StatusFilter>('all');

  protected readonly contactsById = signal<Record<string, ContactSummary>>({});

  protected readonly filters: { id: StatusFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'issued', label: 'Issued' },
    { id: 'paid', label: 'Paid' },
    { id: 'draft', label: 'Drafts' },
    { id: 'void', label: 'Void' },
  ];

  /** Summary tiles — match the Vercel reference: Total / Billed / Collected / Pending. */
  protected readonly tiles = computed(() => {
    const rows = this.invoices();
    let billed = 0;
    let collected = 0;
    for (const r of rows) {
      const total = Number(r.total ?? 0);
      if (r.status === 'paid' || r.status === 'issued') billed += total;
      if (r.status === 'paid') collected += total;
    }
    return {
      total: rows.length,
      billed,
      collected,
      pending: Math.max(billed - collected, 0),
    };
  });

  protected readonly view = computed(() => {
    const filt = this.statusFilter();
    const rows = this.invoices();
    if (filt === 'all') return rows;
    return rows.filter((r) => r.status === filt);
  });

  constructor() {
    this.reload();

    // Pull contact summaries for any invoices we don't already have cached.
    effect(() => {
      const ids = new Set(
        this.invoices()
          .map((i) => i.contact_id)
          .filter((id): id is string => id !== null),
      );
      const cache = this.contactsById();
      const missing = [...ids].filter((id) => !cache[id]);
      if (missing.length === 0) return;
      this.fetchContacts(missing);
    });
  }

  protected setFilter(f: StatusFilter): void {
    this.statusFilter.set(f);
  }

  protected reload(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .list({ size: 100 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.invoices.set(resp.items);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.invoices.set([]);
          this.loading.set(false);
          this.loadError.set(extractApiError(err) ?? 'Could not load invoices.');
        },
      });
  }

  protected statusBadgeClass(status: InvoiceStatus): string {
    switch (status) {
      case 'paid':
        return 'bg-emerald-100 text-emerald-700 ring-emerald-200';
      case 'issued':
        return 'bg-amber-100 text-amber-700 ring-amber-200';
      case 'draft':
        return 'bg-surface-2 text-default border-subtle';
      case 'void':
        return 'bg-red-100 text-red-700 ring-red-200';
      default:
        return 'bg-surface-2 text-default border-subtle';
    }
  }

  protected paymentLabel(method: string | null): string {
    if (!method) return '—';
    return method.toUpperCase();
  }

  protected formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString('en-IN', {
      day: '2-digit',
      month: 'short',
      year: 'numeric',
    });
  }

  protected invoiceNumber(inv: Invoice): string {
    if (inv.number === null) return '— draft —';
    return `INV-${String(inv.number).padStart(4, '0')}`;
  }

  protected contactName(id: string | null): string {
    if (!id) return 'Walk-in';
    return this.contactsById()[id]?.full_name ?? '…';
  }

  protected contactPhone(id: string | null): string | null {
    if (!id) return null;
    return this.contactsById()[id]?.phone ?? null;
  }

  private fetchContacts(ids: string[]): void {
    forkJoin(ids.map((id) => this.contactsApi.get(id).pipe(catchError(() => of(null)))))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((rows) => {
        this.contactsById.update((cache) => {
          const next = { ...cache };
          for (const c of rows) {
            if (c) {
              next[c.id] = {
                id: c.id,
                full_name: c.full_name,
                phone: c.phone,
              };
            }
          }
          return next;
        });
      });
  }
}
