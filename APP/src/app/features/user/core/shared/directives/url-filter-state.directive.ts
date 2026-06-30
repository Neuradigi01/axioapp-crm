import { DestroyRef, Directive, Injector, effect, inject, input } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';

/**
 * One entry binds a piece of page state ↔ a query-param key.
 *
 * `read()` returns the current value as a string for the URL.
 * `write(s)` accepts the URL value and applies it to the underlying
 * source (a `WritableSignal.set(...)`, a `FormControl.setValue(...)`,
 * etc.). `defaultValue` (optional) lets the directive omit the param
 * from the URL when the value matches the default — keeps shared
 * links short.
 */
export interface UrlFilterEntry {
  read: () => string;
  write: (value: string) => void;
  queryKey: string;
  defaultValue?: string;
}

export type UrlFilterStateConfig = Record<string, UrlFilterEntry>;

/**
 * Round-trips a page's filter / sort / page state through the URL's
 * query params. Used on the contacts list (and rolled out to leads,
 * walk-ins, appointments, tasks) so:
 *
 *   - Refresh keeps every filter the user picked.
 *   - The browser back / forward buttons work like a sales rep
 *     expects (Cmd+[ moves between two saved filter views).
 *   - Pasting a URL into a teammate's chat re-opens the same view.
 *
 *   <div [appUrlFilterState]="urlState">…</div>
 *
 * The directive:
 *   1. On init, reads every query param and `write()`s into the page.
 *   2. Wraps each entry's `read()` in an `effect()` and pushes the
 *      changes back into the URL with `replaceUrl: true` so the
 *      back-button doesn't get spammed with intermediate states.
 *
 * `replaceUrl` keeps history clean for *typing* (debounced text
 * input) but kills the "back button moves between filters" property.
 * Tradeoff is intentional — text-typing is the dominant pattern and
 * a back-history full of half-typed search strings is worse than
 * losing the navigation property.
 */
@Directive({
  selector: '[appUrlFilterState]',
  standalone: true,
})
export class UrlFilterStateDirective {
  appUrlFilterState = input.required<UrlFilterStateConfig>();

  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  /** Tracks whether the initial query-param hydration has finished.
   * We must NOT push state back to the URL until after we've consumed
   * the incoming params — otherwise the first effect tick would
   * blank the URL just before we read it. */
  private hydrated = false;

  constructor() {
    // Wait one async tick so child template binds + parent ngOnInit
    // run before we touch the URL. Then hydrate from params and arm
    // the push-back effects.
    queueMicrotask(() => this.start());
  }

  private start(): void {
    // 1) Hydrate from URL on first run + on every URL change (e.g.
    //    the user clicks "back").
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const cfg = this.appUrlFilterState();
      for (const entry of Object.values(cfg)) {
        const incoming = params.get(entry.queryKey) ?? entry.defaultValue ?? '';
        if (incoming !== entry.read()) {
          entry.write(incoming);
        }
      }
      this.hydrated = true;
    });

    // 2) Push state changes back to the URL. One effect per entry —
    //    Angular tracks the signals each `read()` touches, so each
    //    effect re-runs only when its own value changes.
    const cfg = this.appUrlFilterState();
    for (const entry of Object.values(cfg)) {
      effect(
        () => {
          const value = entry.read();
          if (!this.hydrated) return;
          const current = this.route.snapshot.queryParamMap.get(entry.queryKey);
          const isDefault =
            entry.defaultValue !== undefined ? value === entry.defaultValue : value === '';
          const desired = isDefault ? null : value;
          if (current === desired) return;
          this.router.navigate([], {
            relativeTo: this.route,
            queryParams: { [entry.queryKey]: desired },
            queryParamsHandling: 'merge',
            replaceUrl: true,
          });
        },
        { injector: this.injector },
      );
    }
  }
}
