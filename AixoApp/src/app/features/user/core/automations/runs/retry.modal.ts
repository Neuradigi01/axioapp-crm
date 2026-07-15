import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  HostListener,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { AutomationsApiService, RunRead } from '../automations-api.service';

/**
 * Retry confirmation modal. Opens when the operator clicks "Retry"
 * on a failed run row. Shows the original error + a Confirm button
 * that POSTs the retry; on success, emits the updated run row so
 * the parent table patches the row optimistically.
 */
@Component({
  selector: 'app-retry-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule],
  templateUrl: './retry.modal.html',
})
export class RetryModalComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly run = input.required<RunRead>();

  readonly closed = output<void>();
  readonly retried = output<RunRead>();

  protected readonly submitting = signal<boolean>(false);
  protected readonly submitError = signal<string | null>(null);

  protected onConfirm(): void {
    if (this.submitting()) return;
    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .retry(this.run().id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (updated) => {
          this.submitting.set(false);
          this.retried.emit(updated);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Retry failed. Try again.');
        },
      });
  }

  protected onClose(): void {
    if (!this.submitting()) this.closed.emit();
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.onClose();
  }
}
