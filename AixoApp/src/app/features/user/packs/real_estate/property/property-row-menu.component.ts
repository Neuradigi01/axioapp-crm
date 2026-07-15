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
import { Router } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { MatSnackBar } from '@angular/material/snack-bar';

import { extractApiError } from '@core/services/api-error.util';

import { FurnitureAuthService } from '../../../core/auth/auth.service';

import { PropertyApiService } from './property-api.service';
import type { Property, PropertyStatus } from './property.types';

type ActionKey =
  | 'edit'
  | 'publish'
  | 'unpublish'
  | 'archive'
  | 'unarchive'
  | 'mark-sold'
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
 * Row-level action menu for the Property list. Shows a status-aware
 * subset of actions and gates each destructive one on the acting
 * user's granted permissions.
 *
 * State machine (mirrors the backend):
 *   draft        → Edit · Publish · Delete
 *   published    → Edit · Copy URL · Preview · Unpublish · Mark Sold · Archive
 *   unpublished  → Edit · Publish · Archive · Delete
 *   archived     → Edit · Unarchive
 *   sold         → Edit · Copy URL · Preview
 *
 * Publish is auto-disabled with a tooltip when the property has no
 * images — the backend rejects with 422 either way, but blocking on
 * the client short-circuits the round-trip.
 */
@Component({
  selector: 'app-property-row-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, LucideAngularModule],
  templateUrl: './property-row-menu.component.html',
})
export class PropertyRowMenuComponent {
  readonly property = input.required<Property>();

  readonly refresh = output<void>();
  readonly optimisticStatus = output<{ id: string; status: PropertyStatus }>();
  readonly removed = output<string>();

  private readonly api = inject(PropertyApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly hostRef = inject(ElementRef<HTMLElement>);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly open = signal(false);
  protected readonly pending = signal<'delete' | 'archive' | null>(null);
  protected readonly clipboardFallbackUrl = signal<string | null>(null);

  protected readonly canWrite = computed(() => this.auth.hasPermission('property.write'));
  protected readonly canPublish = computed(() => this.auth.hasPermission('property.publish'));
  protected readonly canArchive = computed(() => this.auth.hasPermission('property.archive'));
  protected readonly canDelete = computed(() => this.auth.hasPermission('property.delete'));

  protected readonly hasImages = computed(
    () => (this.property().images?.length ?? 0) > 0 || !!this.property().featured_image_url,
  );

  /** Ordered actions for the current status. Filtered by permission
   * gates before render — the template just iterates. */
  protected readonly actions = computed<ActionSpec[]>(() => {
    const status: PropertyStatus = this.property().status;
    const specs: ActionSpec[] = [
      { key: 'edit', label: 'Edit', icon: 'pencil', requiresPermission: 'property.write' },
    ];
    switch (status) {
      case 'draft':
        specs.push(
          {
            key: 'publish',
            label: 'Publish',
            icon: 'send',
            requiresPermission: 'property.publish',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'property.archive',
          },
          {
            key: 'delete',
            label: 'Delete',
            icon: 'trash-2',
            destructive: true,
            requiresPermission: 'property.delete',
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
            requiresPermission: 'property.publish',
          },
          {
            key: 'mark-sold',
            label: 'Mark sold',
            icon: 'check-circle-2',
            requiresPermission: 'property.write',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'property.archive',
          },
        );
        break;
      case 'unpublished':
        specs.push(
          {
            key: 'publish',
            label: 'Publish',
            icon: 'send',
            requiresPermission: 'property.publish',
          },
          {
            key: 'archive',
            label: 'Archive',
            icon: 'archive',
            requiresPermission: 'property.archive',
          },
          {
            key: 'delete',
            label: 'Delete',
            icon: 'trash-2',
            destructive: true,
            requiresPermission: 'property.delete',
          },
        );
        break;
      case 'archived':
        specs.push({
          key: 'unarchive',
          label: 'Unarchive',
          icon: 'rotate-ccw',
          requiresPermission: 'property.archive',
        });
        break;
      case 'sold':
        specs.push(
          { key: 'copy-url', label: 'Copy public URL', icon: 'link' },
          { key: 'preview', label: 'Preview public', icon: 'external-link' },
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
      this.snackBar.open('Add at least one image to publish this property.', 'Dismiss', {
        duration: 3500,
      });
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

  /** Reveal the delete/archive modal buttons for the template. */
  protected pendingMessage(): { title: string; body: string; confirm: string } | null {
    const p = this.pending();
    if (p === 'delete') {
      return {
        title: 'Delete this property?',
        body: 'This is permanent — every field, image, and log for the listing is removed.',
        confirm: 'Delete',
      };
    }
    if (p === 'archive') {
      return {
        title: 'Archive this property?',
        body: 'The listing is hidden from every dashboard and public link. You can unarchive it later.',
        confirm: 'Archive',
      };
    }
    return null;
  }

  private execute(key: ActionKey): void {
    const p = this.property();
    switch (key) {
      case 'edit':
        // Row-click already navigates to /edit; the menu item is here
        // for keyboard users. In-app router hop keeps state intact.
        this.router.navigate(['/user/properties', p.id, 'edit']);
        return;
      case 'publish':
        this.emitOptimistic('published');
        this.api
          .publish(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Property published.'),
            error: (err: HttpErrorResponse) => this.revertOnError(err, 'Publish failed', p.status),
          });
        return;
      case 'unpublish':
        this.emitOptimistic('unpublished');
        this.api
          .unpublish(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Property unpublished.'),
            error: (err: HttpErrorResponse) =>
              this.revertOnError(err, 'Unpublish failed', p.status),
          });
        return;
      case 'archive':
        this.emitOptimistic('archived');
        this.api
          .archive(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Property archived.'),
            error: (err: HttpErrorResponse) => this.revertOnError(err, 'Archive failed', p.status),
          });
        return;
      case 'unarchive':
        this.emitOptimistic('draft');
        this.api
          .unarchive(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Property moved back to draft.'),
            error: (err: HttpErrorResponse) =>
              this.revertOnError(err, 'Unarchive failed', p.status),
          });
        return;
      case 'mark-sold':
        this.emitOptimistic('sold');
        this.api
          .markSold(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => this.done('Property marked as sold.'),
            error: (err: HttpErrorResponse) =>
              this.revertOnError(err, 'Could not mark as sold', p.status),
          });
        return;
      case 'delete':
        this.api
          .remove(p.id)
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => {
              this.removed.emit(p.id);
              this.snackBar.open('Property deleted.', 'Dismiss', { duration: 2500 });
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

  private emitOptimistic(status: PropertyStatus): void {
    this.optimisticStatus.emit({ id: this.property().id, status });
  }

  private done(message: string): void {
    this.snackBar.open(message, 'Dismiss', { duration: 2500 });
    this.refresh.emit();
  }

  private revertOnError(err: HttpErrorResponse, fallback: string, prev: PropertyStatus): void {
    this.emitOptimistic(prev);
    this.showError(err, fallback);
  }

  private showError(err: HttpErrorResponse, fallback: string): void {
    this.snackBar.open(extractApiError(err) ?? fallback, 'Dismiss', { duration: 4000 });
  }

  /** Assemble the public URL from the browser's own origin + the
   * Fernet token the backend returned. Backend can't know the
   * frontend's host (backend is on port 30007 / a different domain);
   * always mint client-side so the URL points at the app the user
   * is actually looking at. */
  private publicUrlFromToken(token: string): string {
    return `${window.location.origin}/property/${token}`;
  }

  private copyPublicUrl(): void {
    this.api
      .generatePublicUrl(this.property().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: async (resp) => {
          const url = this.publicUrlFromToken(resp.token);
          try {
            await navigator.clipboard.writeText(url);
            this.snackBar.open('Public URL copied to clipboard.', 'Dismiss', { duration: 2500 });
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
      .generatePublicUrl(this.property().id)
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
