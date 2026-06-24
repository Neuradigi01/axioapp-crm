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
import {
  BlockListService,
  BlockReason,
} from '../../whatsapp/block-list/block-list.service';

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
      <div class="relative inline-block">
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-full border border-rose-300 bg-white px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50"
          (click)="toggle(); $event.stopPropagation()"
          aria-label="Block this number"
        >
          <lucide-icon name="x-circle" class="h-3 w-3" />
          Block
        </button>
        @if (open()) {
          <div
            class="absolute right-0 z-50 mt-1 w-64 rounded-md border border-zinc-200 bg-white p-3 text-xs shadow-lg"
            (click)="$event.stopPropagation()"
          >
            <p class="mb-2 font-semibold text-zinc-800">
              Block {{ phoneNumber() }}
            </p>
            <label class="mb-2 block">
              <span class="mb-1 block text-zinc-700">Reason</span>
              <select
                class="w-full rounded-md border border-zinc-300 px-2 py-1"
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
            <label class="mb-2 block">
              <span class="mb-1 block text-zinc-700">Notes</span>
              <textarea
                rows="2"
                class="w-full rounded-md border border-zinc-300 px-2 py-1"
                [ngModel]="notes()"
                (ngModelChange)="notes.set($event)"
              ></textarea>
            </label>
            @if (error(); as err) {
              <p class="mb-1 text-[11px] text-rose-700">{{ err }}</p>
            }
            <div class="flex justify-end gap-1">
              <button
                type="button"
                (click)="close()"
                class="rounded border border-zinc-300 bg-white px-2 py-1 text-zinc-700 hover:bg-zinc-50"
              >
                Cancel
              </button>
              <button
                type="button"
                [disabled]="busy()"
                (click)="submit()"
                class="rounded bg-rose-600 px-2 py-1 font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {{ busy() ? 'Blocking…' : 'Block' }}
              </button>
            </div>
          </div>
        }
      </div>
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
          this.error.set(
            extractApiError(err) ?? 'Could not block number.',
          );
        },
      });
  }
}
