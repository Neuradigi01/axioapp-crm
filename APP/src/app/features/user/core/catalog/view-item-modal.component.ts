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
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { MatSnackBar } from '@angular/material/snack-bar';

import { extractApiError } from '@core/services/api-error.util';

import { InrPipe } from '../shared/pipes/inr.pipe';
import {
  CatalogApiService,
  CatalogItem,
  CatalogStatus,
  buildCatalogImageHref,
} from './catalog-api.service';
import { deriveApiOrigin } from '@core/services/url.util';

/**
 * Read-only modal for a catalog item — opens on card click. Shows
 * everything the operator might want at a glance (image, SKU, price,
 * status, description, cost price, tags, gallery, custom fields,
 * audit timestamps) without the edit form fields. "Edit" hands off
 * to the add/edit modal; "Copy public URL" appears only when the
 * item is ``published`` and mints a Fernet-tokened share link.
 */
@Component({
  selector: 'app-view-item-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, InrPipe, LucideAngularModule],
  templateUrl: './view-item-modal.component.html',
})
export class ViewItemModalComponent {
  private readonly _item = signal<CatalogItem | null>(null);
  private readonly apiOrigin = deriveApiOrigin();
  private readonly api = inject(CatalogApiService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly destroyRef = inject(DestroyRef);

  @Input() set item(value: CatalogItem | null) {
    this._item.set(value);
  }

  @Output() readonly close = new EventEmitter<void>();
  @Output() readonly edit = new EventEmitter<CatalogItem>();

  protected readonly current = computed<CatalogItem | null>(() => this._item());
  protected readonly sharing = signal(false);
  protected readonly clipboardFallbackUrl = signal<string | null>(null);

  protected readonly imageHref = computed<string | null>(() => {
    const item = this._item();
    if (!item?.image_url) return null;
    return buildCatalogImageHref(this.apiOrigin, item.image_url, item);
  });

  /** C5 — Gallery URLs anchored to the API origin. */
  protected readonly galleryHrefs = computed<string[]>(() => {
    const item = this._item();
    if (!item) return [];
    return item.image_urls.map((u) => buildCatalogImageHref(this.apiOrigin, u, item));
  });

  protected readonly customEntries = computed<Array<[string, unknown]>>(() => {
    const data = this._item()?.custom_data ?? {};
    return Object.entries(data);
  });

  protected statusPillClass(): string {
    const s: CatalogStatus | undefined = this._item()?.status;
    switch (s) {
      case 'published':
        return 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20';
      case 'unpublished':
        return 'bg-amber-500/10 text-amber-400 ring-amber-500/20';
      case 'archived':
        return 'bg-surface-2 text-muted ring-zinc-500/20';
      case 'draft':
      default:
        return 'bg-surface-2 text-muted ring-zinc-500/20';
    }
  }

  protected onEdit(): void {
    const item = this._item();
    if (item) this.edit.emit(item);
  }

  protected onCopyPublicUrl(): void {
    const item = this._item();
    if (!item || item.status !== 'published' || this.sharing()) return;
    this.sharing.set(true);
    this.api
      .generatePublicUrl(item.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: async (resp) => {
          this.sharing.set(false);
          const url = `${window.location.origin}/product/${resp.token}`;
          try {
            await navigator.clipboard.writeText(url);
            this.snackBar.open('Public URL copied to clipboard.', 'Dismiss', { duration: 2500 });
          } catch {
            this.clipboardFallbackUrl.set(url);
          }
        },
        error: (err: HttpErrorResponse) => {
          this.sharing.set(false);
          this.snackBar.open(extractApiError(err) ?? 'Could not generate public URL', 'Dismiss', {
            duration: 4000,
          });
        },
      });
  }

  protected dismissClipboardFallback(): void {
    this.clipboardFallbackUrl.set(null);
  }
}
