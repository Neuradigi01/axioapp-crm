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
import { ConfirmDialogService } from '../shared/confirm-dialog/confirm-dialog.service';
import { DynamicFormComponent } from '../shared/dynamic-form/dynamic-form.component';
import { FieldDef, FormValue } from '../shared/dynamic-form/types';
import { FormToastHelper } from '../shared/forms/form-toast.helper';
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
  private readonly confirmDialog = inject(ConfirmDialogService);
  private readonly formToast = inject(FormToastHelper);

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
      this.clearStagedGallery();
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

  /** `name` + `price` are backend-required (locked). `sku` is
   *  backend-required, but the frontend auto-generates one from
   *  ``name`` when the field is left blank (see ``autoGenerateSku``)
   *  so the input is treated as OPTIONAL on the form level — most
   *  operators shouldn't need to think about product codes.
   *  ``category`` accepts `required`. `price` additionally accepts
   *  `min`/`max`. */
  private applyStandardValidators(map: Record<string, StandardFieldRendered>): void {
    // SKU: format-only. Required-ness is handled by the auto-gen
    // fallback in the submit path, not by the form validator.
    this.form.controls.sku.setValidators([Validators.maxLength(64)]);
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
  /** Gallery add/remove is available in BOTH create and edit modes.
   *  Create mode stages files locally via ``stagedGallery`` (previews
   *  from `URL.createObjectURL`, chained upload after item creation).
   *  Edit mode goes straight to the server via the `/images` endpoints. */
  readonly canAddGallery = computed(() => true);
  /** Server-locked gallery cap. Total per product = 1 primary + 4
   *  gallery = 5 images. Kept in sync manually with
   *  ``_MAX_GALLERY`` on the backend service. */
  readonly MAX_GALLERY = 4;
  readonly hasSavedCover = computed(() => !!this._item()?.image_url);

  /** Locally-picked gallery files staged during CREATE (before the
   *  item row exists). Each entry keeps its own ObjectURL for the
   *  preview; ``removeStagedGalleryFile`` revokes it on remove and
   *  ``resetForCreate`` revokes any leftovers. */
  protected readonly stagedGallery = signal<{ file: File; previewUrl: string }[]>([]);

  /** Unified view for the gallery strip. Edit mode reads persisted
   *  URLs off the item; create mode reads local ObjectURL previews.
   *  Returned entries carry an ``isStaged`` flag so the template can
   *  route the X button to the right handler. */
  readonly galleryEntries = computed<{ url: string; isStaged: boolean; index: number }[]>(() => {
    if (this.isEdit()) {
      return (this._item()?.image_urls ?? []).map((u, i) => ({
        url: this.galleryHref(u),
        isStaged: false,
        index: i,
      }));
    }
    return this.stagedGallery().map((s, i) => ({
      url: s.previewUrl,
      isStaged: true,
      index: i,
    }));
  });

  /** Total per-product image count that counts against MAX_GALLERY.
   *  Draws from persisted OR staged depending on mode. */
  readonly galleryCount = computed(() =>
    this.isEdit() ? (this._item()?.image_urls?.length ?? 0) : this.stagedGallery().length,
  );

  /** Hard cap on total images per product = 1 cover + MAX_GALLERY. */
  readonly MAX_TOTAL_IMAGES = 5;

  /** Unified grid feed — cover first (with a ★ badge), gallery next.
   *  Each entry carries its origin (staged local file vs. persisted
   *  server URL) and its role (cover vs. gallery + index) so the
   *  template can route delete + set-as-cover to the right handler
   *  without a second lookup. */
  readonly unifiedImages = computed<
    { url: string; isCover: boolean; isStaged: boolean; index: number | null }[]
  >(() => {
    const rows: { url: string; isCover: boolean; isStaged: boolean; index: number | null }[] = [];
    const coverPreview = this.previewUrl();
    const item = this._item();
    if (coverPreview) {
      // Freshly picked file — an ObjectURL. Treated as staged so
      // delete goes through `clearImage()`, not the server.
      rows.push({ url: coverPreview, isCover: true, isStaged: true, index: null });
    } else if (item?.image_url) {
      rows.push({
        url: buildCatalogImageHref(this.apiOrigin, item.image_url, item),
        isCover: true,
        isStaged: false,
        index: null,
      });
    }
    for (const g of this.galleryEntries()) {
      rows.push({ url: g.url, isCover: false, isStaged: g.isStaged, index: g.index });
    }
    return rows;
  });

  /** Whether the "+ add image" tile should render — hidden once the
   *  grid hits the total cap. */
  readonly canAddMoreImages = computed(() => this.unifiedImages().length < this.MAX_TOTAL_IMAGES);

  protected readonly form = this.fb.group({
    sku: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.maxLength(64)],
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

  /** Delete the persisted primary cover on the server. Distinct from
   *  ``clearImage()`` which only drops the freshly-picked file that
   *  hasn't been uploaded yet. Only available in edit mode (need
   *  an existing item id) and when a saved cover actually exists. */
  protected async removeSavedCover(): Promise<void> {
    const item = this._item();
    if (!item?.image_url) return;
    const ok = await this.confirmDialog.ask({
      title: 'Remove primary cover image?',
      body: "The image is deleted from storage — this can't be undone. You can upload a new one anytime.",
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.imageError.set(null);
    this.api
      .removeImage(item.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this._item.set(updated);
          this.revokePreview();
          this.selectedFile.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.imageError.set(this.errorFor(err) ?? 'Could not remove cover image.');
        },
      });
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

  /** Unified add path — first image slots into the cover, subsequent
   *  ones append to the gallery. Same "+" tile handles both cases so
   *  the operator doesn't have to think about primary vs. gallery on
   *  the initial upload. Once a cover exists, "Set as cover" on any
   *  gallery thumbnail promotes it (see ``promoteToCover``). */
  protected onUnifiedFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    input.value = '';
    if (!file) return;
    this.addUnifiedImage(file);
  }

  protected onUnifiedFileDropped(event: DragEvent): void {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0] ?? null;
    if (!file) return;
    this.addUnifiedImage(file);
  }

  private addUnifiedImage(file: File): void {
    // Total-cap guard runs before anything else so a "+ tile" click
    // that races the cap check gets a clean error, not a 400.
    if (this.unifiedImages().length >= this.MAX_TOTAL_IMAGES) {
      this.galleryError.set(`Up to ${this.MAX_TOTAL_IMAGES} images per product.`);
      return;
    }
    const item = this._item();
    const hasCover = item ? !!item.image_url : !!this.selectedFile();
    if (!hasCover) {
      // No cover yet — file becomes the cover (create: staged
      // ObjectURL, edit: hits /image straight away below).
      this.acceptFile(file);
      if (item) {
        // Edit mode — user just picked their first cover on an
        // existing item. Upload it right away so the grid reflects
        // the saved state and refreshes with the server response.
        this.uploadCoverFile(item.id, file);
      }
      return;
    }
    this.uploadGalleryImage(file);
  }

  private uploadCoverFile(itemId: string, file: File): void {
    this.galleryBusy.set(true);
    this.imageError.set(null);
    this.api
      .uploadImage(itemId, file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.galleryBusy.set(false);
          this._item.set(updated);
          this.revokePreview();
          this.selectedFile.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.galleryBusy.set(false);
          this.imageError.set(this.errorFor(err) ?? 'Could not upload cover image.');
        },
      });
  }

  /** Promote a gallery entry into the primary-cover slot. Create mode
   *  swaps local state (the previously-picked cover file drops back
   *  into the gallery position the promoted entry vacated). Edit mode
   *  hits the /images/promote endpoint which does the same swap
   *  server-side. */
  protected promoteToCover(index: number, isStaged: boolean): void {
    if (isStaged) {
      const staged = this.stagedGallery()[index];
      if (!staged) return;
      const prevFile = this.selectedFile();
      const prevPreview = this.previewUrl();
      // Reuse the promoted entry's ObjectURL as the new cover
      // preview — do NOT revoke it, we're re-parenting it, not
      // replacing.
      this.selectedFile.set(staged.file);
      this.previewUrl.set(staged.previewUrl);
      this.stagedGallery.update((rows) => {
        const next = [...rows];
        if (prevFile && prevPreview) {
          next[index] = { file: prevFile, previewUrl: prevPreview };
        } else {
          next.splice(index, 1);
        }
        return next;
      });
      this.imageError.set(null);
      this.galleryError.set(null);
      return;
    }
    const item = this._item();
    if (!item) return;
    this.galleryBusy.set(true);
    this.galleryError.set(null);
    this.api
      .promoteGalleryImage(item.id, index)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.galleryBusy.set(false);
          this._item.set(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.galleryBusy.set(false);
          this.galleryError.set(this.errorFor(err) ?? 'Could not set as cover.');
        },
      });
  }

  /** Delete a thumbnail — cover or gallery entry, staged or persisted.
   *  Bridges the four existing removal paths behind one entry point so
   *  the unified grid template only has to bind one click handler. */
  protected async deleteUnifiedImage(row: {
    isCover: boolean;
    isStaged: boolean;
    index: number | null;
  }): Promise<void> {
    if (row.isCover) {
      if (row.isStaged) {
        this.clearImage();
      } else {
        await this.removeSavedCover();
      }
      return;
    }
    if (row.index === null) return;
    await this.removeGalleryEntry(row.index, row.isStaged);
  }

  private uploadGalleryImage(file: File): void {
    if (!AddItemModalComponent.ALLOWED_IMAGE_MIME.has(file.type)) {
      this.galleryError.set('Pick a JPEG, PNG, or WebP image.');
      return;
    }
    if (file.size > AddItemModalComponent.MAX_IMAGE_BYTES) {
      this.galleryError.set('Image exceeds the 5 MB cap.');
      return;
    }
    if (this.galleryCount() >= this.MAX_GALLERY) {
      this.galleryError.set(`Up to ${this.MAX_GALLERY} additional images per product.`);
      return;
    }
    this.galleryError.set(null);

    const item = this._item();
    if (!item) {
      // Create mode — stage locally, upload on save.
      const previewUrl = URL.createObjectURL(file);
      this.stagedGallery.update((s) => [...s, { file, previewUrl }]);
      return;
    }
    // Edit mode — hit the server immediately.
    this.galleryBusy.set(true);
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

  protected async removeGalleryEntry(index: number, isStaged: boolean): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'Remove this image?',
      body: isStaged
        ? 'The image drops out of the upload queue — nothing has been saved yet.'
        : 'The image is deleted from storage. You can upload another one anytime.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    if (isStaged) {
      this.stagedGallery.update((rows) => {
        const target = rows[index];
        if (target) URL.revokeObjectURL(target.previewUrl);
        return rows.filter((_, i) => i !== index);
      });
      this.galleryError.set(null);
      return;
    }
    const item = this._item();
    if (!item) return;
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

  /** Revoke every staged ObjectURL on modal reset / component destroy
   *  so we don't leak blobs. */
  private clearStagedGallery(): void {
    for (const s of this.stagedGallery()) URL.revokeObjectURL(s.previewUrl);
    this.stagedGallery.set([]);
  }

  // --- Submit -----------------------------------------------------------

  protected onSubmit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      this.formToast.requiredFieldsMissing();
      return;
    }
    if (!this.customValid()) {
      this.submitError.set('Please fix the highlighted custom fields.');
      this.formToast.requiredFieldsMissing();
      return;
    }
    const raw = this.form.getRawValue();
    if (raw.price === null) {
      this.form.controls.price.markAsTouched();
      this.formToast.requiredFieldsMissing();
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
      const skuValue = raw.sku.trim() || this.autoGenerateSku(raw.name);
      this.api
        .create({
          sku: skuValue,
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
    const coverFile = this.selectedFile();
    if (!coverFile) {
      // No primary cover to upload. Still may have staged gallery
      // files (create path) — chain those directly.
      if (wasCreate) {
        this.chainStagedGalleryUploads(item, wasCreate);
        return;
      }
      this.finishSave(item);
      return;
    }
    this.api
      .uploadImage(item.id, coverFile)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          if (wasCreate) {
            this.chainStagedGalleryUploads(updated, wasCreate);
          } else {
            this.finishSave(updated);
          }
        },
        error: (err: HttpErrorResponse) => this.handleImageUploadError(err, item, wasCreate),
      });
  }

  /** Sequential upload of every staged gallery file (create path
   *  only). One at a time keeps the display-order predictable and
   *  the memory profile flat. A failure on any single file rolls
   *  back the whole create + shows the error banner. */
  private chainStagedGalleryUploads(item: CatalogItem, wasCreate: boolean): void {
    const staged = this.stagedGallery();
    if (staged.length === 0) {
      this.finishSave(item);
      return;
    }
    const [next, ...rest] = staged;
    this.api
      .addGalleryImage(item.id, next.file)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          URL.revokeObjectURL(next.previewUrl);
          this.stagedGallery.set(rest);
          this.chainStagedGalleryUploads(updated, wasCreate);
        },
        error: (err: HttpErrorResponse) => this.handleImageUploadError(err, item, wasCreate),
      });
  }

  /** Common tail — clears preview + emits saved. */
  private finishSave(item: CatalogItem): void {
    this.submitting.set(false);
    this.revokePreview();
    this.selectedFile.set(null);
    this.clearStagedGallery();
    this.saved.emit(item);
  }

  /** Image-upload failure handler shared by cover + gallery paths.
   *  On CREATE: rolls back the product row so the user isn't left
   *  with a half-saved product + orphan images. On EDIT: keeps the
   *  row (the operator's other edits are already persisted) and
   *  surfaces the error banner. */
  private handleImageUploadError(
    err: HttpErrorResponse,
    item: CatalogItem,
    wasCreate: boolean,
  ): void {
    if (wasCreate) {
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
      return;
    }
    this.submitting.set(false);
    this.submitError.set(this.errorFor(err) ?? 'Saved, but the image upload failed.');
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
    this.clearStagedGallery();
  }

  /** Generate a sensible product code from the product name when the
   *  operator leaves the SKU field blank. Shape:
   *  ``<UP-TO-24-CHARS-OF-NAME>-<4-hex-chars>``, e.g.
   *  ``COMFY-SOFA-A3F0``. Uniqueness within the org is guaranteed by
   *  the backend's ``(org_id, sku)`` unique constraint; the random
   *  suffix keeps client-side collisions rare. */
  private autoGenerateSku(name: string): string {
    const base = name
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 24);
    const suffix = Math.floor(Math.random() * 0xffff)
      .toString(16)
      .toUpperCase()
      .padStart(4, '0');
    return base ? `${base}-${suffix}` : `PROD-${suffix}`;
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
