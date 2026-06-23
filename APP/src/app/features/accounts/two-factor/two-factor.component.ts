import { Component, ChangeDetectionStrategy, signal, inject, OnInit, OnDestroy, ElementRef, viewChildren } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { MatSnackBar } from '@angular/material/snack-bar';
import { AuthApiService } from '@app/services/auth-api.service';
import { AuthService } from '@core/services/auth.service';
import { getRoute } from '@core/services/routes-helper.service';
import { UserType, TwoFactorMethod } from '@app/schemas/common';
import { TFA_METHOD_LABELS, OTP_EXPIRY_SECONDS, RESEND_COOLDOWN_SECONDS, ROLE_ADMIN, SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_2FA_CODE_INVALID, MSG_2FA_CODE_RESENT, MSG_2FA_METHOD_SWITCHED, MSG_2FA_METHOD_SWITCH_FAILED, MSG_2FA_CODE_RESEND_FAILED } from '@core/constants/messages.constants';
import { createCountdownTimer } from '@core/services/countdown.service';
import { DeviceInfoService } from '@core/services/device-info.service';

@Component({
  selector: 'app-two-factor',
  templateUrl: './two-factor.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, LucideAngularModule],
})
export class TwoFactorComponent implements OnInit, OnDestroy {
  private readonly authApi = inject(AuthApiService);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly deviceInfo = inject(DeviceInfoService);

  readonly digitInputs = viewChildren<ElementRef<HTMLInputElement>>('digitInput');

  readonly digits = signal<string[]>(['', '', '', '', '', '']);
  readonly method = signal<TwoFactorMethod>('authenticator');
  readonly availableMethods = signal<TwoFactorMethod[]>([]);
  readonly isLoading = signal(false);
  readonly errorMessage = signal('');
  readonly showMethodOptions = signal(false);
  readonly loginUrl = signal(getRoute('login').url);

  private readonly expiryCountdown = createCountdownTimer();
  private readonly resendCountdown = createCountdownTimer();
  readonly expirySeconds = this.expiryCountdown.remaining;
  readonly resendCooldown = this.resendCountdown.remaining;

  private identifier = '';
  private password = '';
  private userType: UserType = 'User';
  private rememberMe = false;

  get methodLabel(): string {
    return TFA_METHOD_LABELS[this.method()] ?? this.method();
  }

  get alternativeMethods(): TwoFactorMethod[] {
    return this.availableMethods().filter((m) => m !== this.method());
  }

  get formattedExpiry(): string {
    const s = this.expirySeconds();
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  }

  get isExpired(): boolean {
    return this.expirySeconds() <= 0;
  }

  get isOtpMethod(): boolean {
    return this.method() === 'email' || this.method() === 'sms';
  }

  ngOnInit(): void {
    const state = history.state;
    if (!state?.identifier || !state?.password) {
      this.router.navigate([this.loginUrl()]);
      return;
    }

    this.identifier = state.identifier;
    this.password = state.password;
    this.userType = state.userType ?? 'User';
    this.rememberMe = state.rememberMe ?? false;
    this.method.set(state.method ?? 'authenticator');
    this.availableMethods.set(state.availableMethods ?? []);
    this.loginUrl.set(this.userType === ROLE_ADMIN ? getRoute('admin_login').url : getRoute('login').url);

    this.startExpiryTimer();
    if (this.isOtpMethod) {
      this.startResendCooldown();
    }
  }

  ngOnDestroy(): void {
    this.expiryCountdown.destroy();
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
    this.isLoading.set(true);
    this.errorMessage.set('');

    try {
      const response = await this.authApi.tryAnotherWay({
        identifier: this.identifier,
        password: this.password,
        user_type: this.userType,
        method,
      });

      if (response.success && response.data) {
        this.method.set(response.data.method as TwoFactorMethod);
        if (response.data.available_methods) {
          this.availableMethods.set(response.data.available_methods as TwoFactorMethod[]);
        }
        this.resetDigits();
        this.showMethodOptions.set(false);
        this.restartExpiryTimer();
        if (this.isOtpMethod) {
          this.startResendCooldown();
        }
        this.snackBar.open(response.message || MSG_2FA_METHOD_SWITCHED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(response.message || MSG_2FA_METHOD_SWITCH_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  async resendCode(): Promise<void> {
    if (this.resendCooldown() > 0 || this.isLoading()) return;

    this.isLoading.set(true);
    this.errorMessage.set('');

    try {
      const response = await this.authApi.tryAnotherWay({
        identifier: this.identifier,
        password: this.password,
        user_type: this.userType,
        method: this.method(),
      });

      if (response.success) {
        this.resetDigits();
        this.restartExpiryTimer();
        this.startResendCooldown();
        this.snackBar.open(MSG_2FA_CODE_RESENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(response.message || MSG_2FA_CODE_RESEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isLoading.set(false);
    }
  }

  private async submitCode(code: string): Promise<void> {
    if (this.isLoading() || this.isExpired) return;

    this.isLoading.set(true);
    this.errorMessage.set('');

    try {
      const loginFn = this.userType === ROLE_ADMIN ? this.authApi.adminLogin.bind(this.authApi) : this.authApi.login.bind(this.authApi);
      const response = await loginFn({
        identifier: this.identifier,
        password: this.password,
        two_factor_code: code,
        two_factor_method: this.method(),
        device_info: this.deviceInfo.collect(),
      });

      if (response.success && response.data?.token) {
        this.auth.setToken(response.data.token, this.rememberMe);
        const target = response.data.role === ROLE_ADMIN
          ? getRoute('admin_dashboard').url
          : getRoute('user_dashboard').url;
        this.router.navigate([target]);
        return;
      }

      this.errorMessage.set(response.message || MSG_2FA_CODE_INVALID);
      this.resetDigits();
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

  private startExpiryTimer(): void {
    this.expiryCountdown.start(OTP_EXPIRY_SECONDS);
  }

  private restartExpiryTimer(): void {
    this.startExpiryTimer();
  }

  private startResendCooldown(): void {
    this.resendCountdown.start(RESEND_COOLDOWN_SECONDS);
  }
}
