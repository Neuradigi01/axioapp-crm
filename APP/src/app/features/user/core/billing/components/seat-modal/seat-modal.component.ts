import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';

import { BillingApiService } from '../../services/billing-api.service';
import { SeatModalService } from '../../services/seat-modal.service';
import { SubscriptionStateService } from '../../services/subscription-state.service';
import { SeatPreview } from '../../types/subscription.types';

/**
 * Seat-management modal — Step 17.b.
 *
 * Smaller cousin of the upgrade modal. The user nudges seats up or
 * down; on every change we hit `GET /subscriptions/seats/preview`
 * (Step 9) so the displayed cost stays accurate. On commit:
 *
 *   - `outcome=needs_payment` (increment) → redirect into Stripe
 *     Checkout for the prorated charge.
 *   - `outcome=scheduled` (decrement)    → toast + close. The change
 *     is parked on `next_seats` and applies at period boundary.
 *   - `outcome=no_change`                → close silently; the user
 *     ended at the original count.
 *
 * Trial plans cannot add seats. The bundle minimum and `seats_in_use`
 * floors are also enforced server-side; we clamp the counter in the
 * UI so submission never trips them, but a 400 still renders inline
 * as a fallback.
 */
@Component({
  selector: 'crm-seat-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (isOpen()) {
      <div
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="seat-modal-title"
      >
        <button
          type="button"
          class="absolute inset-0 bg-zinc-900/60 backdrop-blur-sm"
          (click)="close()"
          aria-label="Close seat management"
        ></button>

        <div
          class="relative w-full max-w-md rounded-2xl bg-white shadow-xl dark:bg-slate-800 max-h-[90vh] flex flex-col"
        >
          <header
            class="flex items-start justify-between gap-4 border-b border-zinc-200 px-6 py-4 dark:border-slate-700"
          >
            <h2
              id="seat-modal-title"
              class="text-lg font-semibold text-zinc-900 dark:text-slate-100"
            >
              Manage seats
            </h2>
            <button
              type="button"
              class="rounded-md p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-slate-700 dark:hover:text-slate-100"
              (click)="close()"
              aria-label="Close"
            >
              <span aria-hidden="true">×</span>
            </button>
          </header>

          <div class="flex-1 overflow-y-auto px-6 py-5">
            <p class="text-sm text-zinc-600 dark:text-slate-300">
              {{ planSummary() }}
            </p>

            <div class="mt-4 inline-flex items-center gap-2 rounded-lg border border-zinc-200 p-1 dark:border-slate-700">
              <button
                type="button"
                (click)="decrement()"
                [disabled]="seats() <= minSeats() || isSubmitting()"
                class="rounded-md px-3 py-1 text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-700"
                aria-label="Decrease seats"
              >
                −
              </button>
              <span
                class="min-w-[2ch] text-center font-medium text-zinc-900 dark:text-slate-100"
              >
                {{ seats() }}
              </span>
              <button
                type="button"
                (click)="increment()"
                [disabled]="isSubmitting() || isTrial()"
                class="rounded-md px-3 py-1 text-zinc-700 hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-700"
                aria-label="Increase seats"
              >
                +
              </button>
            </div>
            <p class="mt-1.5 text-xs text-zinc-500 dark:text-slate-400">
              Minimum {{ minSeats() }} ·
              {{ inUseHint() }}
            </p>

            @if (isTrial()) {
              <p
                class="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
              >
                Trial plans cannot add seats — upgrade first to grow your team.
              </p>
            }

            <!-- Preview box -->
            <div
              class="mt-5 rounded-lg border border-zinc-200 bg-zinc-50 px-4 py-3 text-sm dark:border-slate-700 dark:bg-slate-900"
            >
              @if (previewLoading()) {
                <div class="h-12 animate-pulse rounded bg-zinc-200 dark:bg-slate-700"></div>
              } @else if (preview(); as p) {
                <div class="flex items-center justify-between">
                  <span class="text-zinc-600 dark:text-slate-300">
                    {{ outcomeLine(p) }}
                  </span>
                  <span class="font-semibold text-zinc-900 dark:text-slate-100">
                    \${{ p.amount_due_usd }}
                  </span>
                </div>
                @if (p.monthly_cost_after_change_usd !== null) {
                  <div class="mt-1 text-xs text-zinc-500 dark:text-slate-400">
                    \${{ p.monthly_cost_after_change_usd }} per month going forward
                  </div>
                } @else if (p.annual_cost_after_change_usd !== null) {
                  <div class="mt-1 text-xs text-zinc-500 dark:text-slate-400">
                    \${{ p.annual_cost_after_change_usd }} per year going forward
                  </div>
                }
              } @else {
                <p class="text-xs text-zinc-500 dark:text-slate-400">
                  Adjust seat count to see the estimate.
                </p>
              }
            </div>

            @if (submitError(); as msg) {
              <p
                class="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                role="alert"
              >
                {{ msg }}
              </p>
            }

            @if (scheduledMessage(); as msg) {
              <p
                class="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
              >
                {{ msg }}
              </p>
            }
          </div>

          <footer
            class="flex items-center justify-end gap-2 border-t border-zinc-200 px-6 py-3 dark:border-slate-700"
          >
            <button
              type="button"
              (click)="close()"
              [disabled]="isSubmitting()"
              class="rounded-lg px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-700"
            >
              Cancel
            </button>
            <button
              type="button"
              (click)="commit()"
              [disabled]="commitDisabled()"
              class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              @if (isSubmitting()) {
                <span
                  class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white border-t-transparent"
                ></span>
                Working…
              } @else {
                {{ commitLabel() }}
              }
            </button>
          </footer>
        </div>
      </div>
    }
  `,
})
export class SeatModalComponent {
  private readonly modalState = inject(SeatModalService);
  private readonly subscriptionState = inject(SubscriptionStateService);
  private readonly api = inject(BillingApiService);

  protected readonly isOpen = computed(() => this.modalState.state().open);

  protected readonly seats = signal<number>(0);
  protected readonly preview = signal<SeatPreview | null>(null);
  protected readonly previewLoading = signal<boolean>(false);
  protected readonly isSubmitting = signal<boolean>(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly scheduledMessage = signal<string | null>(null);

  protected readonly minSeats = computed<number>(() => {
    const sub = this.subscriptionState.current();
    if (sub === null) return 1;
    return Math.max(sub.seats.included, sub.seats.in_use);
  });

  protected readonly isTrial = computed<boolean>(
    () => this.subscriptionState.current()?.status === 'trialing',
  );

  protected readonly planSummary = computed<string>(() => {
    const sub = this.subscriptionState.current();
    if (sub === null) return '';
    return `${sub.plan.name} — currently ${sub.seats.purchased} seats purchased.`;
  });

  protected readonly inUseHint = computed<string>(() => {
    const inUse = this.subscriptionState.current()?.seats.in_use ?? 0;
    return `${inUse} active member${inUse === 1 ? '' : 's'} right now`;
  });

  protected readonly commitLabel = computed<string>(() => {
    const sub = this.subscriptionState.current();
    if (sub === null) return 'Confirm';
    const delta = this.seats() - sub.seats.purchased;
    if (delta === 0) return 'No change';
    if (delta > 0) return 'Continue to payment →';
    return 'Schedule reduction';
  });

  protected readonly commitDisabled = computed<boolean>(() => {
    if (this.isSubmitting()) return true;
    if (this.previewLoading()) return true;
    const sub = this.subscriptionState.current();
    if (sub === null) return true;
    return this.seats() === sub.seats.purchased;
  });

  private previewDebounce: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Reset state each time the modal opens.
    effect(() => {
      const state = this.modalState.state();
      if (!state.open) {
        if (this.previewDebounce !== null) {
          clearTimeout(this.previewDebounce);
          this.previewDebounce = null;
        }
        return;
      }
      const sub = this.subscriptionState.current();
      if (sub === null) return;
      this.seats.set(sub.seats.purchased);
      this.preview.set(null);
      this.submitError.set(null);
      this.scheduledMessage.set(null);
    });

    // Re-fetch preview whenever the seat count changes. Debounced so a
    // rapid +/− tap chain only triggers one HTTP call.
    effect(() => {
      const state = this.modalState.state();
      if (!state.open) return;
      const target = this.seats();
      const sub = this.subscriptionState.current();
      if (sub === null) return;
      if (target === sub.seats.purchased) {
        this.preview.set(null);
        return;
      }
      if (this.previewDebounce !== null) {
        clearTimeout(this.previewDebounce);
      }
      this.previewDebounce = setTimeout(() => this.fetchPreview(target), 250);
    });
  }

  protected close(): void {
    if (this.isSubmitting()) return;
    this.modalState.close();
  }

  protected decrement(): void {
    const next = this.seats() - 1;
    if (next < this.minSeats()) return;
    this.seats.set(next);
  }

  protected increment(): void {
    if (this.isTrial()) return;
    this.seats.set(this.seats() + 1);
  }

  protected outcomeLine(p: SeatPreview): string {
    switch (p.outcome_if_committed) {
      case 'needs_payment':
        return `Charged today (${p.delta} extra seat${p.delta === 1 ? '' : 's'})`;
      case 'scheduled':
        return `Refund (we don't pro-rate seat reductions)`;
      case 'no_change':
        return 'No change';
    }
  }

  protected commit(): void {
    if (this.isSubmitting()) return;
    this.isSubmitting.set(true);
    this.submitError.set(null);
    this.scheduledMessage.set(null);

    this.api.changeSeats(this.seats()).subscribe({
      next: (response) => {
        switch (response.outcome) {
          case 'needs_payment':
            // The seat-increase flow also goes through Stripe Checkout
            // for the prorated charge; the response carries the URL
            // (or `null` if the provider is unconfigured server-side,
            // which means smoke-only environments).
            if (response.checkout_url !== null) {
              window.location.href = response.checkout_url;
              return;
            }
            this.isSubmitting.set(false);
            this.submitError.set(
              'Payment provider unavailable. Please try again later.',
            );
            return;
          case 'scheduled':
            this.isSubmitting.set(false);
            this.scheduledMessage.set(
              `Your seat count will reduce to ${response.to_seats} at next renewal.`,
            );
            // Refresh the cached subscription so the Billing page
            // reflects the parked change.
            this.subscriptionState.notifyChanged();
            return;
          case 'no_change':
            this.modalState.close();
            return;
        }
      },
      error: (err) => {
        this.isSubmitting.set(false);
        this.submitError.set(extractErrorMessage(err));
      },
    });
  }

  private fetchPreview(totalSeats: number): void {
    this.previewLoading.set(true);
    this.api.previewSeats(totalSeats).subscribe({
      next: (p) => {
        this.preview.set(p);
        this.previewLoading.set(false);
      },
      error: () => {
        this.preview.set(null);
        this.previewLoading.set(false);
      },
    });
  }
}


function extractErrorMessage(err: unknown): string {
  const e = err as {
    error?: {
      error?: string;
      seats_in_use?: number;
      min_allowed?: number;
    };
  };
  const code = e.error?.error;
  switch (code) {
    case 'seats_below_in_use':
      return `You have ${e.error?.seats_in_use ?? 'too many'} active users — at least ${e.error?.min_allowed ?? 'enough'} seats are required.`;
    case 'seats_below_minimum':
      return `This plan requires at least ${e.error?.min_allowed ?? 5} seats.`;
    case 'trial_cannot_add_seats':
      return 'Trial plans cannot add seats — upgrade first.';
    case 'cannot_change_cancelled':
      return 'Your subscription is cancelled — contact support to reactivate.';
    case 'no_active_subscription':
      return 'No active subscription to manage.';
    default:
      return 'Something went wrong. Please try again.';
  }
}
