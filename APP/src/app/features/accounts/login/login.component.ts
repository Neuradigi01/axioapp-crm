import { Component, ChangeDetectionStrategy, effect, signal, inject, viewChild } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { CaptchaComponent } from '@shared/components/captcha/captcha.component';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { AuthApiService } from '@app/services/auth-api.service';
import { AuthService } from '@core/services/auth.service';
import { getRoute } from '@core/services/routes-helper.service';
import { UserType } from '@app/schemas/common';
import { I2faRequiredData, IEmailVerificationRequiredData, ILoginPayload } from '@app/schemas/auth';
import { ROLE_ADMIN, SNACKBAR_DURATION, SNACKBAR_ACTION } from '@core/constants/app.constants';
import { MSG_ERROR_GENERIC, MSG_LOGIN_FAILED } from '@core/constants/messages.constants';
import { DeviceInfoService } from '@core/services/device-info.service';
import { FurnitureAuthService } from '@app/features/user/core/auth/auth.service';
import { DemoPresetBusService } from '@app/features/dev-tools/demo-preset-bus.service';

// When the demo-logins pill picks a preset, its slug lands here via
// the bus effect below — sent on submit so the demo org is targeted
// explicitly. For real signups the slug stays null and the backend
// resolves the user's org from email + active membership.

@Component({
  selector: 'app-login',
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatCheckboxModule,
    ValidationMessageComponent,
    CaptchaComponent,
    PasswordToggleDirective,
  ],
})
export class LoginComponent {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApiService);
  private readonly auth = inject(AuthService);
  private readonly furnitureAuth = inject(FurnitureAuthService);
  private readonly router = inject(Router);
  private readonly snackBar = inject(MatSnackBar);
  private readonly deviceInfo = inject(DeviceInfoService);
  private readonly demoBus = inject(DemoPresetBusService);

  private readonly route = inject(ActivatedRoute);
  readonly userType: UserType = (this.route.snapshot.data['userType'] as UserType) ?? 'User';

  readonly loginForm: FormGroup = this.fb.group({
    identifier: ['', Validators.required],
    password: ['', Validators.required],
    rememberMe: [false],
  });

  readonly isLoading = signal(false);
  readonly captchaType = signal('');
  readonly captchaToken = signal('');

  readonly selectedOrgSlug = signal<string | null>(null);

  private readonly captchaRef = viewChild<CaptchaComponent>('captchaRef');

  readonly forgotPasswordUrl = getRoute('forgot_password').url;
  readonly registerUrl = getRoute('register').url;

  constructor() {
    effect(() => {
      const preset = this.demoBus.selected();
      if (!preset || this.isAdmin) return;
      this.loginForm.patchValue({
        identifier: preset.identifier,
        password: preset.password,
      });
      this.selectedOrgSlug.set(preset.orgSlug);
    });
  }

  get isAdmin(): boolean {
    return this.userType === ROLE_ADMIN;
  }

  onCaptchaTypeChange(type: string): void {
    this.captchaType.set(type);
  }

  onCaptchaTokenChange(token: string): void {
    this.captchaToken.set(token);
  }

  async onSubmit(): Promise<void> {
    if (this.loginForm.invalid) return;

    this.isLoading.set(true);
    const { identifier, password } = this.loginForm.value;

    // FurnitureCRM (layered) user login. Admin login keeps the legacy path below.
    if (!this.isAdmin) {
      try {
        await firstValueFrom(
          this.furnitureAuth.login(identifier, password, this.selectedOrgSlug()),
        );
        await this.router.navigateByUrl('/user');
      } catch (err: unknown) {
        const msg =
          (err as { error?: { detail?: string; message?: string } })?.error?.detail ??
          (err as { error?: { detail?: string; message?: string } })?.error?.message ??
          MSG_LOGIN_FAILED;
        this.snackBar.open(msg, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } finally {
        this.isLoading.set(false);
      }
      return;
    }

    try {
      const device_info = this.deviceInfo.collect();
      const payload: ILoginPayload = { identifier, password, device_info };

      if (this.captchaType()) {
        const captcha = this.captchaRef();
        if (captcha) {
          payload.captcha_token = await captcha.execute();
          if (this.captchaType() === 'image') {
            payload.captcha_answer = captcha.captchaAnswer.value || '';
          }
        }
      }

      const loginFn = this.isAdmin ? this.authApi.adminLogin.bind(this.authApi) : this.authApi.login.bind(this.authApi);
      const response = await loginFn(payload);

      if (response.success && response.data?.token) {
        this.auth.setToken(response.data.token, this.loginForm.value.rememberMe);
        const target = response.data.role === ROLE_ADMIN
          ? getRoute('admin_dashboard').url
          : getRoute('user').url;
        this.router.navigate([target]);
        return;
      }

      if (!response.success && response.data) {
        const data = response.data as unknown as I2faRequiredData;
        if (data.requires_2fa) {
          this.router.navigate([getRoute('two_factor_authentication').url], {
            state: {
              identifier,
              password,
              userType: this.userType,
              method: data.method,
              availableMethods: data.available_methods,
              rememberMe: this.loginForm.value.rememberMe,
            },
          });
          return;
        }

        const verifyData = response.data as unknown as IEmailVerificationRequiredData;
        if (verifyData.requires_email_verification) {
          this.router.navigate([getRoute('email_verification_notice').url], {
            state: { email: identifier },
          });
          return;
        }
      }

      this.snackBar.open(response.message || MSG_LOGIN_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      this.captchaRef()?.refresh();
    } catch {
      this.snackBar.open(MSG_ERROR_GENERIC, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      this.captchaRef()?.refresh();
    } finally {
      this.isLoading.set(false);
    }
  }
}
