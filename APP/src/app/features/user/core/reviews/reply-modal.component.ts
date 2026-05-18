import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Input,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { Review, ReviewsApiService } from './reviews-api.service';
import { extractApiError } from '@core/services/api-error.util';

/**
 * Modal for replying to a review. Shows the original review for
 * context (read-only), then a textarea + Send. On success the parent
 * receives the updated `Review` (status flipped to `replied`).
 */
@Component({
  selector: 'app-review-reply-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './reply-modal.component.html',
})
export class ReviewReplyModalComponent {
  private readonly api = inject(ReviewsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Input({ required: true }) review!: Review;

  @Output() readonly saved = new EventEmitter<Review>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly textControl = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.minLength(1)],
  });

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  protected submit(): void {
    if (!this.textControl.valid) {
      this.textControl.markAsTouched();
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .reply(this.review.id, this.textControl.value)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.submitting.set(false);
          this.saved.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not send reply.');
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }

  protected stars(n: number): string {
    return 'â˜…â˜…â˜…â˜…â˜…'.slice(0, n) + 'â˜†â˜†â˜†â˜†â˜†'.slice(0, 5 - n);
  }

}
