import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  effect,
  forwardRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

/**
 * Drop-in replacement for a native `<select>` where the OS-native
 * dropdown popup overflows in Chrome DevTools' mobile emulation.
 *
 * Real mobile browsers render `<select>` as a nicely-sized OS picker,
 * but the DevTools popup renders at the actual browser window level
 * and appears to spill past the emulated viewport. This component
 * renders an in-DOM dropdown constrained to its own width so it
 * behaves identically at every viewport size — no browser-controlled
 * popup, no overflow.
 *
 * API mirrors a controlled native select:
 *   <crm-mobile-select
 *     [options]="opts"
 *     [value]="current"
 *     placeholder="— pick one —"
 *     (valueChange)="setCurrent($event)" />
 *
 * `options` is `Array<{ value: string; label: string }>`.
 */
export interface MobileSelectOption {
  readonly value: string;
  readonly label: string;
  /** Optional group heading. Consecutive options that share the same
   *  `group` string render under a single sticky-style header — mirrors
   *  the native `<optgroup>` behaviour. Options without a `group` render
   *  ungrouped (also legal). */
  readonly group?: string;
}

@Component({
  selector: 'crm-mobile-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => MobileSelectComponent),
      multi: true,
    },
  ],
  template: `
    <div class="relative">
      <button
        type="button"
        class="flex w-full items-center justify-between rounded border border-subtle bg-surface px-2 py-1.5 text-left text-xs text-default hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50"
        [attr.aria-expanded]="open()"
        [attr.aria-haspopup]="'listbox'"
        [disabled]="disabled()"
        (click)="toggle()"
      >
        <span class="truncate">{{ activeLabel() }}</span>
        <lucide-icon
          [name]="open() ? 'chevron-up' : 'chevron-down'"
          class="ml-1 h-3.5 w-3.5 shrink-0 text-faint"
        />
      </button>
      @if (open()) {
        <div class="fixed inset-0 z-30" (click)="close()" aria-hidden="true"></div>
        <div
          class="absolute top-full right-0 left-0 z-40 mt-1 max-h-[60vh] overflow-y-auto rounded-md border border-subtle bg-surface p-1 shadow-lg"
          role="listbox"
        >
          @for (opt of options(); track opt.value; let i = $index) {
            @if (opt.group && opt.group !== options()[i - 1]?.group) {
              <div
                class="px-2 pt-2 pb-1 text-[10px] font-semibold tracking-[.06em] text-faint uppercase"
              >
                {{ opt.group }}
              </div>
            }
            <button
              type="button"
              role="option"
              [attr.aria-selected]="opt.value === currentValue()"
              class="flex w-full items-center rounded px-2 py-1.5 text-left text-xs transition"
              [class.bg-accent-soft]="opt.value === currentValue()"
              [class.text-accent]="opt.value === currentValue()"
              [class.text-default]="opt.value !== currentValue()"
              [class.hover:bg-surface-2]="opt.value !== currentValue()"
              (click)="pick(opt.value)"
            >
              {{ opt.label }}
            </button>
          }
        </div>
      }
    </div>
  `,
})
export class MobileSelectComponent implements ControlValueAccessor {
  readonly options = input.required<ReadonlyArray<MobileSelectOption>>();
  /** `[value]` binding — used by callers who don't want a FormControl. */
  readonly value = input<string>('');
  readonly placeholder = input<string>('Select…');
  readonly valueChange = output<string>();
  /** Also disable-able via a FormControl (`control.disable()`). */
  readonly disabled = signal(false);

  protected readonly open = signal(false);
  private readonly host = inject(ElementRef<HTMLElement>);

  /** Single source of truth for the currently-selected value. Written
   *  by either the `[value]` input (via `effect`) or Angular Forms
   *  (via `writeValue`). Reads `writtenValue` first so a form control
   *  can override an initial input value. */
  private readonly writtenValue = signal<string | null>(null);
  protected readonly currentValue = computed<string>(() => {
    const w = this.writtenValue();
    return w !== null ? w : this.value();
  });

  private onChangeFn: (v: string) => void = () => undefined;
  private onTouchedFn: () => void = () => undefined;

  constructor() {
    // Mirror any external `[value]` change into `writtenValue` so
    // template + form path both agree.
    effect(() => {
      const v = this.value();
      if (v !== this.writtenValue()) this.writtenValue.set(v);
    });
  }

  // --- ControlValueAccessor ------------------------------------------
  writeValue(value: string | null | undefined): void {
    this.writtenValue.set(value ?? '');
  }

  registerOnChange(fn: (v: string) => void): void {
    this.onChangeFn = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouchedFn = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled.set(isDisabled);
  }
  // -------------------------------------------------------------------

  protected readonly activeLabel = computed<string>(() => {
    const v = this.currentValue();
    const hit = this.options().find((o) => o.value === v);
    return hit?.label ?? this.placeholder();
  });

  protected toggle(): void {
    if (this.disabled()) return;
    this.open.update((v) => !v);
  }

  protected close(): void {
    this.open.set(false);
    this.onTouchedFn();
  }

  protected pick(v: string): void {
    this.writtenValue.set(v);
    this.valueChange.emit(v);
    this.onChangeFn(v);
    this.close();
  }

  /** Close on Escape when focus is inside the component. */
  @HostListener('keydown.escape')
  onEsc(): void {
    if (this.open()) this.close();
  }

  /** Close on outside click when we're open (backdrop already covers
   *  the general case; this is the belt-and-braces for click paths
   *  that skip the backdrop, e.g. inside another portal). */
  @HostListener('document:mousedown', ['$event.target'])
  onDocumentClick(target: EventTarget | null): void {
    if (!this.open()) return;
    const el = this.host.nativeElement;
    if (target instanceof Node && !el.contains(target)) this.close();
  }
}
