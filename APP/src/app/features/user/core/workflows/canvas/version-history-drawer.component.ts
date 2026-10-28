import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  WorkflowVersionDetail,
  WorkflowVersionSummary,
  WorkflowsApiService,
} from '../workflows-api.service';

/**
 * Right-side drawer listing the workflow's version history (newest
 * first). Each row shows version number / change note / created-by
 * / created-at plus "View" + "Restore" buttons.
 *
 * Wiring is intentionally thin — the parent canvas page owns the
 * preview overlay (replaces the live graph with the historical one
 * the user clicks "View" on) + the actual rollback POST (so it can
 * refresh the canvas state on success). This component just lists
 * versions and emits intents.
 */

@Component({
  selector: 'app-version-history-drawer',
  standalone: true,
  imports: [CommonModule, DatePipe, LucideAngularModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './version-history-drawer.component.html',
})
export class VersionHistoryDrawerComponent {
  private readonly api = inject(WorkflowsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly workflowId = input.required<string>();
  /** Version currently rendered on the canvas overlay — used to
   *  show "Currently viewing" + disable the View button. */
  readonly viewingVersion = input<number | null>(null);

  readonly close = output<void>();
  readonly viewVersion = output<WorkflowVersionDetail>();
  readonly backToCurrent = output<void>();
  readonly restoreVersion = output<{ version: number; changeNote: string }>();

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly versions = signal<WorkflowVersionSummary[]>([]);
  readonly total = signal(0);
  readonly fetchingDetail = signal<number | null>(null);

  constructor() {
    effect(() => {
      const id = this.workflowId();
      if (!id) return;
      this.fetch();
    });
  }

  fetch(): void {
    this.loading.set(true);
    this.error.set(null);
    this.api
      .listVersions(this.workflowId(), { limit: 200 })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resp) => {
          this.versions.set(resp.items);
          this.total.set(resp.total);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.error.set(extractApiError(err) ?? 'Could not load version history.');
          this.loading.set(false);
        },
      });
  }

  onView(version: number): void {
    if (this.fetchingDetail() !== null) return;
    this.fetchingDetail.set(version);
    this.api
      .getVersion(this.workflowId(), version)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (detail) => {
          this.fetchingDetail.set(null);
          this.viewVersion.emit(detail);
        },
        error: (err: HttpErrorResponse) => {
          this.fetchingDetail.set(null);
          this.error.set(extractApiError(err) ?? 'Could not load version graph.');
        },
      });
  }

  onRestore(version: number): void {
    const proceed = confirm(
      `Restore version ${version}? A new version will be written that mirrors v${version}'s graph; nothing is lost.`,
    );
    if (!proceed) return;
    const note = prompt('Change note (optional)', `Rolled back to v${version}`);
    if (note === null) return;
    this.restoreVersion.emit({
      version,
      changeNote: note.trim() || `Rolled back to v${version}`,
    });
  }
}
