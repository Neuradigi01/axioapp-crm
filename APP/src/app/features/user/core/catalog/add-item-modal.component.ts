import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { nullableTrim } from '@core/services/form.util';

import { StandardFieldsApiService } from '../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import { CatalogApiService, CatalogItem } from './catalog-api.service';
import { deriveApiOrigin } from '@core/services/url.util';

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
  private readonly stdApi = inject(StandardFieldsApiService);
  private readonly stdSignals = inject(StandardFieldsSignalsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly stdFields = signal<Record<string, StandardFieldRendered>>({});

  protected stdField(key: string): StandardFieldRendered | undefined {
    return this.stdFields()[key];
  }

  protected isHidden(key: string): boolean {
    return this.stdField(key)?.is_hidden === true;
  }

  constructor() {
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
    this.destroyRef.onDestroy(() => this.revokePreview());
  }

  private refreshStdFields(): void {
    this.stdApi.render('catalog_item').subscribe({
      next: (resp) => {
        const map: Record<string, StandardFieldRendered> = {};
        for (const f of resp.items) map[f.field_key] = f;
        this.stdFields.set(map);
        this.applyStandardValidators(map);
      },
      error: () => {
        /* fallbacks keep the form usable */
      },
    });
  }

  /** `sku` + `name` + `price` are backend-required (locked).
   *  `category` accepts `required`. `price` additionally accepts `min`/`max`. */
  private applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    this.form.controls.sku.setValidators([Validators.required, Validators.maxLength(64)]);
    this.form.controls.sku.updateValueAndValidity({ emitEvent: false });

    this.form.controls.name.setValidators([Validators.required, Validators.maxLength(255)]);
    this.form.controls.name.updateValueAndValidity({ emitEvent: false });

    const categoryV: ValidatorFn[] = [Validators.maxLength(64)];
    if (map['category']?.is_required) categoryV.push(Validators.required);
    this.form.controls.category.setValidators(categoryV);
    this.form.controls.category.updateValueAndValidity({ emitEvent: false });

    const priceRow = map['price'];
    const priceV: ValidatorFn[] = [Validators.required];
    if (priceRow?.min_value != null) {
      priceV.push(Validators.min(priceRow.min_value));
    } else {
      priceV.push(Validators.min(0));
    }
    if (priceRow?.max_value != null) priceV.push(Validators.max(priceRow.max_value));
    this.form.controls.price.setValidators(priceV);
    this.form.controls.price.updateValueAndValidity({ emitEvent: false });
  }

  @Input() set item(value: CatalogItem | null) {
    this._item.set(value);
    if (value !== null) this.resetForm(value);
  }

  @Output() readonly saved = new EventEmitter<CatalogItem>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly _item = signal<CatalogItem | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // --- Image upload state ---
  // Server is the source of truth on size + MIME; these client-side
  // checks just block the obvious before we even hit the network.
  private static readonly ALLOWED_IMAGE_MIME = new Set(['image/jpeg', 'image/png', 'image/webp']);
  private static readonly MAX_IMAGE_BYTES = 5 * 1024 * 1024;

  protected readonly selectedFile = signal<File | null>(null);
  /** Local Object URL for a freshly picked file. Revoked on replace/clear. */
  protected readonly previewUrl = signal<string | null>(null);
  protected readonly imageError = signal<string | null>(null);

  private readonly apiOrigin = deriveApiOrigin();

  /** What the preview shows: freshly picked file > existing image_url > nothing.
   *  Existing URLs from the backend are server-relative (`/files/...`)
   *  and must be re-anchored to the API origin during dev (Angular dev
   *  server runs on a different port). */
  protected readonly displayImage = computed<string | null>(() => {
    const preview = this.previewUrl();
    if (preview) return preview;
    const stored = this._item()?.image_url;
    return stored ? `${this.apiOrigin}${stored}` : null;
  });

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

  protected onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = '';
    if (!file) return;
    this.acceptFile(file);
  }

  protected onFileDropped(event: DragEvent): void {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (!file) return;
    this.acceptFile(file);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  protected clearImage(): void {
    this.revokePreview();
    this.selectedFile.set(null);
    this.imageError.set(null);
  }

  private acceptFile(file: File): void {
    if (!AddItemModalComponent.ALLOWED_IMAGE_MIME.has(file.type)) {
      this.imageError.set('Pick a JPEG, PNG, or WebP image.');
      return;
    }
    if (file.size > AddItemModalComponent.MAX_IMAGE_BYTES) {
      this.imageError.set('Image exceeds the 5 MB cap.');
      return;
    }
    this.revokePreview();
    this.selectedFile.set(file);
    this.previewUrl.set(URL.createObjectURL(file));
    this.imageError.set(null);
  }

  private revokePreview(): void {
    const url = this.previewUrl();
    if (url) URL.revokeObjectURL(url);
    this.previewUrl.set(null);
  }

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
          next: (item) => this.maybeUploadImage(item),
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
          next: (item) => this.maybeUploadImage(item),
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            if (err.status === 409) {
              this.submitError.set('SKU already exists in this org. Pick a different SKU.');
            } else {
              this.submitError.set(this.errorFor(err) ?? 'Could not create item.');
            }
          },
        });
    }
  }

  /** Chain the image upload after a successful create/update. The
   *  item row is already saved at this point; image-upload failure
   *  surfaces an error but keeps the (image-less) row. */
  private maybeUploadImage(item: CatalogItem): void {
    const file = this.selectedFile();
    if (!file) {
      this.submitting.set(false);
      this.revokePreview();
      this.selectedFile.set(null);
      this.saved.emit(item);
      return;
    }
    this.api
      .uploadImage(item.id, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.submitting.set(false);
          this.revokePreview();
          this.selectedFile.set(null);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(this.errorFor(err) ?? 'Saved, but the image upload failed.');
        },
      });
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
        (body as { message?: string; detail?: unknown }).message ??
        (body as { detail?: unknown }).detail;
      if (typeof candidate === 'string') return candidate;
    }
    return null;
  }
}
