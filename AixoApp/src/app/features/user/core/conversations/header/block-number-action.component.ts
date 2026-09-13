import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import { BlockListService, BlockReason } from '../../whatsapp/block-list/block-list.service';

/**
 * "Block this number" quick action on the chat-thread header
 * (whatsapp-platform-upgrade Step 23).
 *
 * Owner / Admin only (gated on `whatsapp.opt_in.manage` — the
 * button hides for junior staff, and the API rejects them with
 * 403 even if they craft the request manually). Reason picker is
 * required; an optional notes field is shown below.
 */
@Component({
  selector: 'app-conversation-block-number-action',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    @if (canManage()) {
      <button
        type="button"
        class="inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-surface px-2.5 py-1 text-xs font-medium text-red-400 hover:bg-red-500/10"
        (click)="toggle(); $event.stopPropagation()"
        aria-label="Block this number"
      >
        <lucide-icon name="x-circle" class="h-3 w-3" />
        Block
      </button>

      @if (open()) {
        <!-- Fixed-position modal so the dialog is never clipped by the
             chat-details rail's overflow-y:auto (which was making the
             old absolute popover render half-hidden at the bottom edge). -->
        <div
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          (click)="close()"
        >
          <div
            class="w-full max-w-md rounded-lg bg-surface shadow-xl ring-1 border-subtle"
            (click)="$event.stopPropagation()"
            role="dialog"
            aria-modal="true"
            aria-labelledby="block-number-title"
          >
            <header class="border-b border-subtle px-4 py-3 md:px-6 md:py-4">
              <h2 id="block-number-title" class="text-base font-semibold text-default">
                Block number
              </h2>
              <p class="mt-1 text-[14px] text-muted">
                Future messages from
                <span class="font-mono text-default">{{ phoneNumber() }}</span>
                will be silently dropped. This action can be undone from Settings → WhatsApp →
                Blocked numbers.
              </p>
            </header>

            <div class="space-y-4 px-4 md:px-6 py-5 text-sm">
              <label class="block">
                <span class="mb-1 block text-xs font-medium text-default">Reason</span>
                <select
                  class="block w-full rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm focus:border-muted focus:outline-none"
                  [ngModel]="reason()"
                  (ngModelChange)="reason.set($event)"
                >
                  <option value="spam">Spam</option>
                  <option value="fraud">Fraud</option>
                  <option value="requested">Requested by customer</option>
                  <option value="harassment">Harassment</option>
                  <option value="other">Other</option>
                </select>
              </label>

              <label class="block">
                <span class="mb-1 block text-xs font-medium text-default">
                  Notes <span class="text-faint">(optional)</span>
                </span>
                <textarea
                  rows="3"
                  class="block w-full rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm focus:border-muted focus:outline-none"
                  placeholder="Add context for your team…"
                  [ngModel]="notes()"
                  (ngModelChange)="notes.set($event)"
                ></textarea>
              </label>

              @if (error(); as err) {
                <div
                  class="rounded-md border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-400"
                >
                  {{ err }}
                </div>
              }
            </div>

            <footer
              class="flex items-center justify-end gap-2 border-t border-subtle px-4 md:px-6 py-3"
            >
              <button
                type="button"
                (click)="close()"
                [disabled]="busy()"
                class="rounded-lg border border-subtle bg-surface px-3 py-1.5 text-sm font-medium text-default hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                [disabled]="busy()"
                (click)="submit()"
                class="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {{ busy() ? 'Blocking…' : 'Block number' }}
              </button>
            </footer>
          </div>
        </div>
      }
    }
  `,
})
export class ConversationBlockNumberActionComponent {
  private readonly api = inject(BlockListService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  readonly phoneNumber = input.required<string>();
  readonly blocked = output<void>();

  protected readonly open = signal<boolean>(false);
  protected readonly busy = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly reason = signal<BlockReason>('spam');
  protected readonly notes = signal<string>('');

  protected canManage(): boolean {
    return this.auth.hasPermission('whatsapp.opt_in.manage');
  }

  protected toggle(): void {
    this.open.set(!this.open());
    this.error.set(null);
  }

  protected close(): void {
    this.open.set(false);
  }

  protected submit(): void {
    const phone = this.phoneNumber();
    if (!phone) return;
    this.busy.set(true);
    this.error.set(null);
    this.api
      .add({
        phone_number: phone,
        reason: this.reason(),
        notes: this.notes() || null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.busy.set(false);
          this.open.set(false);
          this.notes.set('');
          this.blocked.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.busy.set(false);
          this.error.set(extractApiError(err) ?? 'Could not block number.');
        },
      });
  }
}
