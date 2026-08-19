import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { LucideAngularModule } from 'lucide-angular';

import type { ColumnFilterOption, ColumnFilterType } from './column-filter.types';

/**
 * Reusable column-header filter popover.
 *
 * Sits on any table `<th>` and opens a searchable checkbox list
 * (multi-select) — the selected value(s) come back via `valueChange`
 * as a plain `string[]`. Trigger renders as the column label + chevron
 * + a small accent dot when a filter is active.
 *
 * Portalled to `document.body` (same pattern as `crm-mobile-select`)
 * so the popover is not clipped by the table wrapper's
 * `overflow-hidden` / `md:overflow-x-auto`. The trigger closes on
 * outside-click, Escape, or a viewport resize/scroll re-anchors the
 * panel.
 *
 * Usage — any list page can wire this up by supplying its own options
 * and holding the selected values in a signal:
 *
 *     <app-column-filter
 *       label="Source"
 *       filterType="multi-select"
 *       [options]="sourceOptions()"
 *       [value]="sourceFilter()"
 *       (valueChange)="sourceFilter.set($event)"
 *     />
 *
 * The component is intentionally page-agnostic — the caller owns
 * option loading (which is why options is a plain input, not a
 * fetch-inside-popover) and owns the API side. Reuse pattern lives
 * next to the types in `column-filter.types.ts`.
 */
@Component({
  selector: 'app-column-filter',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  template: `
    <button
      type="button"
      class="inline-flex items-center gap-1 transition hover:text-default focus:outline-none"
      [class.text-accent]="active()"
      [attr.aria-expanded]="open()"
      [attr.aria-haspopup]="'listbox'"
      [attr.aria-label]="'Filter by ' + label()"
      (click)="toggle($event)"
    >
      <span>{{ label() }}</span>
      @if (active()) {
        <span
          class="inline-block h-1.5 w-1.5 rounded-full bg-accent"
          [attr.aria-label]="value().length + ' active filter'"
        ></span>
      }
      <lucide-icon
        [name]="open() ? 'chevron-up' : 'chevron-down'"
        class="h-3 w-3 shrink-0 opacity-70"
      />
    </button>
    @if (open()) {
      <div #backdrop class="fixed inset-0 z-[1000]" (click)="close()" aria-hidden="true"></div>
      <div
        #panel
        class="fixed z-[1001] flex max-h-[70vh] w-[240px] flex-col overflow-hidden rounded-md border border-subtle bg-surface shadow-lg"
        [style.top]="panelStyle()?.top"
        [style.left]="panelStyle()?.left"
        role="dialog"
        [attr.aria-label]="'Filter ' + label()"
        (click)="$event.stopPropagation()"
      >
        <div class="border-b border-subtle p-2">
          <div class="relative">
            <lucide-icon
              name="search"
              class="pointer-events-none absolute top-1/2 left-2 h-3.5 w-3.5 -translate-y-1/2 text-faint"
            />
            <input
              #searchInput
              type="search"
              [value]="searchTerm()"
              (input)="onSearch($event)"
              (keydown.escape)="close()"
              placeholder="Search…"
              class="w-full rounded border border-subtle bg-surface-2 py-1 pr-2 pl-7 text-xs text-default placeholder:text-faint focus:border-accent focus:outline-none"
              [attr.aria-label]="'Search ' + label()"
            />
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-1" role="listbox" aria-multiselectable="true">
          @if (visibleOptions().length === 0) {
            <div class="px-2 py-4 text-center text-[11px] text-faint">No matches.</div>
          } @else {
            @for (opt of visibleOptions(); track opt.value) {
              <label
                class="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-xs text-default transition hover:bg-surface-2"
                role="option"
                [attr.aria-selected]="isChecked(opt.value)"
              >
                <input
                  type="checkbox"
                  class="checkbox h-3.5 w-3.5"
                  [checked]="isChecked(opt.value)"
                  (change)="toggleValue(opt.value)"
                />
                <span class="truncate">{{ opt.label }}</span>
              </label>
            }
          }
        </div>
        <div
          class="flex items-center justify-between gap-2 border-t border-subtle bg-surface-2 px-2 py-1.5"
        >
          <button
            type="button"
            class="text-[11px] text-faint transition hover:text-default disabled:cursor-not-allowed disabled:opacity-40"
            [disabled]="!active()"
            (click)="clear()"
          >
            Clear
          </button>
          <span class="text-[11px] text-faint">
            @if (value().length > 0) {
              {{ value().length }} selected
            }
          </span>
        </div>
      </div>
    }
  `,
})
export class ColumnFilterComponent {
  /** Column header label rendered on the trigger and inside the popover. */
  readonly label = input.required<string>();

  /** Widget the popover renders. Only `multi-select` is drawn today;
   *  the other names are reserved so pages can already declare their
   *  intended widget without a config-shape churn later. */
  readonly filterType = input<ColumnFilterType>('multi-select');

  /** Options rendered as the checkbox list. Callers own loading /
   *  memoisation — pass a plain array (or the return of a signal) and
   *  the popover renders it. */
  readonly options = input<readonly ColumnFilterOption[]>([]);

  /** Currently-selected values. Kept as `string[]` (not `Set`) so the
   *  input is a plain, comparable JSON value — pages that persist the
   *  filter through the URL can just `.join(',')` on the way out. */
  readonly value = input<readonly string[]>([]);

  /** Emitted when the user checks / unchecks / clears — the caller
   *  drives the round-trip. Every emission is a full new array; the
   *  popover never mutates the input. */
  readonly valueChange = output<string[]>();

  protected readonly open = signal(false);
  protected readonly searchTerm = signal('');
  protected readonly panelStyle = signal<{ top: string; left: string } | null>(null);

  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly panelRef = viewChild<ElementRef<HTMLElement>>('panel');
  protected readonly backdropRef = viewChild<ElementRef<HTMLElement>>('backdrop');
  protected readonly searchInputRef = viewChild<ElementRef<HTMLInputElement>>('searchInput');

  /** True whenever at least one option is selected. Drives the trigger
   *  active dot + Clear button enable-state. */
  protected readonly active = computed<boolean>(() => this.value().length > 0);

  /** Options filtered by the search input. Case-insensitive substring
   *  match against `label`, with the current selection pinned to the
   *  top so users can uncheck without hunting past unchecked matches. */
  protected readonly visibleOptions = computed<readonly ColumnFilterOption[]>(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const opts = this.options();
    const selectedSet = new Set(this.value());
    const matched = term ? opts.filter((o) => o.label.toLowerCase().includes(term)) : opts;
    return [...matched].sort((a, b) => {
      const aSel = selectedSet.has(a.value) ? 0 : 1;
      const bSel = selectedSet.has(b.value) ? 0 : 1;
      return aSel - bSel;
    });
  });

  /** Portalled node's original parent so we can put the panel back
   *  before Angular tears down the `@if` block. Same shape as
   *  `crm-mobile-select` — see that file for the "renderer removeChild
   *  throws when node's real parent is document.body" story. */
  private originalParent: HTMLElement | null = null;

  constructor() {
    // Refine the panel position once the panel is actually in the DOM
    // (the initial anchor is measured from the trigger rect + a
    // conservative height estimate; the real panel is usually shorter).
    effect(() => {
      if (this.open() && this.panelRef()) {
        queueMicrotask(() => {
          this.refinePosition();
          this.searchInputRef()?.nativeElement?.focus();
        });
      }
    });

    // Portal panel + backdrop to `document.body`. Table wrappers use
    // `overflow-hidden` / `md:overflow-x-auto` — without portalling
    // the popover clips or scrolls with the table.
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

    this.destroyRef.onDestroy(() => {
      this.panelRef()?.nativeElement?.remove();
      this.backdropRef()?.nativeElement?.remove();
    });
  }

  protected toggle(event: MouseEvent): void {
    // Stop the header's `(click)` (e.g. sort) from firing when the
    // filter trigger is nested inside a sortable header.
    event.stopPropagation();
    const nextOpen = !this.open();
    if (nextOpen) {
      this.searchTerm.set('');
      this.positionPanel();
    }
    this.open.set(nextOpen);
  }

  protected close(): void {
    const panel = this.panelRef()?.nativeElement;
    const backdrop = this.backdropRef()?.nativeElement;
    if (panel && backdrop && this.originalParent && panel.parentElement === document.body) {
      this.originalParent.appendChild(backdrop);
      this.originalParent.appendChild(panel);
    }
    this.open.set(false);
    this.panelStyle.set(null);
  }

  protected onSearch(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.searchTerm.set(input.value);
  }

  protected isChecked(value: string): boolean {
    return this.value().includes(value);
  }

  protected toggleValue(value: string): void {
    const current = this.value();
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    this.valueChange.emit(next);
  }

  protected clear(): void {
    if (!this.active()) return;
    this.valueChange.emit([]);
  }

  /** Anchor the panel under the trigger, flipping above / clamping
   *  horizontally to keep it on-screen. */
  private positionPanel(estimatedHeight = 320): void {
    const trigger = this.host.nativeElement.querySelector(
      'button[type="button"]',
    ) as HTMLElement | null;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const PANEL_W = 240;
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
    });
  }

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

  @HostListener('keydown.escape')
  onEsc(): void {
    if (this.open()) this.close();
  }

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
