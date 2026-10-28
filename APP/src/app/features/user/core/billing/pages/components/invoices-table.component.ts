import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import { Invoice, InvoiceStatus } from '../../types/subscription.types';

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
  paid: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:ring-emerald-900',
  open: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-900',
  void: 'bg-zinc-100 text-zinc-600 ring-1 ring-zinc-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600',
  uncollectible:
    'bg-rose-50 text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950 dark:text-rose-300 dark:ring-rose-900',
  draft:
    'bg-zinc-100 text-zinc-600 ring-1 ring-zinc-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600',
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
  imports: [LucideAngularModule],
  template: `
    <section
      class="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800"
    >
      <div class="flex items-center gap-3 border-b border-zinc-200 px-6 py-4 dark:border-slate-700">
        <div
          class="flex h-9 w-9 items-center justify-center rounded-lg bg-zinc-100 text-zinc-700 ring-1 ring-zinc-200 dark:bg-slate-700 dark:text-slate-300 dark:ring-slate-600"
        >
          <lucide-icon name="receipt" size="18" aria-hidden="true"></lucide-icon>
        </div>
        <div>
          <p
            class="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-slate-400"
          >
            Invoices
          </p>
          <h2 class="text-base font-semibold text-zinc-900 dark:text-slate-100">Billing history</h2>
        </div>
      </div>

      @if (isLoading()) {
        <div class="space-y-2 p-6">
          @for (i of [0, 1, 2]; track i) {
            <div class="h-10 rounded bg-zinc-100 animate-pulse dark:bg-slate-700"></div>
          }
        </div>
      } @else if (viewRows().length === 0) {
        <div class="px-6 py-12 text-center">
          <div
            class="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-zinc-100 text-zinc-400 dark:bg-slate-700 dark:text-slate-500"
          >
            <lucide-icon name="receipt" size="18" aria-hidden="true"></lucide-icon>
          </div>
          <p class="mt-3 text-sm font-medium text-zinc-700 dark:text-slate-200">No invoices yet</p>
          <p class="mt-1 text-xs text-zinc-500 dark:text-slate-400">
            Once you upgrade and Stripe issues the first invoice, it'll appear here.
          </p>
        </div>
      } @else {
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead
              class="border-b border-zinc-200 bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-400"
            >
              <tr>
                <th class="px-6 py-2.5 font-medium">Date</th>
                <th class="px-6 py-2.5 font-medium">Number</th>
                <th class="px-6 py-2.5 font-medium">Amount</th>
                <th class="px-6 py-2.5 font-medium">Status</th>
                <th class="px-6 py-2.5 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-zinc-100 dark:divide-slate-700">
              @for (row of viewRows(); track row.id) {
                <tr
                  class="text-zinc-700 transition-colors hover:bg-zinc-50 dark:text-slate-200 dark:hover:bg-slate-700/50"
                >
                  <td class="px-6 py-3 tabular-nums">{{ row.date }}</td>
                  <td class="px-6 py-3 font-mono text-xs">{{ row.number }}</td>
                  <td class="px-6 py-3 font-medium tabular-nums">
                    {{ row.amountDisplay }}
                  </td>
                  <td class="px-6 py-3">
                    <span
                      [class]="
                        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ' +
                        row.statusClasses
                      "
                    >
                      {{ row.statusLabel }}
                    </span>
                  </td>
                  <td class="px-6 py-3 text-right">
                    @if (row.downloadUrl) {
                      <a
                        [href]="row.downloadUrl"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="inline-flex items-center gap-1 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                      >
                        <lucide-icon name="download" size="14" aria-hidden="true"></lucide-icon>
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
  const amount =
    invoice.amount_paid_cents > 0 ? invoice.amount_paid_cents : invoice.amount_due_cents;
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
