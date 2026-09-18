import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { CdkDrag, CdkDragDrop, CdkDropList, moveItemInArray } from '@angular/cdk/drag-drop';
import { HttpErrorResponse } from '@angular/common/http';
import { LucideAngularModule } from 'lucide-angular';
import { ToastService } from '../../../../../shared/components/toast/toast.service';

import { extractApiError } from '@core/services/api-error.util';

import { ConfirmDialogService } from '../../../core/shared/confirm-dialog/confirm-dialog.service';
import { assetUrl } from './asset-url.util';
import { PropertyApiService } from './property-api.service';
import {
  ALLOWED_IMAGE_MIME,
  MAX_IMAGE_BYTES,
  MAX_UPLOAD_BATCH,
  type PropertyImage,
} from './property.types';

/**
 * Property gallery — upload (drag or click), reorder (CDK drag),
 * pick featured, delete. Sits inside the create/edit form and
 * activates only after the property row exists (create flow saves
 * as draft first, then the gallery becomes usable).
 *
 * Client-side validation matches the backend: 5 MB per file,
 * JPEG/PNG/WebP only. Rejected files never leave the browser.
 */
@Component({
  selector: 'app-property-gallery',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, CdkDropList, CdkDrag, LucideAngularModule],
  templateUrl: './property-gallery.component.html',
})
export class PropertyGalleryComponent {
  readonly propertyId = input.required<string>();
  readonly initialImages = input<PropertyImage[]>([]);
  readonly readonly = input<boolean>(false);

  readonly imagesChanged = output<PropertyImage[]>();

  private readonly api = inject(PropertyApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);
  private readonly confirmDialog = inject(ConfirmDialogService);

  protected readonly images = signal<PropertyImage[]>([]);
  protected readonly uploading = signal(false);
  protected readonly dragOver = signal(false);

  protected imgSrc(img: PropertyImage): string {
    return assetUrl(img.image_url);
  }

  constructor() {
    // Hydrate from the parent's `initialImages` on first render AND
    // whenever the parent replaces the list (e.g. property re-fetched
    // after a save). `untracked` keeps the set inside the effect from
    // triggering another cycle. Previously used a one-shot
    // `queueMicrotask` — that missed later input changes and left the
    // gallery stale after an external refresh.
    effect(() => {
      const next = this.initialImages();
      untracked(() => this.images.set([...next]));
    });
  }

  protected onFilesPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files) return;
    this.upload(Array.from(input.files));
    input.value = ''; // allow re-picking the same file
  }

  protected onDrop(event: CdkDragDrop<PropertyImage[]>): void {
    if (event.previousIndex === event.currentIndex) return;
    const reordered = [...this.images()];
    moveItemInArray(reordered, event.previousIndex, event.currentIndex);
    this.images.set(reordered);
    this.persistOrder(reordered.map((i) => i.id));
  }

  protected onDragEnter(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  protected onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
  }

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
  }

  protected onFileDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    const dt = event.dataTransfer;
    if (!dt || !dt.files.length) return;
    this.upload(Array.from(dt.files));
  }

  protected setAsCover(image: PropertyImage): void {
    if (image.is_featured) return;
    this.api
      .setFeaturedImage(this.propertyId(), image.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.images.update((all) => all.map((i) => ({ ...i, is_featured: i.id === image.id })));
          this.imagesChanged.emit(this.images());
          this.toast.success('Cover image updated');
        },
        error: (err: HttpErrorResponse) => this.showError(err, 'Could not set cover image'),
      });
  }

  protected async requestDelete(image: PropertyImage): Promise<void> {
    const ok = await this.confirmDialog.ask({
      title: 'Remove this image?',
      body: 'The image is deleted from storage — this cannot be undone. You can upload another anytime.',
      confirmLabel: 'Remove',
      danger: true,
    });
    if (!ok) return;
    this.api
      .deleteImage(this.propertyId(), image.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.images.update((all) => all.filter((i) => i.id !== image.id));
          this.imagesChanged.emit(this.images());
          this.toast.success('Image removed');
        },
        error: (err: HttpErrorResponse) => this.showError(err, 'Could not delete image'),
      });
  }

  private upload(files: File[]): void {
    if (files.length === 0) return;
    if (files.length > MAX_UPLOAD_BATCH) {
      this.toast.warn(`Please upload at most ${MAX_UPLOAD_BATCH} files at a time.`);
      return;
    }

    const validated: File[] = [];
    for (const f of files) {
      if (!ALLOWED_IMAGE_MIME.has(f.type)) {
        this.toast.warn(`Skipped “${f.name}”`, {
          subtitle: 'Only JPEG, PNG, or WebP images are allowed.',
        });
        continue;
      }
      if (f.size > MAX_IMAGE_BYTES) {
        this.toast.warn(`Skipped “${f.name}”`, {
          subtitle: 'File exceeds the 5 MB cap.',
        });
        continue;
      }
      validated.push(f);
    }
    if (validated.length === 0) return;

    this.uploading.set(true);
    this.api
      .uploadImages(this.propertyId(), validated)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (inserted) => {
          this.images.update((all) => [...all, ...inserted]);
          this.imagesChanged.emit(this.images());
          this.uploading.set(false);
          this.toast.success(
            `Uploaded ${inserted.length} image${inserted.length === 1 ? '' : 's'}`,
          );
        },
        error: (err: HttpErrorResponse) => {
          this.uploading.set(false);
          this.showError(err, 'Upload failed');
        },
      });
  }

  private persistOrder(orderedIds: string[]): void {
    this.api
      .reorderImages(this.propertyId(), orderedIds)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (fresh) => {
          this.images.set(fresh);
          this.imagesChanged.emit(fresh);
        },
        error: (err: HttpErrorResponse) => this.showError(err, 'Could not save new order'),
      });
  }

  private showError(err: HttpErrorResponse, fallback: string): void {
    this.toast.error(extractApiError(err) ?? fallback);
  }
}
