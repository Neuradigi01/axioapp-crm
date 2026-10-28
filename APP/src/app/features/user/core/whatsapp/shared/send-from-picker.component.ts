import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  input,
  output,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { WhatsAppNumbersService } from './whatsapp-numbers.service';

/**
 * Step 27b — shared "Send from" dropdown.
 *
 * Hides entirely when the org has < 2 connected phones — the
 * single-number UX stays unchanged. When ≥ 2, renders a compact
 * select with the display number + verified name + a small chip
 * marking the default.
 *
 * Consumers (chat-thread composer + campaign create modal) pass
 * the current selection in via `value` + receive changes via the
 * `(valueChange)` output. They also pass an optional
 * `preferredPhoneId` to seed the picker from the inbound's
 * `received_via_phone_id` — that way the composer auto-selects the
 * same number the customer reached.
 */
@Component({
  selector: 'app-wa-send-from-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    @if (numbersService.isMulti()) {
      <label class="flex items-center gap-2 text-xs">
        <span class="font-medium text-zinc-600">{{ label() }}</span>
        <select
          class="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs"
          [value]="effectiveValue()"
          (change)="onChange($any($event.target).value)"
        >
          @for (n of numbers(); track n.phone_id) {
            <option [value]="n.phone_id">
              +{{ n.display_phone_number }}{{ n.verified_name ? ' — ' + n.verified_name : ''
              }}{{ n.is_default ? ' (default)' : '' }}
            </option>
          }
        </select>
      </label>
    }
  `,
})
export class SendFromPickerComponent implements OnInit {
  protected readonly numbersService = inject(WhatsAppNumbersService);
  private readonly destroyRef = inject(DestroyRef);

  readonly value = input<string | null>(null);
  readonly preferredPhoneId = input<string | null>(null);
  readonly label = input<string>('Send from');
  readonly valueChange = output<string | null>();

  protected readonly numbers = this.numbersService.numbers;

  /** Effective selection: explicit value > preferred > default.
   *  Computed so the SELECT reflects all three input sources without
   *  needing the parent to thread the fallback chain itself. */
  protected readonly effectiveValue = computed<string>(() => {
    const explicit = this.value();
    if (explicit) return explicit;
    const preferred = this.preferredPhoneId();
    if (preferred) return preferred;
    return this.numbersService.defaultPhoneId() ?? '';
  });

  ngOnInit(): void {
    this.numbersService
      .ensureLoaded()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        error: (_err: HttpErrorResponse) => {
          // Silent failure — picker just hides (numbers() stays
          // null → isMulti() false). The composer falls back to
          // the backend's default-phone logic.
        },
      });
  }

  protected onChange(phoneId: string): void {
    this.valueChange.emit(phoneId || null);
  }
}
