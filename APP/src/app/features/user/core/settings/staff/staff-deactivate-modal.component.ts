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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { environment } from '../../../../../../environments/environment';
import { extractApiError } from '@core/services/api-error.util';

import {
  OpenRecordsCounts,
  StaffApiService,
} from './staff-api.service';

/** Compact user row passed in from the parent — only the fields the
 * modal needs to render and drive the transfer-target dropdown. */
export interface DeactivateTargetUser {
  id: string;
  full_name: string;
  email: string;
  is_active: boolean;
}

/**
 * Two-step offboarding modal.
 *
 *   1. On open → fetch the per-entity open-record counts for the
 *      target user (`StaffApiService.getOpenRecordsCounts`).
 *   2a. If `total === 0`, the modal collapses to a single confirm:
 *      "User has no open records — deactivate?" → calls the existing
 *      `PATCH /users/{id}/status` directly.
 *   2b. If `total > 0`, render the transfer-target picker (active
 *      members of the org, minus the target). The "Skip transfer"
 *      affordance is intentionally disabled with a tooltip — the
 *      backend rejects deactivation with 409 anyway.
 *   3. On confirm: `transferRecords(...)` → `PATCH /users/{id}/status`,
 *      sequentially. A failure in either leaves the modal open with an
 *      inline error so the operator can retry without losing context.
 */
@Component({
  selector: 'app-staff-deactivate-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, LucideAngularModule],
  templateUrl: './staff-deactivate-modal.component.html',
})
export class StaffDeactivateModalComponent {
  private readonly api = inject(StaffApiService);
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly base = environment.apiBaseUrl;

  protected readonly _user = signal<DeactivateTargetUser | null>(null);
  protected readonly _usersInOrg = signal<DeactivateTargetUser[]>([]);

  protected readonly counts = signal<OpenRecordsCounts | null>(null);
  protected readonly loadingCounts = signal(false);
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly stage = signal<'transfer' | 'deactivating'>('transfer');

  @Input() set user(value: DeactivateTargetUser | null) {
    this._user.set(value);
    if (value) this.loadCounts(value.id);
  }

  @Input() set usersInOrg(value: DeactivateTargetUser[]) {
    this._usersInOrg.set(value);
  }

  @Output() readonly cancel = new EventEmitter<void>();
  /** Emitted once both transfer AND deactivate succeed. The parent
   * uses this to reload the staff list. */
  @Output() readonly completed = new EventEmitter<void>();

  protected readonly transferTargetControl = new FormControl<string>('', {
    nonNullable: true,
  });
  protected readonly reasonControl = new FormControl<string>('', {
    nonNullable: true,
  });

  /** Active members minus the deactivation target. */
  protected readonly transferCandidates = computed(() => {
    const targetId = this._user()?.id;
    return this._usersInOrg().filter(
      (u) => u.is_active && u.id !== targetId,
    );
  });

  protected readonly hasOpenRecords = computed(() => {
    const c = this.counts();
    return c !== null && c.total > 0;
  });

  protected readonly canConfirm = computed(() => {
    if (this.submitting() || this.loadingCounts()) return false;
    const c = this.counts();
    if (c === null) return false;
    // Zero open records → confirm always allowed.
    if (c.total === 0) return true;
    // Otherwise: transfer target required.
    return this.transferTargetControl.value !== '';
  });

  private loadCounts(userId: string): void {
    this.counts.set(null);
    this.loadingCounts.set(true);
    this.error.set(null);
    this.api
      .getOpenRecordsCounts(userId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (counts) => {
          this.counts.set(counts);
          this.loadingCounts.set(false);
        },
        error: (err: HttpErrorResponse) => {
          this.loadingCounts.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not load open-record counts.',
          );
        },
      });
  }

  protected onConfirm(): void {
    if (!this.canConfirm()) return;
    const user = this._user();
    const counts = this.counts();
    if (!user || !counts) return;

    this.submitting.set(true);
    this.error.set(null);

    const reasonRaw = this.reasonControl.value.trim();
    const reason = reasonRaw.length > 0 ? reasonRaw : null;

    if (counts.total > 0) {
      const toUserId = this.transferTargetControl.value;
      if (!toUserId) return;
      this.api
        .transferRecords(user.id, { to_user_id: toUserId, reason })
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: () => {
            this.stage.set('deactivating');
            this.runDeactivate(user.id);
          },
          error: (err: HttpErrorResponse) => {
            this.submitting.set(false);
            this.error.set(
              extractApiError(err) ?? 'Could not transfer records.',
            );
          },
        });
    } else {
      this.runDeactivate(user.id);
    }
  }

  private runDeactivate(userId: string): void {
    this.http
      .patch(`${this.base}/users/${userId}/status`, { is_active: false })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.completed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(
            extractApiError(err) ?? 'Could not deactivate the user.',
          );
        },
      });
  }
}
