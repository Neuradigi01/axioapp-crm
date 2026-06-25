import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';

import { PreviewPaneComponent } from '../editor/preview-pane.component';
import {
  TemplateRead,
  TemplateVersionRead,
  TemplatesApiService,
} from '../templates-api.service';

/**
 * Versions drawer — right-side panel listing every saved version of
 * the template. "View" expands the chosen version inline (read-only
 * preview using the Step-7 preview pane). "Restore" is gated on
 * ``templates.write`` and PATCHes the latest row with the past
 * version's body + subject, creating a new version row server-side.
 *
 * Re-fetches on every open so an in-flight auto-save from the editor
 * (Step 7) doesn't leave the drawer's list stale.
 */
@Component({
  selector: 'app-versions-drawer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, DatePipe, LucideAngularModule, PreviewPaneComponent],
  templateUrl: './versions-drawer.component.html',
})
export class VersionsDrawerComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly destroyRef = inject(DestroyRef);

  readonly template = input.required<TemplateRead>();

  readonly closed = output<void>();
  /** Emits the refreshed template after Restore so the parent updates. */
  readonly updated = output<TemplateRead>();

  protected readonly versions = signal<TemplateVersionRead[]>([]);
  protected readonly loading = signal<boolean>(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly viewing = signal<TemplateVersionRead | null>(null);
  protected readonly restoring = signal<number | null>(null);
  protected readonly restoreError = signal<string | null>(null);

  protected readonly canRestore = this.auth.hasPermission('templates.write');

  constructor() {
    // Re-fetch on every open / template change.
    effect(() => {
      const t = this.template();
      void t;
      this.fetchVersions();
    });
  }

  private fetchVersions(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .versions(this.template().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.versions.set(rows);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.versions.set([]);
          this.loading.set(false);
          this.loadError.set(
            extractApiError(err) ?? 'Could not load versions.',
          );
        },
      });
  }

  protected viewVersion(v: TemplateVersionRead): void {
    this.viewing.set(v);
  }

  protected closeView(): void {
    this.viewing.set(null);
  }

  protected restore(v: TemplateVersionRead): void {
    if (!this.canRestore) return;
    if (this.restoring() !== null) return;
    this.restoring.set(v.version);
    this.restoreError.set(null);
    this.api
      .update(this.template().id, {
        body_text: v.body_text,
        subject: v.subject,
        change_note: `Restored from v${v.version}`,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.restoring.set(null);
          this.updated.emit(row);
          this.fetchVersions();
          this.viewing.set(null);
        },
        error: (err: HttpErrorResponse) => {
          this.restoring.set(null);
          this.restoreError.set(
            extractApiError(err) ?? `Could not restore v${v.version}.`,
          );
        },
      });
  }

  protected close(): void {
    this.closed.emit();
  }

  protected trackByVersion = (_: number, v: TemplateVersionRead) => v.version;
}
