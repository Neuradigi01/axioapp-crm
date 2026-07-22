/**
 * Verify-code sub-modal shown after the SMTP tab in the add-sender
 * modal successfully POSTs and the backend emails a 6-digit code to
 * the from-address. The operator opens their inbox on the sender
 * address, copies the code, pastes it here, and hits Verify.
 *
 * Emits `verified` on success (parent closes the whole flow +
 * refreshes the sender list), or `cancelled` on close.
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { EmailSendersApiService, SmtpSender } from './email-senders-api.service';

@Component({
  selector: 'app-verify-sender-code-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './verify-sender-code-modal.component.html',
})
export class VerifySenderCodeModalComponent {
  private readonly api = inject(EmailSendersApiService);
  private readonly destroyRef = inject(DestroyRef);

  /** ID of the pending SMTP sender row awaiting verification. */
  readonly senderId = input.required<string>();

  /** From-address shown in the "we emailed the code to …" hint. */
  readonly fromAddress = input.required<string>();

  readonly verified = output<SmtpSender>();
  readonly cancelled = output<void>();

  protected readonly code = new FormControl<string>('', {
    nonNullable: true,
    validators: [Validators.required, Validators.pattern(/^\d{6}$/)],
  });

  protected readonly submitting = signal(false);
  protected readonly resending = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly info = signal<string | null>(null);

  submit(): void {
    if (this.submitting()) return;
    this.code.markAsTouched();
    if (this.code.invalid) return;
    this.error.set(null);
    this.info.set(null);
    this.submitting.set(true);
    this.api
      .verify(this.senderId(), this.code.value)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.submitting.set(false);
          this.verified.emit(row);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(extractApiError(err) ?? 'Verification failed. Try again.');
        },
      });
  }

  resend(): void {
    if (this.resending()) return;
    this.error.set(null);
    this.info.set(null);
    this.resending.set(true);
    this.api
      .resendCode(this.senderId())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.resending.set(false);
          this.info.set(`New code sent to ${this.fromAddress()}. Check your inbox.`);
          this.code.reset('');
        },
        error: (err: HttpErrorResponse) => {
          this.resending.set(false);
          this.error.set(extractApiError(err) ?? 'Could not resend code.');
        },
      });
  }

  cancel(): void {
    if (this.submitting()) return;
    this.cancelled.emit();
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget && !this.submitting()) {
      this.cancelled.emit();
    }
  }
}
