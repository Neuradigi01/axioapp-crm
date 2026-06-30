import {
  Component,
  ChangeDetectionStrategy,
  inject,
  signal,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSnackBar } from '@angular/material/snack-bar';
import { FormCardComponent } from '@shared/components/form-card/form-card.component';
import { TwoFactorApiService } from '@app/services/two-factor-api.service';
import {
  TFA_METHOD_LABELS,
  TFA_METHOD_ICONS,
  SNACKBAR_DURATION,
  SNACKBAR_ACTION,
} from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC,
  MSG_2FA_STATUS_FAILED,
  MSG_2FA_ENABLED,
  MSG_2FA_DISABLED,
  MSG_2FA_METHOD_CHANGED,
  MSG_2FA_SETUP_FAILED,
  MSG_2FA_OTP_SENT,
  MSG_2FA_OTP_RESENT,
  MSG_2FA_OTP_SEND_FAILED,
  MSG_2FA_VERIFY_FAILED,
  MSG_2FA_DISABLE_FAILED,
  MSG_2FA_METHOD_CHANGE_FAILED,
} from '@core/constants/messages.constants';
import { createCountdownTimer } from '@core/services/countdown.service';
import { TfaView } from '@app/schemas/user';

@Component({
  selector: 'app-tfa-settings',
  templateUrl: './tfa-settings.component.html',
  styleUrl: './tfa-settings.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    FormCardComponent,
  ],
})
export class TfaSettingsComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly tfaApi = inject(TwoFactorApiService);
  private readonly snackBar = inject(MatSnackBar);

  readonly currentView = signal<TfaView>('loading');
  readonly currentMethod = signal<string | null>(null);
  readonly maskedEmail = signal('');
  readonly maskedMobile = signal('');
  readonly qrCode = signal('');
  readonly secretKey = signal('');
  readonly emailEnabled = signal(false);
  readonly smsEnabled = signal(false);
  readonly selectedMethod = signal('');
  readonly isLoading = signal(false);

  private readonly resendCountdown = createCountdownTimer();
  readonly resendTimer = this.resendCountdown.remaining;

  readonly verifyForm: FormGroup = this.fb.group({
    code: ['', [Validators.required, Validators.minLength(6), Validators.maxLength(6)]],
  });

  getMethodLabel(method: string): string {
    return TFA_METHOD_LABELS[method] || method;
  }

  getMethodIcon(method: string): string {
    return TFA_METHOD_ICONS[method] || 'security';
  }

  async ngOnInit(): Promise<void> {
    await this.loadStatus();
  }

  private async loadStatus(): Promise<void> {
    this.currentView.set('loading');
    try {
      const response = await this.tfaApi.getStatus();
      if (response.success && response.data) {
        const data = response.data;
        this.maskedEmail.set(data.masked_email || '');
        this.maskedMobile.set(data.masked_mobile || '');
        this.emailEnabled.set(data.email_enabled);
        this.smsEnabled.set(data.sms_enabled);
        if (data.two_factor_enabled && data.two_factor_method) {
          this.currentMethod.set(data.two_factor_method);
          this.currentView.set('enabled');
        } else {
          this.currentMethod.set(null);
          this.currentView.set('disabled');
        }
      }
    } catch {
      this.snackBar.open(MSG_2FA_STATUS_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      this.currentView.set('disabled');
    }
  }

  async selectMethod(method: string): Promise<void> {
    this.selectedMethod.set(method);
    this.verifyForm.reset();
    this.isLoading.set(true);

    try {
      if (method === 'authenticator') {
        const response = await this.tfaApi.setupAuthenticator();
        if (response.success && response.data) {
          this.qrCode.set(`data:image/png;base64,${response.data.qr_code}`);
          this.secretKey.set(response.data.secret);
          this.currentView.set('setup-authenticator');
        } else {
          this.snackBar.open(response.message || MSG_2FA_SETUP_FAILED, SNACKBAR_ACTION, {
            duration: SNACKBAR_DURATION,
          });
        }
      } else {
        const response = await this.tfaApi.sendSetupOtp(method);
        if (response.success) {
          this.currentView.set('setup-otp');
          this.startResendTimer();
          this.snackBar.open(MSG_2FA_OTP_SENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        } else {
          this.snackBar.open(response.message || MSG_2FA_OTP_SEND_FAILED, SNACKBAR_ACTION, {
            duration: SNACKBAR_DURATION,
          });
        }
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async verifyAndEnable(): Promise<void> {
    if (this.verifyForm.invalid) {
      this.verifyForm.markAllAsTouched();
      return;
    }

    this.isLoading.set(true);
    const payload = {
      code: this.verifyForm.get('code')!.value,
      method: this.selectedMethod(),
    };

    try {
      const response = await this.tfaApi.verifyAndEnable(payload);
      if (response.success) {
        this.snackBar.open(MSG_2FA_ENABLED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.clearTimers();
        await this.loadStatus();
      } else {
        this.snackBar.open(response.message || MSG_2FA_VERIFY_FAILED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async resendOtp(): Promise<void> {
    if (this.resendTimer() > 0) return;
    this.isLoading.set(true);

    try {
      const response = await this.tfaApi.sendSetupOtp(this.selectedMethod());
      if (response.success) {
        this.snackBar.open(MSG_2FA_OTP_RESENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        this.startResendTimer();
      } else {
        this.snackBar.open(response.message || MSG_2FA_OTP_SEND_FAILED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  showChangeMethod(): void {
    this.selectedMethod.set('');
    this.currentView.set('change-method');
  }

  showDisable(): void {
    this.currentView.set('disable');
  }

  async disableTfa(): Promise<void> {
    this.isLoading.set(true);

    try {
      const response = await this.tfaApi.disable();
      if (response.success) {
        this.snackBar.open(MSG_2FA_DISABLED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
        await this.loadStatus();
      } else {
        this.snackBar.open(response.message || MSG_2FA_DISABLE_FAILED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async submitChangeMethod(): Promise<void> {
    if (!this.selectedMethod()) return;

    this.isLoading.set(true);

    try {
      const response = await this.tfaApi.changeMethod(this.selectedMethod());
      if (response.success) {
        this.snackBar.open(MSG_2FA_METHOD_CHANGED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
        await this.loadStatus();
      } else {
        this.snackBar.open(response.message || MSG_2FA_METHOD_CHANGE_FAILED, SNACKBAR_ACTION, {
          duration: SNACKBAR_DURATION,
        });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  cancelSetup(): void {
    this.clearTimers();
    this.verifyForm.reset();
    this.selectedMethod.set('');
    if (this.currentMethod()) {
      this.currentView.set('enabled');
    } else {
      this.currentView.set('disabled');
    }
  }

  ngOnDestroy(): void {
    this.resendCountdown.destroy();
  }

  private startResendTimer(): void {
    this.resendCountdown.start(60);
  }

  private clearTimers(): void {
    this.resendCountdown.stop();
  }
}
