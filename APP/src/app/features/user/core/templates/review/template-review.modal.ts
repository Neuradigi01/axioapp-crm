import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import {
  TemplateRead,
  TemplatesApiService,
} from '../templates-api.service';

/**
 * Review modal — wraps the Step-4 workflow endpoints.
 *
 * Three reviewer actions:
 *   • Approve         → POST /api/v1/templates/{id}/approve
 *   • Request changes → POST /api/v1/templates/{id}/request-changes
 *   • Reject          → POST /api/v1/templates/{id}/reject
 *
 * Approve accepts an optional note; Reject + Request changes
 * REQUIRE a non-empty note (the backend rejects empty notes 422).
 * The parent editor only opens this modal when the template is in
 * ``in_review`` AND the user has ``templates.review`` — visibility is
 * gated upstream so the modal can stay simple.
 */
type ReviewAction = 'approve' | 'request_changes' | 'reject';


@Component({
  selector: 'app-template-review-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './template-review.modal.html',
})
export class TemplateReviewModalComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly template = input.required<TemplateRead>();

  readonly closed = output<void>();
  /** Emits the refreshed template after a successful transition so the
   *  parent editor can update its `template` signal without re-fetching. */
  readonly updated = output<TemplateRead>();

  protected readonly action = signal<ReviewAction>('approve');
  protected readonly note = signal<string>('');
  protected readonly submitting = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);

  protected readonly noteRequired = computed(() => this.action() !== 'approve');
  protected readonly canSubmit = computed(() => {
    if (this.submitting()) return false;
    if (this.noteRequired() && this.note().trim().length === 0) return false;
    return true;
  });

  protected setAction(a: ReviewAction): void {
    this.action.set(a);
    this.error.set(null);
  }

  protected onNoteInput(value: string): void {
    this.note.set(value);
  }

  protected submit(): void {
    if (!this.canSubmit()) return;
    this.submitting.set(true);
    this.error.set(null);

    const id = this.template().id;
    const payload = { note: this.note().trim() || null };
    const obs =
      this.action() === 'approve'
        ? this.api.approve(id, payload)
        : this.action() === 'reject'
          ? this.api.reject(id, payload)
          : this.api.requestChanges(id, payload);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (row) => {
        this.submitting.set(false);
        this.updated.emit(row);
        this.closed.emit();
      },
      error: (err: HttpErrorResponse) => {
        this.submitting.set(false);
        this.error.set(extractApiError(err) ?? 'Could not submit review.');
      },
    });
  }

  protected close(): void {
    if (this.submitting()) return;
    this.closed.emit();
  }
}
