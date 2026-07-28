import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import { ContactsApiService, OptInHistory } from '../contacts-api.service';
import { ContactDataExportButtonComponent } from './data-export-button.component';
import { OptInChipComponent } from './opt-in-chip.component';

/**
 * Opt-in panel on the contact-detail page (Step 22).
 *
 * Shows the current status + immutable consent-log history. Owner /
 * Admin (holders of ``whatsapp.opt_in.manage``) see "Force opt-in"
 * and "Force opt-out" buttons inline with a reason textarea so the
 * override is always audited; junior staff see read-only.
 */
@Component({
  selector: 'app-opt-in-section',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, OptInChipComponent, ContactDataExportButtonComponent],
  template: `
    <section class="rounded-md border border-subtle bg-surface p-4">
      <header class="mb-3 flex items-center justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-muted">WhatsApp opt-in</p>
          <p class="text-[11px] text-muted">DPDP-grade consent record.</p>
        </div>
        <div class="flex items-center gap-2">
          <app-contact-data-export-button [contactId]="contactId()" />
          @if (history(); as h) {
            <app-opt-in-chip [status]="h.status" />
          }
        </div>
      </header>

      @if (loading()) {
        <p class="text-[11px] text-muted">Loading…</p>
      }
      @if (error(); as err) {
        <p class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400">
          {{ err }}
        </p>
      }
      @if (history(); as h) {
        <dl class="mb-3 grid grid-cols-2 gap-2 text-xs">
          <div>
            <dt class="text-[10px] uppercase text-muted">Source</dt>
            <dd class="text-default">{{ h.source ?? '—' }}</dd>
          </div>
          <div>
            <dt class="text-[10px] uppercase text-muted">Recorded</dt>
            <dd class="text-default">{{ formatDate(h.recorded_at) }}</dd>
          </div>
          @if (h.opt_out_recorded_at) {
            <div
              class="col-span-2 rounded-md border border-red-500/20 bg-red-500/10 px-2 py-1 text-red-400"
            >
              <dt class="text-[10px] uppercase text-red-400">Opted out</dt>
              <dd>
                {{ formatDate(h.opt_out_recorded_at) }}
                @if (h.opt_out_reason) {
                  — {{ h.opt_out_reason }}
                }
              </dd>
            </div>
          }
        </dl>

        @if (canManage()) {
          <div class="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            <button
              type="button"
              class="rounded-md border border-emerald-300 bg-surface px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
              [disabled]="busy() || h.status === 'opted_in'"
              (click)="manualOptIn()"
            >
              Mark opted-in
            </button>
            <button
              type="button"
              class="rounded-md border border-red-500/30 bg-surface px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/10 disabled:opacity-50"
              [disabled]="busy() || h.status === 'opted_out'"
              (click)="manualOptOut()"
            >
              Mark opted-out
            </button>
          </div>
          <textarea
            class="mb-2 w-full rounded-md border border-subtle px-2 py-1 text-xs"
            rows="2"
            placeholder="Optional reason — recorded on the consent log."
            [ngModel]="reason()"
            (ngModelChange)="reason.set($event)"
            maxlength="500"
          ></textarea>
        } @else {
          <p class="text-[11px] text-muted">
            Manual override requires the
            <code>whatsapp.opt_in.manage</code> permission.
          </p>
        }

        <details>
          <summary
            class="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-muted hover:text-default"
          >
            Consent log ({{ h.events.length }})
          </summary>
          @if (h.events.length === 0) {
            <p class="mt-1 text-[11px] text-muted">No events yet.</p>
          } @else {
            <ul class="mt-2 space-y-1.5 text-xs">
              @for (e of h.events; track e.id) {
                <li class="rounded border border-subtle px-2 py-1">
                  <div class="flex items-baseline justify-between">
                    <span class="font-medium text-default">
                      {{ e.old_status ?? '∅' }} → {{ e.new_status }}
                    </span>
                    <span class="text-[10px] text-muted">
                      {{ formatDate(e.recorded_at) }}
                    </span>
                  </div>
                  <p class="text-[11px] text-muted">
                    {{ humanSource(e.source) }}{{ e.reason ? ' — ' + e.reason : '' }}
                  </p>
                </li>
              }
            </ul>
          }
        </details>
      }
    </section>
  `,
})
export class OptInSectionComponent {
  private readonly api = inject(ContactsApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  readonly contactId = input.required<string>();

  protected readonly loading = signal<boolean>(false);
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly history = signal<OptInHistory | null>(null);
  protected readonly reason = signal<string>('');

  protected readonly canManage = (): boolean => this.auth.hasPermission('whatsapp.opt_in.manage');

  constructor() {
    effect(() => {
      const id = this.contactId();
      if (id) this.load(id);
    });
  }

  protected formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return '—';
    return parsed.toLocaleString();
  }

  protected humanSource(source: string | null | undefined): string {
    switch (source) {
      case 'form_widget':
        return 'Form widget';
      case 'bulk_import':
        return 'Bulk import';
      case 'manual_entry':
        return 'Manual override';
      case 'inbound_first_message':
        return 'First inbound message';
      case 'explicit_opt_in_link':
        return 'Explicit opt-in link';
      case 'stop_keyword':
        return 'STOP keyword';
      default:
        return source ?? 'Unknown';
    }
  }

  protected manualOptIn(): void {
    const id = this.contactId();
    if (!id) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .recordOptIn(id, {
        source: 'manual_entry',
        reason: this.reason() || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.reason.set('');
          this.load(id);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not record opt-in.');
        },
      });
  }

  protected manualOptOut(): void {
    const id = this.contactId();
    if (!id) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .recordOptOut(id, { reason: this.reason() || null })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.reason.set('');
          this.load(id);
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not record opt-out.');
        },
      });
  }

  private load(id: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .getOptIn(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (h) => {
          this.history.set(h);
          this.loading.set(false);
          this.busy.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loading.set(false);
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not load opt-in.');
        },
      });
  }
}
