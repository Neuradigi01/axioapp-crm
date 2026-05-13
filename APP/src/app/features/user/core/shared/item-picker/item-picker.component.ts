import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Input,
  computed,
  forwardRef,
  inject,
  signal,
} from '@angular/core';
import {
  ControlValueAccessor,
  NG_VALUE_ACCESSOR,
} from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap } from 'rxjs/operators';

import {
  CatalogApiService,
  CatalogItem,
} from '../../catalog/catalog-api.service';
import { InrPipe } from '../pipes/inr.pipe';

/**
 * Reusable item-picker for any form that needs a catalog item
 * selection — Walk-ins (Step 3.2's modal could optionally adopt
 * this), Leads, Custom Orders later.
 *
 * Inputs / two-way:
 *   - `value` (CatalogItem | null) via `ControlValueAccessor` so it
 *     plugs into `[formControl]` and `[(ngModel)]`.
 *   - `placeholder` for the search input.
 *
 * Behaviour: debounced autocomplete against `/catalog?q=...`,
 * dropdown of up to 8 results. Active-only by default — Phase 4's
 * inventory might widen this.
 */
@Component({
  selector: 'app-item-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [InrPipe],
  templateUrl: './item-picker.component.html',
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => ItemPickerComponent),
      multi: true,
    },
  ],
})
export class ItemPickerComponent implements ControlValueAccessor {
  private readonly api = inject(CatalogApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() placeholder = 'Search products by name or SKU…';

  protected readonly selected = signal<CatalogItem | null>(null);
  protected readonly query = signal('');
  protected readonly results = signal<CatalogItem[]>([]);
  protected readonly open = signal(false);
  protected readonly disabledState = signal(false);

  protected readonly hasSelection = computed(() => this.selected() !== null);

  private readonly query$ = new Subject<string>();
  private onChange: (value: CatalogItem | null) => void = () => undefined;
  private onTouched: () => void = () => undefined;

  constructor() {
    this.query$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((q) => {
          const trimmed = q.trim();
          if (trimmed.length === 0) {
            this.results.set([]);
            return [];
          }
          return this.api.list({ q: trimmed, active_only: true, size: 8 });
        }),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: (resp) => {
          if (!resp) return;
          this.results.set(resp.items);
        },
        error: () => this.results.set([]),
      });
  }

  writeValue(value: CatalogItem | null): void {
    this.selected.set(value);
  }

  registerOnChange(fn: (value: CatalogItem | null) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabledState.set(isDisabled);
  }

  protected onInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.query.set(value);
    this.open.set(true);
    this.query$.next(value);
  }

  protected pick(item: CatalogItem): void {
    this.selected.set(item);
    this.query.set('');
    this.results.set([]);
    this.open.set(false);
    this.onTouched();
    this.onChange(item);
  }

  protected clear(): void {
    this.selected.set(null);
    this.query.set('');
    this.results.set([]);
    this.open.set(true);
    this.onTouched();
    this.onChange(null);
  }
}
