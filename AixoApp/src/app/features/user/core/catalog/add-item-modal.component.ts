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
import { LucideAngularModule } from 'lucide-angular';

import { nullableTrim } from '@core/services/form.util';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { StandardFieldsApiService } from '../standard-fields/standard-fields-api.service';
import { StandardFieldsSignalsService } from '../standard-fields/standard-fields-signals.service';
import type { StandardFieldRendered } from '../standard-fields/types';
import {
  CatalogApiService,
  CatalogCategoriesApiService,
  CatalogCategory,
  CatalogItem,
  buildCatalogImageHref,
} from './catalog-api.service';
import { deriveApiOrigin } from '@core/services/url.util';

/**
 * Add-or-edit modal for a catalog item.
 *
 * Pass `item` to open in edit mode; null/undefined opens an empty
 * create form. `sku` is locked in edit mode (matches backend's
 * "SKU is a stable identifier" rule).
 *
 * Widened by the catalog review (0163):
 *   C2 — server-fed category select + "add new" free-text
 *   C3 — dynamic custom fields via <app-dynamic-form>
 *   C4 — description textarea
 *   C5 — gallery thumbnail strip with add + remove
 *   C6 — cost_price input
 *   C9 — atomic create: image upload failure rolls back the item
 *   C13 — tags chip input (comma or Enter to add, backspace to remove)
 */
@Component({
  selector: 'app-add-item-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule, DynamicFormComponent],
  templateUrl: './add-item-modal.component.html',
})
export class AddItemModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CatalogApiService);
  private readonly categoriesApi = inject(CatalogCategoriesApiService);
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

  // C2 — categories fed from the server, not derived from loaded items.
  protected readonly categories = signal<CatalogCategory[]>([]);

  // C3 — dynamic custom-field defs + form state, mirrors the pattern
  // used by contacts / leads / walk-ins.
  protected readonly customFields = signal<FieldDef[]>([]);
  protected readonly customFieldsLoading = signal(false);
  protected readonly customValue = signal<FormValue>({});
  protected readonly customValid = signal(true);

  constructor() {
    effect(() => {
      this.stdSignals.changedAt();
      this.refreshStdFields();
    });
    this.destroyRef.onDestroy(() => {
      this.revokePreview();
    });
    this.loadCategories();
    this.loadCustomFields();
  }

  private loadCategories(): void {
    this.categoriesApi
      .list(true)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => this.categories.set(rows),
        error: () => this.categories.set([]),
      });
  }

  private loadCustomFields(): void {
    this.customFieldsLoading.set(true);
    this.api
      .renderFields()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (defs) => {
          this.customFields.set(defs);
          this.customFieldsLoading.set(false);
        },
        error: () => {
          this.customFields.set([]);
          this.customFieldsLoading.set(false);
        },
      });
  }

  private refreshStdFields(): void {
    // `takeUntilDestroyed` matches every other subscription in this
    // file. Without it, closing the modal mid-render leaks the
    // subscription and can `.set()` on a destroyed component when
    // the response finally lands.
    this.stdApi
      .render('catalog_item')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
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
    else this.resetForCreate();
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

  // C5 — gallery state. Loaded from `item.image_urls`; add/remove hit
  // the /images endpoints and mutate the local signal on success.
  protected readonly galleryBusy = signal(false);
  protected readonly galleryError = signal<string | null>(null);

  // C13 — tag chip state. Simple array + input; Enter or comma adds.
  protected readonly tagInput = signal('');

  private readonly apiOrigin = deriveApiOrigin();

  /** What the preview shows: freshly picked file > existing image_url > nothing. */
  protected readonly displayImage = computed<string | null>(() => {
    const preview = this.previewUrl();
    if (preview) return preview;
    const item = this._item();
    if (!item?.image_url) return null;
    return buildCatalogImageHref(this.apiOrigin, item.image_url, item);
  });

  protected galleryHref(url: string): string {
    const item = this._item();
    return item ? buildCatalogImageHref(this.apiOrigin, url, item) : `${this.apiOrigin}${url}`;
  }

  readonly isEdit = computed(() => this._item() !== null);
  readonly canAddGallery = computed(() => this._item() !== null);
  readonly galleryUrls = computed<string[]>(() => this._item()?.image_urls ?? []);

  protected readonly form = this.fb.group({
    sku: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(64)],
    }),
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    description: this.fb.control('', { nonNullable: true }),
    category: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.maxLength(64)],
    }),
    price: this.fb.control<number | null>(null, {
      validators: [Validators.required, Validators.min(0)],
    }),
    cost_price: this.fb.control<number | null>(null, {
      validators: [Validators.min(0)],
    }),
    is_active: this.fb.control<boolean>(true, { nonNullable: true }),
    tags: this.fb.control<string[]>([], { nonNullable: true }),
  });

  // --- C3 custom-form pass-through --------------------------------------

  protected onCustomValueChange(v: FormValue): void {
    this.customValue.set(v);
  }

  protected onCustomValidityChange(valid: boolean): void {
    this.customValid.set(valid);
  }

  // --- C13 tag chips ----------------------------------------------------

  protected onTagInput(event: Event): void {
    this.tagInput.set((event.target as HTMLInputElement).value);
  }

  protected onTagKeydown(event: KeyboardEvent): void {
    const value = this.tagInput().trim();
    if ((event.key === 'Enter' || event.key === ',') && value) {
      event.preventDefault();
      this.addTag(value);
      this.tagInput.set('');
      (event.target as HTMLInputElement).value = '';
    } else if (event.key === 'Backspace' && !value) {
      // Delete the last tag on backspace-with-empty-input for the
      // Todoist-style chip UX.
      const tags = this.form.controls.tags.value;
      if (tags.length > 0) {
        this.form.controls.tags.setValue(tags.slice(0, -1));
      }
    }
  }

  protected addTag(raw: string): void {
    const trimmed = raw.trim();
    if (!trimmed) return;
    const current = this.form.controls.tags.value;
    if (current.includes(trimmed)) return;
    this.form.controls.tags.setValue([...current, trimmed]);
  }

  protected removeTag(tag: string): void {
    this.form.controls.tags.setValue(this.form.controls.tags.value.filter((t) => t !== tag));
  }

  // --- Image upload -----------------------------------------------------

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

  // --- C5 gallery -------------------------------------------------------

  protected onGalleryFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = '';
    if (!file) return;
    this.uploadGalleryImage(file);
  }

  private uploadGalleryImage(file: File): void {
    const item = this._item();
    if (!item) return;
    if (!AddItemModalComponent.ALLOWED_IMAGE_MIME.has(file.type)) {
      this.galleryError.set('Pick a JPEG, PNG, or WebP image.');
      return;
    }
    if (file.size > AddItemModalComponent.MAX_IMAGE_BYTES) {
      this.galleryError.set('Image exceeds the 5 MB cap.');
      return;
    }
    this.galleryBusy.set(true);
    this.galleryError.set(null);
    this.api
      .addGalleryImage(item.id, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.galleryBusy.set(false);
          this._item.set(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.galleryBusy.set(false);
          this.galleryError.set(this.errorFor(err) ?? 'Could not add gallery image.');
        },
      });
  }

  protected removeGalleryImage(index: number): void {
    const item = this._item();
    if (!item) return;
    if (!confirm('Remove this gallery image?')) return;
    this.galleryBusy.set(true);
    this.galleryError.set(null);
    this.api
      .removeGalleryImage(item.id, index)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.galleryBusy.set(false);
          this._item.set(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.galleryBusy.set(false);
          this.galleryError.set(this.errorFor(err) ?? 'Could not remove gallery image.');
        },
      });
  }

  // --- Submit -----------------------------------------------------------

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    if (!this.customValid()) {
      this.submitError.set('Please fix the highlighted custom fields.');
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
          description: nullableTrim(raw.description),
          category: nullableTrim(raw.category),
          price: raw.price,
          cost_price: raw.cost_price,
          is_active: raw.is_active,
          tags: raw.tags,
          custom_data: this.customValue() as Record<string, unknown>,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (item) => this.maybeUploadImage(item, false),
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
          description: nullableTrim(raw.description),
          category: nullableTrim(raw.category),
          price: raw.price,
          cost_price: raw.cost_price,
          is_active: raw.is_active,
          tags: raw.tags,
          custom_data: this.customValue() as Record<string, unknown>,
        })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (item) => this.maybeUploadImage(item, true),
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

  /** Chain the image upload after a successful create/update.
   *
   *  C9 — atomic create: on the CREATE path, if the image upload
   *  fails we DELETE the item we just created so the operator isn't
   *  left with a half-saved row + a confusing "saved but image failed"
   *  banner. Edit path keeps the previous behaviour (item stays
   *  saved; error shown) — an existing row with a failed image swap
   *  isn't ambiguous. */
  private maybeUploadImage(item: CatalogItem, wasCreate: boolean): void {
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
          if (wasCreate) {
            // Roll back — delete the item we just created so the user
            // sees one clean error instead of a half-created row.
            // If the rollback delete ALSO fails, log so the orphan
            // product isn't invisible — the operator will otherwise
            // see "product not created" while a row silently exists
            // in the DB, findable only by a page refresh.
            this.api
              .delete(item.id)
              .pipe(takeUntilDestroyed(this.destroyRef))
              .subscribe({
                error: (rollbackErr: HttpErrorResponse) => {
                  console.warn(
                    '[catalog] rollback delete failed for orphan product',
                    item.id,
                    rollbackErr.status,
                    rollbackErr.message,
                  );
                },
              });
            this.submitting.set(false);
            this.submitError.set(
              this.errorFor(err) ??
                'Image upload failed; the product was not created. Try again with a different image.',
            );
          } else {
            this.submitting.set(false);
            this.submitError.set(this.errorFor(err) ?? 'Saved, but the image upload failed.');
          }
        },
      });
  }

  private resetForm(item: CatalogItem): void {
    this.form.reset({
      sku: item.sku,
      name: item.name,
      description: item.description ?? '',
      category: item.category ?? '',
      price: Number(item.price),
      cost_price: item.cost_price !== null ? Number(item.cost_price) : null,
      is_active: item.is_active,
      tags: item.tags ?? [],
    });
    this.form.controls.sku.disable();
    this.customValue.set((item.custom_data ?? {}) as FormValue);
  }

  private resetForCreate(): void {
    this.form.reset({
      sku: '',
      name: '',
      description: '',
      category: '',
      price: null,
      cost_price: null,
      is_active: true,
      tags: [],
    });
    this.form.controls.sku.enable();
    this.customValue.set({});
    this.tagInput.set('');
    this.galleryError.set(null);
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
