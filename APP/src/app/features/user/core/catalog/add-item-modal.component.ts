import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { nullableTrim } from '@core/services/form.util';

import {
  CatalogApiService,
  CatalogItem,
} from './catalog-api.service';

/**
 * Add-or-edit modal for a catalog item.
 *
 * Pass `item` to open in edit mode; null/undefined opens an empty
 * create form. `sku` is locked in edit mode (matches backend's
 * "SKU is a stable identifier" rule).
 *
 * The 409 from a duplicate SKU is surfaced inline ("SKU already
 * exists in this org") instead of bubbling as a toast.
 */
@Component({
  selector: 'app-add-item-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './add-item-modal.component.html',
})
export class AddItemModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CatalogApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() set item(value: CatalogItem | null) {
    this._item.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Output() readonly saved = new EventEmitter<CatalogItem>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _item = signal<CatalogItem | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  readonly isEdit = computed(() => this._item() !== null);

  protected readonly form = this.fb.group({
    sku: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(64)],
    }),
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    category: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.maxLength(64)],
    }),
    price: this.fb.control<number | null>(null, {
      validators: [Validators.required, Validators.min(0)],
    }),
    is_active: this.fb.control<boolean>(true, { nonNullable: true }),
  });

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const raw = this.form.getRawValue();
    if (raw.price === null) {
      this.form.controls.price.markAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);

    const existing = this._item();
    if (existing !== null) {
      this.api
        .update(existing.id, {
          name: raw.name,
          category: nullableTrim(raw.category),
          price: raw.price,
          is_active: raw.is_active,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (item) => {
            this.submitting.set(false);
            this.saved.emit(item);
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.submitError.set(this.errorFor(err) ?? 'Could not save item.');
          },
        });
    } else {
      this.api
        .create({
          sku: raw.sku.trim(),
          name: raw.name,
          category: nullableTrim(raw.category),
          price: raw.price,
          is_active: raw.is_active,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (item) => {
            this.submitting.set(false);
            this.saved.emit(item);
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            if (err.status === 409) {
              this.submitError.set(
                'SKU already exists in this org. Pick a different SKU.',
              );
            } else {
              this.submitError.set(this.errorFor(err) ?? 'Could not create item.');
            }
          },
        });
    }
  }

  private resetForm(item: CatalogItem): void {
    this.form.reset({
      sku: item.sku,
      name: item.name,
      category: item.category ?? '',
      price: Number(item.price),
      is_active: item.is_active,
    });
    this.form.controls.sku.disable();
  }


  private errorFor(err: HttpErrorResponse): string | null {
    const body = err?.error;
    if (typeof body === 'string') return body;
    if (body && typeof body === 'object') {
      const candidate =
        (body as { message?: string; detail?: unknown }).message
        ?? (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
