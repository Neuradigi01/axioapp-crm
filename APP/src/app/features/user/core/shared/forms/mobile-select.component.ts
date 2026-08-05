import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
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
  template: `
    <div class="relative">
      <button
        type="button"
        class="flex w-full items-center justify-between rounded border border-subtle bg-surface px-2 py-1.5 text-left text-xs text-default hover:bg-surface-2"
        [attr.aria-expanded]="open()"
        [attr.aria-haspopup]="'listbox'"
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
              [attr.aria-selected]="opt.value === value()"
              class="flex w-full items-center rounded px-2 py-1.5 text-left text-xs transition"
              [class.bg-accent-soft]="opt.value === value()"
              [class.text-accent]="opt.value === value()"
              [class.text-default]="opt.value !== value()"
              [class.hover:bg-surface-2]="opt.value !== value()"
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
export class MobileSelectComponent {
  readonly options = input.required<ReadonlyArray<MobileSelectOption>>();
  readonly value = input<string>('');
  readonly placeholder = input<string>('Select…');
  readonly valueChange = output<string>();

  protected readonly open = signal(false);
  private readonly host = inject(ElementRef<HTMLElement>);

  protected readonly activeLabel = computed<string>(() => {
    const v = this.value();
    const hit = this.options().find((o) => o.value === v);
    return hit?.label ?? this.placeholder();
  });

  protected toggle(): void {
    this.open.update((v) => !v);
  }

  protected close(): void {
    this.open.set(false);
  }

  protected pick(v: string): void {
    this.valueChange.emit(v);
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
