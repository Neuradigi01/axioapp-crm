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

/**
 * In-viewport date + time picker. Same idea as `<crm-mobile-select>`:
 * a trigger button plus a panel constrained to its own parent width,
 * so the whole popup can never spill past the viewport (which native
 * `<input type="datetime-local">` popups do in Chrome DevTools' mobile
 * emulation).
 *
 * Value shape mirrors the native `datetime-local` input:
 * `"YYYY-MM-DDTHH:mm"` (no seconds, no timezone). Empty string clears.
 */
@Component({
  selector: 'crm-mobile-datetime',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => MobileDateTimeComponent),
      multi: true,
    },
  ],
  templateUrl: './mobile-datetime.component.html',
})
export class MobileDateTimeComponent implements ControlValueAccessor {
  /** `[value]` binding for non-form-driven callers. */
  readonly value = input<string>('');
  readonly placeholder = input<string>('Pick a date & time');
  /** Optional `min` boundary — matches `value` shape. Days before this
   *  get disabled in the calendar grid. */
  readonly min = input<string>('');
  /** Optional `max` boundary — same shape. */
  readonly max = input<string>('');
  /** `'datetime'` (default) — calendar + time inputs, emits
   *  `YYYY-MM-DDTHH:mm`. `'date'` — calendar only, emits `YYYY-MM-DD`. */
  readonly mode = input<'datetime' | 'date'>('datetime');
  readonly valueChange = output<string>();

  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly open = signal(false);
  readonly disabled = signal(false);

  /** `position: fixed` coords for the calendar panel. Recomputed each
   *  time the panel opens (or the viewport resizes/scrolls) so the
   *  panel escapes any parent `overflow-hidden` / clipped modal card
   *  and always fits inside the viewport. `null` → not open yet. */
  protected readonly panelStyle = signal<{ top: string; left: string; width: string } | null>(null);

  /** Single source of truth — written by either `[value]` (via effect)
   *  or `writeValue()` (from Angular Forms). */
  private readonly writtenValue = signal<string | null>(null);
  protected readonly currentValue = computed<string>(() => {
    const w = this.writtenValue();
    return w !== null ? w : this.value();
  });

  private onChangeFn: (v: string) => void = () => undefined;
  private onTouchedFn: () => void = () => undefined;

  /** The month currently shown in the calendar grid (independent of
   *  the selected value so a user can browse without picking). */
  protected readonly viewMonth = signal(new Date());

  constructor() {
    // Mirror the `[value]` input into writtenValue so both binding paths
    // agree. `writtenValue` is read via `untracked` so this effect fires
    // only when `[value]` actually changes — otherwise the user's
    // `pickDay()` (which sets writtenValue) would re-trigger the effect
    // and get clobbered back to the input's default (empty), breaking
    // `formControlName` callers where `[value]` is never bound.
    effect(() => {
      const v = this.value();
      if (v !== untracked(() => this.writtenValue())) this.writtenValue.set(v);
    });

    // When the current value maps to a real date, park the calendar
    // on that month so opening the picker again shows the right page.
    effect(() => {
      const parsed = this.parseValue(this.currentValue());
      if (parsed) this.viewMonth.set(new Date(parsed.getFullYear(), parsed.getMonth(), 1));
    });

    // Refine the panel position once the actual panel is in the DOM
    // (its measured height is more reliable than the estimate).
    effect(() => {
      if (this.open() && this.panelRef()) {
        // Run in a microtask so layout settles before we read offsetHeight.
        queueMicrotask(() => this.refinePosition());
      }
    });

    // Portal the panel + backdrop to `document.body` once they render.
    // `position: fixed` normally anchors to the viewport — but if ANY
    // ancestor uses `transform`, `filter`, `perspective`, or
    // `will-change`, that ancestor becomes the containing block and
    // the panel positions relative to the ancestor instead. Tailwind's
    // `-translate-x-1/2 -translate-y-1/2` centering pattern (used by
    // the task modal and other callers) triggers this. Portalling to
    // body sidesteps the trap for every caller.
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
    // still portaled (parent view teardown, route change), yank the
    // orphaned nodes from body so we don't leak DOM.
    this.destroyRef.onDestroy(() => {
      this.panelRef()?.nativeElement?.remove();
      this.backdropRef()?.nativeElement?.remove();
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

  /** Human label for the trigger — "05 Aug 2026, 14:30" or placeholder. */
  protected readonly triggerLabel = computed<string>(() => {
    const parsed = this.parseValue(this.currentValue());
    if (!parsed) return this.placeholder();
    return this.formatDisplay(parsed);
  });

  /** Header label — "August 2026". */
  protected readonly monthLabel = computed<string>(() => {
    const d = this.viewMonth();
    return d.toLocaleString('en', { month: 'long', year: 'numeric' });
  });

  /** 42-cell grid for the calendar (6 weeks × 7 days). Each cell is a
   *  Date at midnight local time. Leading/trailing cells belong to the
   *  previous/next month and render dimmed. */
  protected readonly gridDays = computed<Date[]>(() => {
    const anchor = this.viewMonth();
    const firstOfMonth = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    // Grid starts on the Monday of the week containing the 1st.
    // JS getDay(): Sun=0..Sat=6. Convert to Mon=0..Sun=6.
    const dow = (firstOfMonth.getDay() + 6) % 7;
    const start = new Date(firstOfMonth);
    start.setDate(1 - dow);
    const out: Date[] = [];
    for (let i = 0; i < 42; i += 1) {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      out.push(d);
    }
    return out;
  });

  protected readonly weekdayLabels = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'];

  /** Currently-selected time components (hours 0-23, minutes 0-59).
   *  Falls back to `12:00` if no value is set — matching the OS pickers. */
  protected readonly selectedHour = computed<number>(() => {
    const p = this.parseValue(this.currentValue());
    return p ? p.getHours() : 12;
  });

  protected readonly selectedMinute = computed<number>(() => {
    const p = this.parseValue(this.currentValue());
    return p ? p.getMinutes() : 0;
  });

  /** Selected day (midnight-local Date) — for highlighting the grid. */
  protected readonly selectedDay = computed<Date | null>(() => {
    const p = this.parseValue(this.currentValue());
    if (!p) return null;
    return new Date(p.getFullYear(), p.getMonth(), p.getDate());
  });

  protected readonly today = new Date();

  /** Panel element ref, populated once `@if (open())` renders it. */
  protected readonly panelRef = viewChild<ElementRef<HTMLElement>>('panel');
  /** Backdrop element ref — needs to move to `document.body` alongside
   *  the panel so both escape any transformed ancestor container. */
  protected readonly backdropRef = viewChild<ElementRef<HTMLElement>>('backdrop');

  /** Original parent of the panel/backdrop before we portal them to
   *  `document.body`. We put them back before the `@if` teardown so
   *  Angular's renderer can remove the nodes from a parent it knows
   *  about. */
  private originalParent: HTMLElement | null = null;

  protected toggle(): void {
    if (this.disabled()) return;
    const nextOpen = !this.open();
    if (nextOpen) {
      // Seed a sensible position from the trigger's rect so first
      // paint isn't at (0,0). Actual size measurement runs after the
      // panel renders (see `afterNextRender` in the constructor).
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
    this.onTouchedFn();
  }

  /** Compute a fixed-position for the panel that:
   *  - sits below the trigger when there's room, above otherwise
   *  - never extends outside the viewport horizontally
   *  - never taller than 90vh (internal scroll takes over past that).
   *  Panel is `position: fixed` so it escapes any parent `overflow-hidden`
   *  (modal cards, table cells, sidebars, etc.) and can never be clipped.
   *  `estimatedHeight` is used on first paint (before the panel is in
   *  the DOM). Once the panel renders, `refinePosition()` re-measures
   *  and re-anchors with the true height. */
  private positionPanel(estimatedHeight = 380): void {
    const trigger = this.host.nativeElement.querySelector(
      'button[type="button"]',
    ) as HTMLElement | null;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const PANEL_W = Math.min(320, vw - 16);
    const h = Math.min(estimatedHeight, vh - 16);
    const spaceBelow = vh - rect.bottom;
    const spaceAbove = rect.top;
    let top: number;
    if (spaceBelow >= h + 8 || spaceBelow >= spaceAbove) {
      top = rect.bottom + 4;
    } else {
      top = rect.top - h - 4;
    }
    // Clamp so the panel is fully on-screen vertically.
    top = Math.max(8, Math.min(top, vh - h - 8));
    // Align to trigger's left edge, but clamp so it stays on-screen.
    const left = Math.max(8, Math.min(rect.left, vw - PANEL_W - 8));
    this.panelStyle.set({
      top: `${Math.round(top)}px`,
      left: `${Math.round(left)}px`,
      width: `${Math.round(PANEL_W)}px`,
    });
  }

  /** Re-anchor with the true measured height once the panel is in the
   *  DOM. Prevents "estimate was wrong → panel clips off screen"
   *  glitches, especially in date-only mode where the panel is shorter
   *  than the datetime mode. */
  private refinePosition(): void {
    const el = this.panelRef()?.nativeElement;
    if (!el) return;
    this.positionPanel(el.offsetHeight);
  }

  /** Recompute the panel position on window resize / scroll while it's
   *  open — keeps it glued to the trigger through page-scroll or
   *  orientation change. */
  @HostListener('window:resize')
  onResize(): void {
    if (this.open()) this.positionPanel();
  }
  @HostListener('window:scroll')
  onWindowScroll(): void {
    if (this.open()) this.positionPanel();
  }

  protected prevMonth(): void {
    const d = this.viewMonth();
    this.viewMonth.set(new Date(d.getFullYear(), d.getMonth() - 1, 1));
  }

  protected nextMonth(): void {
    const d = this.viewMonth();
    this.viewMonth.set(new Date(d.getFullYear(), d.getMonth() + 1, 1));
  }

  protected pickDay(day: Date): void {
    // Keep the existing hour/minute; if there's no value yet, start
    // at the current wall-clock time. Date-only mode zeros the time
    // to keep the emitted string tidy.
    const parsed = this.parseValue(this.currentValue());
    const dateMode = this.mode() === 'date';
    const h = dateMode ? 0 : parsed ? parsed.getHours() : this.today.getHours();
    const m = dateMode ? 0 : parsed ? parsed.getMinutes() : this.today.getMinutes();
    const next = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m);
    this.emit(next);
    // In date-only mode there's nothing else to configure — close so
    // the user doesn't have to reach for the backdrop.
    if (dateMode) this.close();
  }

  protected pickToday(): void {
    const n = new Date();
    // Preserve the currently-selected time if there is one.
    const parsed = this.parseValue(this.currentValue());
    if (parsed) {
      n.setHours(parsed.getHours(), parsed.getMinutes(), 0, 0);
    } else {
      n.setSeconds(0, 0);
    }
    this.emit(n);
    this.viewMonth.set(new Date(n.getFullYear(), n.getMonth(), 1));
  }

  protected clear(): void {
    this.writtenValue.set('');
    this.valueChange.emit('');
    this.onChangeFn('');
    this.close();
  }

  /** Time input handlers — clamps & preserves the selected day. */
  protected onHourInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    const h = Math.max(0, Math.min(23, Number(raw) || 0));
    this.applyTime(h, this.selectedMinute());
  }

  protected onMinuteInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    const m = Math.max(0, Math.min(59, Number(raw) || 0));
    this.applyTime(this.selectedHour(), m);
  }

  private applyTime(h: number, m: number): void {
    const parsed = this.parseValue(this.currentValue()) ?? new Date();
    const next = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate(), h, m);
    this.emit(next);
  }

  private emit(d: Date): void {
    const iso = this.formatIso(d);
    this.writtenValue.set(iso);
    this.valueChange.emit(iso);
    this.onChangeFn(iso);
  }

  /** Convenience predicates the template uses to style cells. */
  protected isSameDay(a: Date, b: Date | null): boolean {
    if (!b) return false;
    return (
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate()
    );
  }

  protected isCurrentMonth(day: Date): boolean {
    return day.getMonth() === this.viewMonth().getMonth();
  }

  /** Disable dates outside the min/max range (day-precision). */
  protected isDisabled(day: Date): boolean {
    const min = this.parseValue(this.min());
    const max = this.parseValue(this.max());
    const dayMs = day.getTime();
    if (min) {
      const minDay = new Date(min.getFullYear(), min.getMonth(), min.getDate()).getTime();
      if (dayMs < minDay) return true;
    }
    if (max) {
      const maxDay = new Date(max.getFullYear(), max.getMonth(), max.getDate()).getTime();
      if (dayMs > maxDay) return true;
    }
    return false;
  }

  /** Parse a `YYYY-MM-DDTHH:mm` (or with seconds) string into a Date.
   *  Anything unparseable returns `null` so the trigger falls back to
   *  the placeholder and the calendar stays on the current month. */
  private parseValue(value: string): Date | null {
    if (!value) return null;
    // Accept `YYYY-MM-DDTHH:mm[:ss]` — split on `T` so we sidestep the
    // native `Date(string)` timezone-guessing (which flips UTC vs local
    // silently across browsers).
    const [datePart, timePart = '00:00'] = value.split('T');
    const [y, mo, d] = datePart.split('-').map((n) => Number(n));
    const [h, mi] = timePart.split(':').map((n) => Number(n));
    if (!y || !mo || !d) return null;
    const dt = new Date(y, mo - 1, d, h || 0, mi || 0);
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  /** ISO shape without timezone. `date` mode emits `YYYY-MM-DD`
   *  (matches `<input type="date">`); `datetime` mode emits
   *  `YYYY-MM-DDTHH:mm` (matches `datetime-local`). */
  private formatIso(d: Date): string {
    const p = (n: number): string => String(n).padStart(2, '0');
    const datePart = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    if (this.mode() === 'date') return datePart;
    return `${datePart}T${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  /** Trigger label — `05 Aug 2026, 14:30` or `05 Aug 2026`. */
  private formatDisplay(d: Date): string {
    const p = (n: number): string => String(n).padStart(2, '0');
    const month = d.toLocaleString('en', { month: 'short' });
    const datePart = `${p(d.getDate())} ${month} ${d.getFullYear()}`;
    if (this.mode() === 'date') return datePart;
    return `${datePart}, ${p(d.getHours())}:${p(d.getMinutes())}`;
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
    // Panel + backdrop are portaled to `document.body`, so
    // `host.contains(panel)` is false. Check panel/backdrop explicitly
    // so clicks on days / month nav / time inputs don't close.
    const panel = this.panelRef()?.nativeElement;
    const backdrop = this.backdropRef()?.nativeElement;
    if (el.contains(target)) return;
    if (panel && panel.contains(target)) return;
    if (backdrop && backdrop.contains(target)) return;
    this.close();
  }
}
