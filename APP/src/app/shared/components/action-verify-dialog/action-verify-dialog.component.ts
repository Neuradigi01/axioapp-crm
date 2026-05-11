import { Component, ChangeDetectionStrategy, inject, signal, OnInit, OnDestroy, viewChildren, ElementRef } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ActionVerifyApiService } from '@app/services/action-verify-api.service';
import { IActionVerifyDialogData, TwoFactorMethod } from '@app/schemas/common';
import { TFA_METHOD_LABELS, TFA_METHOD_ICONS, RESEND_COOLDOWN_SECONDS, SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_ACTION_VERIFY_FAILED, MSG_ACTION_VERIFY_OTP_SENT, MSG_ACTION_VERIFY_OTP_SEND_FAILED } from '@core/constants/messages.constants';
import { createCountdownTimer } from '@core/services/countdown.service';

@Component({
  selector: 'app-action-verify-dialog',
  templateUrl: './action-verify-dialog.component.html',
  styleUrl: './action-verify-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MatDialogModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
  ],
})
export class ActionVerifyDialogComponent implements OnInit, OnDestroy {
  private readonly dialogRef = inject(MatDialogRef<ActionVerifyDialogComponent>);
  private readonly actionVerifyApi = inject(ActionVerifyApiService);
  private readonly snackBar = inject(MatSnackBar);
  readonly data: IActionVerifyDialogData = inject(MAT_DIALOG_DATA);

  readonly digitInputs = viewChildren<ElementRef<HTMLInputElement>>('digitInput');

  readonly digits = signal<string[]>(['', '', '', '', '', '']);
  readonly method = signal<TwoFactorMethod>('authenticator');
  readonly isLoading = signal(false);
  readonly errorMessage = signal('');
  readonly showMethodOptions = signal(false);

  private readonly resendCountdown = createCountdownTimer();
  readonly resendCooldown = this.resendCountdown.remaining;

  get methodLabel(): string {
    return TFA_METHOD_LABELS[this.method()] ?? this.method();
  }

  get methodIcon(): string {
    return TFA_METHOD_ICONS[this.method()] ?? 'security';
  }

  get isOtpMethod(): boolean {
    return this.method() === 'email' || this.method() === 'sms';
  }

  get alternativeMethods(): TwoFactorMethod[] {
    return this.data.availableMethods.filter((m) => m !== this.method());
  }

  async ngOnInit(): Promise<void> {
    this.method.set(this.data.twoFactorMethod);
    if (this.isOtpMethod) {
      await this.sendOtp();
    }
  }

  ngOnDestroy(): void {
    this.resendCountdown.destroy();
  }

  onDigitInput(index: number, event: Event): void {
    const input = event.target as HTMLInputElement;
    const value = input.value.replace(/\D/g, '');

    const updated = [...this.digits()];

    if (value.length > 1) {
      const chars = value.split('');
      for (let i = 0; i < chars.length && index + i < 6; i++) {
        updated[index + i] = chars[i];
      }
      this.digits.set(updated);

      const nextIndex = Math.min(index + chars.length, 5);
      this.focusInput(nextIndex);
    } else {
      updated[index] = value;
      this.digits.set(updated);

      if (value && index < 5) {
        this.focusInput(index + 1);
      }
    }

    const code = updated.join('');
    if (code.length === 6 && updated.every((d) => d !== '')) {
      this.submitCode(code);
    }
  }

  onDigitKeydown(index: number, event: KeyboardEvent): void {
    if (event.key === 'Backspace') {
      const updated = [...this.digits()];
      if (updated[index]) {
        updated[index] = '';
        this.digits.set(updated);
      } else if (index > 0) {
        updated[index - 1] = '';
        this.digits.set(updated);
        this.focusInput(index - 1);
      }
      event.preventDefault();
    } else if (event.key === 'ArrowLeft' && index > 0) {
      this.focusInput(index - 1);
    } else if (event.key === 'ArrowRight' && index < 5) {
      this.focusInput(index + 1);
    }
  }

  onDigitPaste(event: ClipboardEvent): void {
    event.preventDefault();
    const pasted = event.clipboardData?.getData('text')?.replace(/\D/g, '') ?? '';
    if (!pasted) return;

    const updated = [...this.digits()];
    for (let i = 0; i < Math.min(pasted.length, 6); i++) {
      updated[i] = pasted[i];
    }
    this.digits.set(updated);

    const nextIndex = Math.min(pasted.length, 5);
    this.focusInput(nextIndex);

    const code = updated.join('');
    if (code.length === 6 && updated.every((d) => d !== '')) {
      this.submitCode(code);
    }
  }

  toggleMethodOptions(): void {
    this.showMethodOptions.update((v) => !v);
  }

  async selectMethod(method: TwoFactorMethod): Promise<void> {
    this.method.set(method);
    this.resetDigits();
    this.errorMessage.set('');
    this.showMethodOptions.set(false);

    if (this.isOtpMethod) {
      await this.sendOtp();
    }
  }

  async resendCode(): Promise<void> {
    if (this.resendCooldown() > 0 || this.isLoading()) return;
    await this.sendOtp();
  }

  onCancel(): void {
    this.dialogRef.close(null);
  }

  private async sendOtp(): Promise<void> {
    this.isLoading.set(true);
    try {
      const response = await this.actionVerifyApi.sendOtp(this.method());
      if (response.success) {
        this.snackBar.open(MSG_ACTION_VERIFY_OTP_SENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.resendCountdown.start(RESEND_COOLDOWN_SECONDS);
      } else {
        this.snackBar.open(response.message || MSG_ACTION_VERIFY_OTP_SEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  private async submitCode(code: string): Promise<void> {
    if (this.isLoading()) return;

    this.isLoading.set(true);
    this.errorMessage.set('');

    try {
      const response = await this.actionVerifyApi.verify(code, this.method());
      if (response.success && response.data?.action_token) {
        this.dialogRef.close(response.data.action_token);
      } else {
        this.errorMessage.set(response.message || MSG_ACTION_VERIFY_FAILED);
        this.resetDigits();
      }
    } catch {
      this.errorMessage.set(MSG_ERROR_GENERIC);
      this.resetDigits();
    } finally {
      this.isLoading.set(false);
    }
  }

  private resetDigits(): void {
    this.digits.set(['', '', '', '', '', '']);
    this.focusInput(0);
  }

  private focusInput(index: number): void {
    setTimeout(() => {
      const inputs = this.digitInputs();
      if (inputs[index]) {
        inputs[index].nativeElement.focus();
      }
    });
  }
}
