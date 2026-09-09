import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { ToastService } from '../../../../shared/components/toast/toast.service';

import { FurnitureAuthService } from '../auth/auth.service';

import { CatalogApiService, CatalogItem, CatalogStatus } from './catalog-api.service';

type ActionKey =
  | 'edit'
  | 'publish'
  | 'unpublish'
  | 'archive'
  | 'unarchive'
  | 'delete'
  | 'copy-url'
  | 'preview';

interface ActionSpec {
  key: ActionKey;
  label: string;
  icon: string;
  destructive?: boolean;
  requiresPermission?: string;
}

/**
 * Row-level action menu for the Catalog page. Shows a status-aware
 * subset of actions and gates each on the acting user's granted
 * permissions.
 *
 * State machine (mirrors the backend):
 *   draft        → Edit · Publish · Archive · Delete
 *   published    → Edit · Copy URL · Preview · Unpublish · Archive
 *   unpublished  → Edit · Publish · Archive · Delete
 *   archived     → Edit · Unarchive
 *
 * Publish is auto-blocked with a snackbar when the product has no
 * images — the backend rejects with 422 either way, but short-
 * circuiting on the client saves the round-trip.
 */
@Component({
  selector: 'app-catalog-row-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './catalog-row-menu.component.html',
})
export class CatalogRowMenuComponent {
  readonly item = input.required<CatalogItem>();

  readonly refresh = output<void>();
  readonly optimisticStatus = output<{ id: string; status: CatalogStatus }>();
  readonly removed = output<string>();
  readonly editRequested = output<CatalogItem>();

  private readonly api = inject(CatalogApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly toast = inject(ToastService);
  private readonly hostRef = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly open = signal(false);
  protected readonly pending = signal<'delete' | 'archive' | null>(null);
  protected readonly clipboardFallbackUrl = signal<string | null>(null);

  protected readonly canWrite = computed(() => this.auth.hasPermission('catalog.write'));
  protected readonly canPublish = computed(() => this.auth.hasPermission('catalog.publish'));
  protected readonly canArchive = computed(() => this.auth.hasPermission('catalog.archive'));

  protected readonly hasImages = computed(() => {
    const it = this.item();
    return !!it.image_url || (it.image_urls?.length ?? 0) > 0;
  });

  /** Ordered actions for the current status, filtered by permission. */
  protected readonly actions = computed<ActionSpec[]>(() => {
    const status: CatalogStatus = this.item().status;
    const specs: ActionSpec[] = [
      { key: 'edit', label: 'Edit', icon: 'pencil', requiresPermission: 'catalog.write' },
    ];
    switch (status) {
      case 'draft':
        specs.push(
          {
            key: 'publish',
            label: 'Publish',
            icon: 'send',
            requiresPermission: 'catalog.publish',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'catalog.archive',
          },
          {
            key: 'delete',
            label: 'Delete',
            icon: 'trash-2',
            destructive: true,
            requiresPermission: 'catalog.write',
          },
        );
        break;
      case 'published':
        specs.push(
          { key: 'copy-url', label: 'Copy public URL', icon: 'link' },
          { key: 'preview', label: 'Preview public', icon: 'external-link' },
          {
            key: 'unpublish',
            label: 'Unpublish',
            icon: 'eye-off',
            requiresPermission: 'catalog.publish',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'catalog.archive',
          },
        );
        break;
      case 'unpublished':
        specs.push(
          {
            key: 'publish',
            label: 'Publish',
            icon: 'send',
            requiresPermission: 'catalog.publish',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'catalog.archive',
          },
          {
            key: 'delete',
            label: 'Delete',
            icon: 'trash-2',
            destructive: true,
            requiresPermission: 'catalog.write',
          },
        );
        break;
      case 'archived':
        specs.push(
          {
            key: 'unarchive',
            label: 'Unarchive',
            icon: 'rotate-ccw',
            requiresPermission: 'catalog.archive',
          },
          {
            key: 'delete',
            label: 'Delete permanently',
            icon: 'trash-2',
            destructive: true,
            requiresPermission: 'catalog.write',
          },
        );
        break;
    }
    return specs.filter(
      (s) => !s.requiresPermission || this.auth.hasPermission(s.requiresPermission),
    );
  });

  protected toggle(event: MouseEvent): void {
    event.stopPropagation();
    this.open.update((v) => !v);
  }

  protected close(): void {
    this.open.set(false);
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.open()) return;
    const target = event.target as Node | null;
    if (target && !this.hostRef.nativeElement.contains(target)) {
      this.close();
    }
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.close();
    this.pending.set(null);
    this.clipboardFallbackUrl.set(null);
  }

  protected run(action: ActionSpec, event: MouseEvent): void {
    event.stopPropagation();
    this.close();
    if (action.key === 'publish' && !this.hasImages()) {
      this.toast.warn('Add at least one image before publishing.');
      return;
    }
    if (action.key === 'delete') {
      this.pending.set('delete');
      return;
    }
    if (action.key === 'archive') {
      this.pending.set('archive');
      return;
    }
    this.execute(action.key);
  }

  protected confirmPending(): void {
    const p = this.pending();
    if (!p) return;
    this.pending.set(null);
    this.execute(p);
  }

  protected cancelPending(): void {
    this.pending.set(null);
  }

  protected pendingMessage(): { title: string; body: string; confirm: string } | null {
    const p = this.pending();
    if (p === 'delete') {
      return {
        title: 'Delete this product?',
        body: 'This is permanent — every field, image, and log for the product is removed.',
        confirm: 'Delete',
      };
    }
    if (p === 'archive') {
      return {
        title: 'Archive this product?',
        body: 'The product is hidden from every dashboard and public link. You can unarchive it later.',
        confirm: 'Archive',
      };
    }
    return null;
  }

  private execute(key: ActionKey): void {
    const it = this.item();
    switch (key) {
      case 'edit':
        this.editRequested.emit(it);
        return;
      case 'publish':
        this.emitOptimistic('published');
        this.api
          .publish(it.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Product published.'),
            error: (err: HttpErrorResponse) => this.revertOnError(err, 'Publish failed', it.status),
          });
        return;
      case 'unpublish':
        this.emitOptimistic('unpublished');
        this.api
          .unpublish(it.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Product unpublished.'),
            error: (err: HttpErrorResponse) =>
              this.revertOnError(err, 'Unpublish failed', it.status),
          });
        return;
      case 'archive':
        this.emitOptimistic('archived');
        this.api
          .archive(it.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Product archived.'),
            error: (err: HttpErrorResponse) => this.revertOnError(err, 'Archive failed', it.status),
          });
        return;
      case 'unarchive':
        this.emitOptimistic('draft');
        this.api
          .unarchive(it.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Product moved back to draft.'),
            error: (err: HttpErrorResponse) =>
              this.revertOnError(err, 'Unarchive failed', it.status),
          });
        return;
      case 'delete':
        this.api
          .delete(it.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => {
              this.removed.emit(it.id);
              this.toast.success('Product deleted.');
            },
            error: (err: HttpErrorResponse) => this.showError(err, 'Delete failed'),
          });
        return;
      case 'copy-url':
        this.copyPublicUrl();
        return;
      case 'preview':
        this.previewPublic();
        return;
    }
  }

  private emitOptimistic(status: CatalogStatus): void {
    this.optimisticStatus.emit({ id: this.item().id, status });
  }

  private done(message: string): void {
    this.toast.success(message);
    this.refresh.emit();
  }

  private revertOnError(err: HttpErrorResponse, fallback: string, prev: CatalogStatus): void {
    this.emitOptimistic(prev);
    this.showError(err, fallback);
  }

  private showError(err: HttpErrorResponse, fallback: string): void {
    this.toast.error(extractApiError(err) ?? fallback);
  }

  /** Assemble the public URL from the browser's own origin + the
   *  Fernet token the backend returned. Backend can't know the FE
   *  host (backend and frontend run on different origins in prod);
   *  minting client-side keeps the URL pointing at whatever host the
   *  operator is looking at. */
  private publicUrlFromToken(token: string): string {
    return `${window.location.origin}/product/${token}`;
  }

  private copyPublicUrl(): void {
    this.api
      .generatePublicUrl(this.item().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: async (resp) => {
          const url = this.publicUrlFromToken(resp.token);
          try {
            await navigator.clipboard.writeText(url);
            this.toast.success('Public URL copied to clipboard.');
          } catch {
            // Older browser / permission blocked — reveal a fallback
            // modal with the URL in a read-only field.
            this.clipboardFallbackUrl.set(url);
          }
        },
        error: (err: HttpErrorResponse) => this.showError(err, 'Could not generate public URL'),
      });
  }

  private previewPublic(): void {
    this.api
      .generatePublicUrl(this.item().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          const url = this.publicUrlFromToken(resp.token);
          window.open(url, '_blank', 'noopener');
        },
        error: (err: HttpErrorResponse) => this.showError(err, 'Could not open preview'),
      });
  }

  protected dismissClipboardFallback(): void {
    this.clipboardFallbackUrl.set(null);
  }
}
