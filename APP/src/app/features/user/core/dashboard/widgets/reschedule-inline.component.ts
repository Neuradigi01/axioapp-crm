import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  Output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { LucideAngularModule } from 'lucide-angular';

import { MobileDateTimeComponent } from '../../shared/forms/mobile-datetime.component';

/**
 * Inline datetime picker that replaces a follow-up row's action bar
 * when the user clicks Reschedule. Not a modal — the widget rows are
 * dense and a modal would feel heavy for a 1-second interaction.
 *
 * Emits `save` with an ISO-8601 datetime string; the widget owns the
 * HTTP call. Emits `cancel` to close without changes.
 *
 * The initial value is seeded from the row's current `due_at`; if
 * that's null we default to "today at 10:00" — matches how the New
 * Task modal defaults new rows.
 */
@Component({
  selector: 'app-reschedule-inline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule, MobileDateTimeComponent],
  template: `
    <div class="flex flex-wrap items-center gap-2 rounded-md border border-subtle bg-surface-2 p-2">
      <div class="flex-1 min-w-[12rem]">
        <crm-mobile-datetime
          [value]="localValue()"
          (valueChange)="localValue.set($event)"
          placeholder="Pick date & time"
        />
      </div>
      <button
        type="button"
        (click)="onSave()"
        [disabled]="!localValue()"
        class="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white hover:brightness-95 disabled:cursor-not-allowed disabled:bg-surface-2"
      >
        <lucide-icon name="check" size="14" aria-hidden="true"></lucide-icon>
        Save
      </button>
      <button
        type="button"
        (click)="cancel.emit()"
        class="inline-flex items-center gap-1 rounded-md border border-subtle bg-surface px-2.5 py-1 text-xs font-medium text-default hover:bg-surface-2"
      >
        <lucide-icon name="x" size="14" aria-hidden="true"></lucide-icon>
        Cancel
      </button>
    </div>
  `,
})
export class RescheduleInlineComponent {
  @Input() set initialDueAt(value: string | null) {
    this.localValue.set(value ? this.toDatetimeLocal(value) : this.defaultToday10am());
  }

  @Output() readonly save = new EventEmitter<string>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly localValue = signal(this.defaultToday10am());

  protected onSave(): void {
    const v = this.localValue();
    if (!v) return;
    // Convert the datetime-local string ("YYYY-MM-DDTHH:mm") into
    // an ISO-8601 UTC string the backend expects.
    this.save.emit(new Date(v).toISOString());
  }

  private defaultToday10am(): string {
    const d = new Date();
    d.setHours(10, 0, 0, 0);
    return this.toDatetimeLocal(d.toISOString());
  }

  /** Convert a backend ISO string to a "YYYY-MM-DDTHH:mm" the
   *  <input type="datetime-local"> element accepts. */
  private toDatetimeLocal(iso: string): string {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }
}
