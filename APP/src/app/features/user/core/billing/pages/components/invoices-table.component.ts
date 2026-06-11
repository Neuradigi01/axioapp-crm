import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';

import {
  Invoice,
  InvoiceStatus,
} from '../../types/subscription.types';

interface InvoiceRowVM {
  id: string;
  date: string;
  number: string;
  amountDisplay: string;
  statusLabel: string;
  statusClasses: string;
  downloadUrl: string | null;
}

const STATUS_LABELS: Record<InvoiceStatus, string> = {
  paid: 'Paid',
  open: 'Unpaid',
  void: 'Void',
  uncollectible: 'Uncollectible',
  draft: 'Draft',
};

const STATUS_TONE: Record<InvoiceStatus, string> = {
  paid: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  open: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300',
  void: 'bg-zinc-100 text-zinc-600 dark:bg-slate-700 dark:text-slate-300',
  uncollectible:
    'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
  draft: 'bg-zinc-100 text-zinc-600 dark:bg-slate-700 dark:text-slate-300',
};

/**
 * Invoice history table on the Billing settings page.
 *
 * Populated by `GET /api/v1/subscriptions/invoices` (Step 13.c). The
 * "Download PDF" link points at Stripe's `pdf_url` (preferred) or
 * `hosted_invoice_url` as a fallback — either gives the customer
 * the document Stripe rendered. We do not generate PDFs locally.
 *
 * Empty state covers two cases: still on trial (no Stripe activity
 * yet) and active subscription whose first invoice has not yet
 * landed via the Step 13.b webhook.
 */
@Component({
  selector: 'crm-invoices-table',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <p class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400">
        Invoices
      </p>
      <h2 class="mt-1 text-xl font-semibold text-zinc-900 dark:text-slate-100">
        Billing history
      </h2>

      @if (isLoading()) {
        <div class="mt-6 space-y-2">
          @for (i of [0, 1, 2]; track i) {
            <div class="h-9 rounded bg-zinc-100 animate-pulse dark:bg-slate-700"></div>
          }
        </div>
      } @else if (viewRows().length === 0) {
        <p class="mt-6 text-sm text-zinc-500 dark:text-slate-400">
          No invoices yet. Once you upgrade and Stripe issues the first
          invoice it will appear here.
        </p>
      } @else {
        <div class="mt-6 overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-left text-xs uppercase tracking-wide text-zinc-500 dark:text-slate-400">
              <tr>
                <th class="py-2 font-medium">Date</th>
                <th class="py-2 font-medium">Number</th>
                <th class="py-2 font-medium">Amount</th>
                <th class="py-2 font-medium">Status</th>
                <th class="py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-zinc-100 dark:divide-slate-700">
              @for (row of viewRows(); track row.id) {
                <tr class="text-zinc-700 dark:text-slate-200">
                  <td class="py-3">{{ row.date }}</td>
                  <td class="py-3 font-mono text-xs">{{ row.number }}</td>
                  <td class="py-3 font-medium">{{ row.amountDisplay }}</td>
                  <td class="py-3">
                    <span
                      [class]="
                        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ' +
                        row.statusClasses
                      "
                    >
                      {{ row.statusLabel }}
                    </span>
                  </td>
                  <td class="py-3 text-right">
                    @if (row.downloadUrl) {
                      <a
                        [href]="row.downloadUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                      >
                        Download
                      </a>
                    } @else {
                      <span class="text-xs text-zinc-400">—</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    </section>
  `,
})
export class InvoicesTableComponent {
  readonly invoices = input.required<readonly Invoice[]>();
  readonly isLoading = input<boolean>(false);

  protected readonly viewRows = computed<readonly InvoiceRowVM[]>(() =>
    this.invoices().map(toViewModel),
  );
}


function toViewModel(invoice: Invoice): InvoiceRowVM {
  // `pdf_url` is the direct PDF; `hosted_invoice_url` is Stripe's
  // browser-facing view. Either is acceptable for a "Download" action,
  // and at least one is usually populated.
  const downloadUrl = invoice.pdf_url ?? invoice.hosted_invoice_url ?? null;
  const amount = invoice.amount_paid_cents > 0
    ? invoice.amount_paid_cents
    : invoice.amount_due_cents;
  return {
    id: invoice.id,
    date: (invoice.paid_at ?? invoice.created_at).slice(0, 10),
    number: invoice.number ?? invoice.stripe_invoice_id,
    amountDisplay: formatCurrency(amount, invoice.currency),
    statusLabel: STATUS_LABELS[invoice.status] ?? invoice.status,
    statusClasses: STATUS_TONE[invoice.status] ?? STATUS_TONE.draft,
    downloadUrl,
  };
}


function formatCurrency(cents: number, currency: string): string {
  // Stripe ships cents; divide for display. We avoid `Intl.NumberFormat`
  // here because the page is admin-facing and we want consistent
  // formatting regardless of the browser locale (most invoices are
  // USD; multi-currency support is a later concern).
  const amount = (cents / 100).toFixed(2);
  return `${currency.toUpperCase()} ${amount}`;
}
