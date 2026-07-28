import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  BlockListPage,
  BlockListService,
  BlockReason,
  BlockedNumber,
  BlockNumberRequest,
} from './block-list.service';

const REASONS: ReadonlyArray<{ value: BlockReason; label: string }> = [
  { value: 'spam', label: 'Spam' },
  { value: 'fraud', label: 'Fraud' },
  { value: 'requested', label: 'Requested by customer' },
  { value: 'harassment', label: 'Harassment' },
  { value: 'other', label: 'Other' },
];

/**
 * Settings → WhatsApp → Block list (Step 23).
 *
 * Tabular view + add modal + per-row unblock. Inbound from these
 * numbers is silently dropped at the webhook; outbound to them is
 * refused by the send guard.
 */
@Component({
  selector: 'app-block-list-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <div class="space-y-4 p-4">
      <header class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-default">Block list</h1>
          <p class="text-xs text-muted">
            Numbers we won't send to or accept from. Inbound is silently dropped; outbound is
            refused by the campaign send guard.
          </p>
        </div>
        <button
          type="button"
          (click)="openAdd()"
          class="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent"
        >
          <lucide-icon name="plus" class="h-3.5 w-3.5" />
          Block a number
        </button>
      </header>

      <div class="flex items-center gap-2">
        <input
          type="search"
          placeholder="Filter by digits…"
          class="w-64 rounded-md border border-subtle px-2.5 py-1.5 text-xs"
          [ngModel]="search()"
          (ngModelChange)="onSearch($event)"
        />
        @if (loading()) {
          <span class="text-[11px] text-muted">Loading…</span>
        }
      </div>

      @if (error(); as err) {
        <p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {{ err }}
        </p>
      }
      @if (toast(); as msg) {
        <p class="rounded-md border border-subtle bg-surface-2 px-3 py-2 text-xs text-default">
          {{ msg }}
        </p>
      }

      <div class="overflow-hidden rounded-md border border-subtle bg-surface">
        <table class="w-full text-xs">
          <thead class="bg-surface-2 text-muted">
            <tr>
              <th class="px-3 py-2 text-left font-medium">Phone</th>
              <th class="px-3 py-2 text-left font-medium">Reason</th>
              <th class="px-3 py-2 text-left font-medium">Blocked</th>
              <th class="px-3 py-2 text-left font-medium">Notes</th>
              <th class="px-3 py-2 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-subtle">
            @for (row of page().items; track row.id) {
              <tr>
                <td class="px-3 py-2 font-mono text-default">
                  {{ row.phone_number }}
                </td>
                <td class="px-3 py-2 capitalize text-default">{{ row.reason }}</td>
                <td class="px-3 py-2 text-muted">
                  {{ formatDate(row.created_at) }}
                </td>
                <td class="px-3 py-2 text-muted">{{ row.notes || '—' }}</td>
                <td class="px-3 py-2 text-right">
                  <button
                    type="button"
                    (click)="onUnblock(row)"
                    class="rounded-md border border-subtle bg-surface px-2 py-1 text-[11px] font-medium text-default hover:bg-surface-2"
                  >
                    Unblock
                  </button>
                </td>
              </tr>
            } @empty {
              <tr>
                <td colspan="5" class="px-3 py-6 text-center text-muted">
                  No blocked numbers. Inbound + outbound flow without restriction.
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      @if (page().total > page().size) {
        <div class="flex items-center justify-between text-xs text-muted">
          <span>{{ page().total }} blocked total</span>
          <div class="flex gap-1">
            <button
              type="button"
              [disabled]="page().page === 1"
              (click)="setPage(page().page - 1)"
              class="rounded border border-subtle bg-surface px-2 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              [disabled]="page().page * page().size >= page().total"
              (click)="setPage(page().page + 1)"
              class="rounded border border-subtle bg-surface px-2 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      }
    </div>

    @if (addOpen()) {
      <div
        class="fixed inset-0 z-50 flex items-center justify-center bg-accent/40"
        (click)="closeAdd()"
      >
        <div
          class="w-full max-w-md rounded-md border border-subtle bg-surface p-4 shadow-lg"
          (click)="$event.stopPropagation()"
        >
          <p class="mb-2 text-sm font-semibold text-default">Block a number</p>
          <label class="mb-2 block text-xs">
            <span class="mb-1 block font-medium text-default">Phone</span>
            <input
              type="text"
              class="w-full rounded-md border border-subtle px-2.5 py-1.5"
              placeholder="+91 9XXXXXXXXX"
              [ngModel]="form().phone_number"
              (ngModelChange)="patchForm({ phone_number: $event })"
            />
          </label>
          <label class="mb-2 block text-xs">
            <span class="mb-1 block font-medium text-default">Reason</span>
            <select
              class="w-full rounded-md border border-subtle px-2.5 py-1.5"
              [ngModel]="form().reason"
              (ngModelChange)="patchForm({ reason: $event })"
            >
              @for (r of REASONS; track r.value) {
                <option [value]="r.value">{{ r.label }}</option>
              }
            </select>
          </label>
          <label class="mb-3 block text-xs">
            <span class="mb-1 block font-medium text-default">Notes</span>
            <textarea
              rows="2"
              class="w-full rounded-md border border-subtle px-2.5 py-1.5"
              [ngModel]="form().notes"
              (ngModelChange)="patchForm({ notes: $event })"
            ></textarea>
          </label>
          <div class="flex justify-end gap-2">
            <button
              type="button"
              (click)="closeAdd()"
              class="rounded-md border border-subtle bg-surface px-3 py-1.5 text-xs font-medium text-default hover:bg-surface-2"
            >
              Cancel
            </button>
            <button
              type="button"
              [disabled]="busy() || !form().phone_number"
              (click)="submitAdd()"
              class="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-white hover:bg-accent disabled:opacity-50"
            >
              {{ busy() ? 'Adding…' : 'Block number' }}
            </button>
          </div>
        </div>
      </div>
    }
  `,
})
export class BlockListPageComponent {
  private readonly api = inject(BlockListService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly REASONS = REASONS;

  protected readonly page = signal<BlockListPage>({
    items: [],
    total: 0,
    page: 1,
    size: 50,
  });
  protected readonly loading = signal<boolean>(false);
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);
  protected readonly search = signal<string>('');

  protected readonly addOpen = signal<boolean>(false);
  protected readonly form = signal<BlockNumberRequest>({
    phone_number: '',
    reason: 'spam',
    notes: '',
  });

  constructor() {
    this.load();
  }

  protected onSearch(value: string): void {
    this.search.set(value);
    this.load(1);
  }

  protected setPage(p: number): void {
    this.load(p);
  }

  protected openAdd(): void {
    this.form.set({ phone_number: '', reason: 'spam', notes: '' });
    this.addOpen.set(true);
  }

  protected closeAdd(): void {
    this.addOpen.set(false);
  }

  protected patchForm(patch: Partial<BlockNumberRequest>): void {
    this.form.update((f) => ({ ...f, ...patch }));
  }

  protected submitAdd(): void {
    const body = this.form();
    if (!body.phone_number) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .add(body)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.addOpen.set(false);
          this.toast.set(`${body.phone_number} added to the block list.`);
          this.load(1);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not block number.');
        },
      });
  }

  protected onUnblock(row: BlockedNumber): void {
    if (!confirm(`Unblock ${row.phone_number}?`)) return;
    this.api
      .remove(row.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.toast.set(`${row.phone_number} unblocked.`);
          this.load(this.page().page);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not unblock number.');
        },
      });
  }

  protected formatDate(iso: string): string {
    return new Date(iso).toLocaleString();
  }

  private load(page = this.page().page): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .list(this.search() || undefined, page, this.page().size)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (p) => {
          this.page.set(p);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load block list.');
        },
      });
  }
}
