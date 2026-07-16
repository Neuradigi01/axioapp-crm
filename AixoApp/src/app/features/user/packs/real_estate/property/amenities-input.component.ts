import {
  ChangeDetectionStrategy,
  Component,
  computed,
  forwardRef,
  input,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Free-form chip input for amenity tags. Push to the array on Enter
 * or comma; click × to remove. No external chip library; uses only
 * Tailwind + native input.
 *
 * Implements `ControlValueAccessor` so it plugs into typed reactive
 * forms with `formControlName="amenities"`.
 */
@Component({
  selector: 'app-amenities-input',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, FormsModule, LucideAngularModule],
  template: `
    <div
      class="flex flex-wrap items-center gap-1.5 rounded-md border border-zinc-200 bg-white p-2 focus-within:border-zinc-400 focus-within:ring-2 focus-within:ring-zinc-200"
    >
      @for (chip of chips(); let idx = $index; track chip + idx) {
        <span
          class="inline-flex items-center gap-1 rounded-full bg-zinc-100 py-0.5 pl-2.5 pr-1 text-xs text-zinc-700 ring-1 ring-zinc-200"
        >
          {{ chip }}
          <button
            type="button"
            (click)="remove(idx)"
            class="ml-0.5 rounded-full p-0.5 text-zinc-400 hover:bg-zinc-200 hover:text-zinc-700"
            aria-label="Remove tag"
          >
            <lucide-icon name="x" class="h-3 w-3"></lucide-icon>
          </button>
        </span>
      }
      <input
        type="text"
        [placeholder]="placeholder()"
        [value]="buffer()"
        (input)="onBufferChange($event)"
        (keydown.enter)="commit($event)"
        (keydown)="onKey($event)"
        (blur)="commitFromBuffer()"
        [disabled]="disabled()"
        class="min-w-32 flex-1 border-0 bg-transparent p-1 text-sm text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
      />
    </div>
  `,
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => AmenitiesInputComponent),
      multi: true,
    },
  ],
})
export class AmenitiesInputComponent implements ControlValueAccessor {
  readonly placeholder = input<string>('Type an amenity and press Enter…');

  protected readonly chips = signal<string[]>([]);
  protected readonly buffer = signal<string>('');
  protected readonly disabled = signal(false);
  protected readonly count = computed(() => this.chips().length);

  private onChange: (v: string[]) => void = () => {};
  private onTouched: () => void = () => {};

  writeValue(value: string[] | null): void {
    this.chips.set(Array.isArray(value) ? [...value] : []);
  }

  registerOnChange(fn: (v: string[]) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }

  protected onBufferChange(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    if (raw.includes(',')) {
      const parts = raw.split(',');
      const tail = parts.pop() ?? '';
      for (const p of parts) this.push(p);
      this.buffer.set(tail);
    } else {
      this.buffer.set(raw);
    }
  }

  protected commit(event: Event): void {
    event.preventDefault();
    this.commitFromBuffer();
  }

  protected commitFromBuffer(): void {
    this.push(this.buffer());
    this.buffer.set('');
    this.onTouched();
  }

  protected onKey(event: KeyboardEvent): void {
    // Backspace on an empty buffer removes the last chip — familiar UX.
    if (event.key === 'Backspace' && this.buffer() === '' && this.chips().length > 0) {
      this.chips.update((c) => c.slice(0, -1));
      this.onChange(this.chips());
    }
  }

  protected remove(index: number): void {
    this.chips.update((c) => c.filter((_, i) => i !== index));
    this.onChange(this.chips());
  }

  private push(raw: string): void {
    const value = raw.trim();
    if (!value) return;
    if (this.chips().includes(value)) return;
    this.chips.update((c) => [...c, value]);
    this.onChange(this.chips());
  }
}
