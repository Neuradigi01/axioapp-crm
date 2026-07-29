import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { extractApiError } from '@core/services/api-error.util';

import { InventoryApiService, InventoryItem, Warehouse } from './inventory-api.service';

/**
 * Add New Product modal.
 *
 * Form maps 1-to-1 onto `POST /inventory/items/full` (atomic catalog
 * + inventory). The optional cover image is uploaded via a second
 * `POST .../{id}/cover` call only after the create succeeds — if the
 * image upload fails, the product still exists with no cover.
 *
 * `warehouses` is passed in by the parent (already loaded once for the
 * Products tab) so the modal renders instantly without a second fetch.
 */
@Component({
  selector: 'app-fp-add-product-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './add-product-modal.component.html',
})
export class AddProductModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(InventoryApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input() warehouses: Warehouse[] = [];
  @Output() readonly created = new EventEmitter<InventoryItem>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  protected readonly selectedFile = signal<File | null>(null);
  protected readonly previewUrl = signal<string | null>(null);

  protected readonly materials: ReadonlyArray<string> = [
    'Solid Wood',
    'Engineered Wood',
    'Metal',
    'Glass',
    'Upholstered',
    'Mixed',
  ];
  protected readonly categories: ReadonlyArray<string> = [
    'Sofa',
    'Bed',
    'Dining',
    'Chair',
    'Table',
    'Wardrobe',
    'Storage',
    'Lighting',
    'Outdoor',
  ];

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    sku: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(64)],
    }),
    category: this.fb.control<string | null>(null),
    material: this.fb.control<string | null>(null),
    color: this.fb.control<string | null>(null),
    finish: this.fb.control<string | null>(null),
    warehouse_id: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    price: this.fb.control<number>(0, {
      nonNullable: true,
      validators: [Validators.min(0)],
    }),
    reorder_level: this.fb.control<number>(0, {
      nonNullable: true,
      validators: [Validators.min(0)],
    }),
    description: this.fb.control<string | null>(null),
    is_best_seller: this.fb.control<boolean>(false, { nonNullable: true }),
  });

  constructor() {
    // Default to the org's default warehouse when available.
    const defaultWh = this.warehouses.find((w) => w.is_default) ?? this.warehouses[0];
    if (defaultWh) {
      this.form.patchValue({ warehouse_id: defaultWh.id });
    }
  }

  protected onFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.selectedFile.set(file);
    if (this.previewUrl()) URL.revokeObjectURL(this.previewUrl()!);
    this.previewUrl.set(file ? URL.createObjectURL(file) : null);
  }

  protected clearFile(): void {
    this.selectedFile.set(null);
    if (this.previewUrl()) URL.revokeObjectURL(this.previewUrl()!);
    this.previewUrl.set(null);
  }

  protected save(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const v = this.form.getRawValue();

    this.api
      .createItemFull({
        name: v.name,
        sku: v.sku,
        category: v.category,
        material: v.material,
        color: v.color,
        finish: v.finish,
        warehouse_id: v.warehouse_id,
        price: v.price,
        reorder_level: v.reorder_level,
        description: v.description,
        is_best_seller: v.is_best_seller,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (item) => {
          const file = this.selectedFile();
          if (!file) {
            this.submitting.set(false);
            this.created.emit(item);
            return;
          }
          // Best-effort cover upload — if it fails, the product
          // still exists; surface the error inline so the user can
          // retry from the items list.
          this.api
            .uploadCover(item.id, file)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
              next: (resp) => {
                this.submitting.set(false);
                this.created.emit({ ...item, cover_url: resp.cover_url });
              },
              error: () => {
                this.submitting.set(false);
                this.created.emit(item);
              },
            });
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not create product.');
        },
      });
  }

  protected close(): void {
    if (this.previewUrl()) URL.revokeObjectURL(this.previewUrl()!);
    this.cancel.emit();
  }
}
