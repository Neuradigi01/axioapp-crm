import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  computed,
  effect,
  forwardRef,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { FormsModule } from '@angular/forms';

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
  imports: [LucideAngularModule, FormsModule],
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
        [attr.aria-label]="ariaLabel()"
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
        <div #backdrop class="fixed inset-0 z-[1000]" (click)="close()" aria-hidden="true"></div>
        <div
          #panel
          class="fixed z-[1001] flex max-h-[60vh] flex-col rounded-md border border-subtle bg-surface shadow-lg"
          [style.top]="panelStyle()?.top"
          [style.left]="panelStyle()?.left"
          [style.width]="panelStyle()?.width"
          role="listbox"
        >
          @if (searchable()) {
            <div class="border-b border-subtle p-1.5">
              <input
                #searchInput
                type="text"
                [ngModel]="searchQuery()"
                (ngModelChange)="searchQuery.set($event)"
                [placeholder]="searchPlaceholder()"
                class="w-full rounded border border-subtle bg-surface px-2 py-1 text-xs text-default placeholder:text-faint focus:border-muted focus:outline-none focus:ring-1 focus:ring-accent"
                (click)="$event.stopPropagation()"
              />
            </div>
          }
          <div class="overflow-y-auto p-1">
            @for (opt of filteredOptions(); track opt.value; let i = $index) {
              @if (opt.group && opt.group !== filteredOptions()[i - 1]?.group) {
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
            } @empty {
              <div class="px-2 py-3 text-center text-xs text-faint">No matches</div>
            }
          </div>
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
  /** Accessible name for the trigger when no `<label for>` can point
   *  at it (it's a custom component). Omitted from the DOM when null. */
  readonly ariaLabel = input<string | null>(null);
  /** When true, renders a search box at the top of the panel that
   *  filters options by (case-insensitive) substring match on label.
   *  Off by default — small option lists don't need it. */
  readonly searchable = input<boolean>(false);
  readonly searchPlaceholder = input<string>('Search…');
  /** Chip-based multi-select "pick to add" mode. When true, `pick()`
   *  emits `valueChange` without retaining the picked value on the
   *  trigger — the trigger keeps rendering the placeholder so the
   *  operator can keep adding chips. The parent owns the chip strip. */
  readonly pickToAdd = input<boolean>(false);
  readonly valueChange = output<string>();
  /** Also disable-able via a FormControl (`control.disable()`). */
  readonly disabled = signal(false);

  protected readonly open = signal(false);
  protected readonly searchQuery = signal('');
  protected readonly filteredOptions = computed<ReadonlyArray<MobileSelectOption>>(() => {
    const q = this.searchQuery().trim().toLowerCase();
    const all = this.options();
    if (!q) return all;
    return all.filter((o) => o.label.toLowerCase().includes(q));
  });
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  /** `position: fixed` coords for the dropdown panel. Recomputed each
   *  time the panel opens (or the viewport resizes/scrolls) so it
   *  stays glued to the trigger while being body-portaled. */
  protected readonly panelStyle = signal<{ top: string; left: string; width: string } | null>(null);

  /** Single source of truth for the currently-selected value. Written
   *  by either the `[value]` input (via `effect`) or Angular Forms
   *  (via `writeValue`). Reads `writtenValue` first so a form control
   *  can override an initial input value. */
  private readonly writtenValue = signal<string | null>(null);
  /** Flips true the first time Angular Forms calls `writeValue`. Once
   *  set, the `[value]` input sync effect stops writing so a
   *  form-control-owned value can't be clobbered by the input's default
   *  empty string on the effect's first run (which fires AFTER
   *  writeValue during CVA setup — the exact bug that blanked the
   *  Channel dropdown when navigating Step 2 → Step 1). */
  private readonly formControlOwned = signal(false);
  protected readonly currentValue = computed<string>(() => {
    const w = this.writtenValue();
    return w !== null ? w : this.value();
  });

  private onChangeFn: (v: string) => void = () => undefined;
  private onTouchedFn: () => void = () => undefined;

  protected readonly panelRef = viewChild<ElementRef<HTMLElement>>('panel');
  protected readonly backdropRef = viewChild<ElementRef<HTMLElement>>('backdrop');
  protected readonly searchInputRef = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  /** Original parent of the panel/backdrop before we portal them to
   *  `document.body`. We put them back before the `@if` teardown so
   *  Angular's renderer can remove the nodes from a parent it knows
   *  about. */
  private originalParent: HTMLElement | null = null;

  constructor() {
    // Mirror any external `[value]` change into `writtenValue` so
    // template + form path both agree. `writtenValue` is read via
    // `untracked` so the effect only fires when the input actually
    // changes — otherwise a user pick (which sets writtenValue) would
    // re-trigger the effect and clobber it back to the input value.
    // Skipped entirely once a FormControl has taken ownership so
    // Angular Forms's writeValue isn't overwritten by the input's
    // default '' on the effect's first pass.
    effect(() => {
      const v = this.value();
      if (untracked(() => this.formControlOwned())) return;
      if (v !== untracked(() => this.writtenValue())) this.writtenValue.set(v);
    });

    // Refine the panel position once the actual panel is in the DOM.
    // Also focus the search input on open (searchable variant).
    effect(() => {
      if (this.open() && this.panelRef()) {
        queueMicrotask(() => {
          this.refinePosition();
          if (this.searchable()) this.searchInputRef()?.nativeElement.focus();
        });
      }
    });

    // Portal the panel + backdrop to `document.body`. `position: fixed`
    // is broken by any ancestor with `transform` / `filter` /
    // `perspective` — Tailwind's `-translate-x-1/2 -translate-y-1/2`
    // modal-centering pattern triggers this. Portalling to body means
    // the backdrop truly covers the viewport (so outside-clicks close
    // the dropdown instead of falling through to the modal's own
    // backdrop and closing the whole modal), and the panel positions
    // correctly regardless of the caller's DOM.
    effect(() => {
      if (!this.open()) return;
      const panel = this.panelRef()?.nativeElement;
      const backdrop = this.backdropRef()?.nativeElement;
      if (!panel || !backdrop) return;
      if (panel.parentElement !== document.body) {
        this.originalParent = panel.parentElement;
        document.body.appendChild(backdrop);
        document.body.appendChild(panel);
      }
    });

    // Safety net: if the component is destroyed while the panel is
    // still portaled, yank the orphaned nodes from body.
    this.destroyRef.onDestroy(() => {
      this.panelRef()?.nativeElement?.remove();
      this.backdropRef()?.nativeElement?.remove();
    });
  }

  // --- ControlValueAccessor ------------------------------------------
  writeValue(value: string | null | undefined): void {
    this.formControlOwned.set(true);
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
    const nextOpen = !this.open();
    if (nextOpen) {
      // Seed a position from the trigger's rect so the first paint
      // isn't at (0,0); the effect above refines it after the panel
      // measures its true height.
      this.positionPanel();
    }
    this.open.set(nextOpen);
  }

  protected close(): void {
    // Move the portaled nodes back to their original parent BEFORE
    // Angular tears down the `@if (open())` view — otherwise the
    // renderer's `removeChild(originalParent, node)` throws because
    // the node's real parent is now `document.body`.
    const panel = this.panelRef()?.nativeElement;
    const backdrop = this.backdropRef()?.nativeElement;
    if (panel && backdrop && this.originalParent && panel.parentElement === document.body) {
      this.originalParent.appendChild(backdrop);
      this.originalParent.appendChild(panel);
    }
    this.open.set(false);
    this.panelStyle.set(null);
    this.searchQuery.set('');
    this.onTouchedFn();
  }

  protected pick(v: string): void {
    // Pick-to-add mode leaves `writtenValue` on '' so the trigger keeps
    // rendering the placeholder (`activeLabel()` falls back when no
    // option matches the current value). The parent's chip strip owns
    // the picked-values state.
    if (!this.pickToAdd()) {
      this.writtenValue.set(v);
    }
    // Notify Angular Forms BEFORE emitting valueChange so a parent
    // (valueChange) handler that reads the FormControl value sees the
    // just-picked value, not the previous one. Register's onCountryChange
    // relies on this to load states for the newly-selected country.
    this.onChangeFn(v);
    this.valueChange.emit(v);
    this.close();
  }

  /** Compute a fixed-position for the panel that sits below the
   *  trigger when there's room, above otherwise, and never spills
   *  past the viewport horizontally. */
  private positionPanel(estimatedHeight = 240): void {
    const trigger = this.host.nativeElement.querySelector(
      'button[type="button"]',
    ) as HTMLElement | null;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const PANEL_W = Math.max(160, Math.min(rect.width, vw - 16));
    const h = Math.min(estimatedHeight, vh - 16);
    const spaceBelow = vh - rect.bottom;
    const spaceAbove = rect.top;
    let top: number;
    if (spaceBelow >= h + 8 || spaceBelow >= spaceAbove) {
      top = rect.bottom + 4;
    } else {
      top = rect.top - h - 4;
    }
    top = Math.max(8, Math.min(top, vh - h - 8));
    const left = Math.max(8, Math.min(rect.left, vw - PANEL_W - 8));
    this.panelStyle.set({
      top: `${Math.round(top)}px`,
      left: `${Math.round(left)}px`,
      width: `${Math.round(PANEL_W)}px`,
    });
  }

  /** Re-anchor with the true measured height once the panel is in the
   *  DOM — the estimate can be wildly off for long option lists. */
  private refinePosition(): void {
    const el = this.panelRef()?.nativeElement;
    if (!el) return;
    this.positionPanel(el.offsetHeight);
  }

  @HostListener('window:resize')
  onResize(): void {
    if (this.open()) this.positionPanel();
  }

  @HostListener('window:scroll')
  onWindowScroll(): void {
    if (this.open()) this.positionPanel();
  }

  /** Close on Escape when focus is inside the component. */
  @HostListener('keydown.escape')
  onEsc(): void {
    if (this.open()) this.close();
  }

  /** Close on outside click when we're open. Panel + backdrop are
   *  portaled to `document.body`, so `host.contains(panel)` is false —
   *  check panel/backdrop explicitly so clicks on options don't close
   *  before `pick()` fires. */
  @HostListener('document:mousedown', ['$event.target'])
  onDocumentClick(target: EventTarget | null): void {
    if (!this.open()) return;
    if (!(target instanceof Node)) return;
    const el = this.host.nativeElement;
    const panel = this.panelRef()?.nativeElement;
    const backdrop = this.backdropRef()?.nativeElement;
    if (el.contains(target)) return;
    if (panel && panel.contains(target)) return;
    if (backdrop && backdrop.contains(target)) return;
    this.close();
  }
}
