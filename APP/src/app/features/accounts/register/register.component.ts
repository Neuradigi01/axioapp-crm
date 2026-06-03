import { Component, ChangeDetectionStrategy, signal, computed, inject, OnInit, OnDestroy, viewChild, ElementRef } from '@angular/core';
import { FormBuilder, FormGroup, Validators, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ValidationMessageComponent } from '@shared/components/validation-message/validation-message.component';
import { CaptchaComponent } from '@shared/components/captcha/captcha.component';
import { PasswordToggleDirective } from '@shared/directives/password-toggle.directive';
import { matchFieldValidator } from '@shared/validators/custom-validators';
import { AuthApiService } from '@app/services/auth-api.service';
import { FurnitureAuthService } from '@app/features/user/core/auth/auth.service';
import { firstValueFrom } from 'rxjs';
import { AppConfigApiService } from '@app/services/app-config-api.service';
import { LocationApiService } from '@app/services/location-api.service';
import { createCountdownTimer } from '@core/services/countdown.service';
import { getRoute } from '@core/services/routes-helper.service';
import { SNACKBAR_DURATION, SNACKBAR_DURATION_LONG, SNACKBAR_ACTION, RESEND_COOLDOWN_SECONDS } from '@core/constants/app.constants';
import {
  MSG_ERROR_GENERIC, MSG_REGISTRATION_SUCCESS, MSG_REGISTRATION_FAILED,
  MSG_CONTACT_OTP_SENT, MSG_CONTACT_OTP_SEND_FAILED,
} from '@core/constants/messages.constants';
import { ICountry, IState } from '@app/schemas/common';

@Component({
  selector: 'app-register',
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
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
    MatSelectModule,
    ValidationMessageComponent,
    CaptchaComponent,
    PasswordToggleDirective,
  ],
})
export class RegisterComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly authApi = inject(AuthApiService);
  private readonly furnitureAuth = inject(FurnitureAuthService);
  private readonly appConfigService = inject(AppConfigApiService);
  private readonly locationApi = inject(LocationApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly snackBar = inject(MatSnackBar);

  // ── Auth config ──────────────────────────────────────────────────────
  readonly authConfig = this.appConfigService.config;
  readonly needsEmailOtp = computed(() => {
    const cfg = this.authConfig();
    return cfg?.contact_verification_mode === 'pre' && cfg.email_enabled;
  });
  readonly needsSmsOtp = computed(() => {
    const cfg = this.authConfig();
    return cfg?.contact_verification_mode === 'pre' && cfg.sms_enabled;
  });

  // ── Inline OTP state ─────────────────────────────────────────────────
  readonly emailOtpSent = signal(false);
  readonly emailOtpToken = signal('');
  readonly isSendingEmailOtp = signal(false);
  readonly emailTimer = createCountdownTimer();

  readonly smsOtpSent = signal(false);
  readonly smsOtpToken = signal('');
  readonly isSendingSmsOtp = signal(false);
  readonly smsTimer = createCountdownTimer();

  // ── Registration form ────────────────────────────────────────────────
  //
  // After the onboarding-setup track, `/auth/register` collects user
  // identity only. The workspace name and vertical-pack choice move to
  // `/onboarding` (a dedicated step the new user lands on after this
  // form submits with `needs_onboarding=true`).
  readonly registerForm: FormGroup = this.fb.group({
    password: ['', [Validators.required, Validators.minLength(8)]],
    confirm_password: ['', [Validators.required, matchFieldValidator('password')]],
    first_name: ['', Validators.required],
    last_name: ['', Validators.required],
    email: ['', [Validators.required, Validators.email]],
    mobile_no: [''],
    country_id: [null as number | null],
    state_id: [{ value: null as number | null, disabled: true }],
    referral_id: [''],
    email_otp_code: [''],
    mobile_otp_code: [''],
  });

  readonly isLoading = signal(false);
  readonly captchaType = signal('');
  readonly captchaToken = signal('');
  readonly countries = signal<ICountry[]>([]);
  readonly states = signal<IState[]>([]);
  readonly statesLoading = signal(false);

  readonly countrySearchTerm = signal('');
  readonly stateSearchTerm = signal('');

  readonly filteredCountries = computed(() => {
    const term = this.countrySearchTerm().toLowerCase();
    if (!term) return this.countries();
    return this.countries().filter(c => c.name.toLowerCase().includes(term));
  });

  readonly filteredStates = computed(() => {
    const term = this.stateSearchTerm().toLowerCase();
    if (!term) return this.states();
    return this.states().filter(s => s.name.toLowerCase().includes(term));
  });

  private readonly countrySearchInput = viewChild<ElementRef<HTMLInputElement>>('countrySearchInput');
  private readonly stateSearchInput = viewChild<ElementRef<HTMLInputElement>>('stateSearchInput');
  private readonly captchaRef = viewChild<CaptchaComponent>('captchaRef');

  readonly loginUrl = getRoute('login').url;

  ngOnInit(): void {
    const ref = this.route.snapshot.queryParamMap.get('ref');
    if (ref) {
      this.registerForm.patchValue({ referral_id: ref });
    }
    this.loadCountries();
  }

  ngOnDestroy(): void {
    this.emailTimer.destroy();
    this.smsTimer.destroy();
  }

  // ── Inline OTP methods ───────────────────────────────────────────────

  async sendEmailOtp(): Promise<void> {
    const emailControl = this.registerForm.get('email')!;
    if (emailControl.invalid) {
      emailControl.markAsTouched();
      return;
    }

    this.isSendingEmailOtp.set(true);
    try {
      const res = await this.authApi.sendContactOtp({ type: 'email', value: emailControl.value });
      if (res.success && res.data?.otp_token) {
        this.emailOtpSent.set(true);
        this.emailOtpToken.set(res.data.otp_token);
        this.emailTimer.start(RESEND_COOLDOWN_SECONDS);
        this.snackBar.open(MSG_CONTACT_OTP_SENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(res.message || MSG_CONTACT_OTP_SEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_CONTACT_OTP_SEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSendingEmailOtp.set(false);
    }
  }

  async sendSmsOtp(): Promise<void> {
    const mobileControl = this.registerForm.get('mobile_no')!;
    if (!mobileControl.value) {
      mobileControl.markAsTouched();
      return;
    }

    this.isSendingSmsOtp.set(true);
    try {
      const res = await this.authApi.sendContactOtp({ type: 'sms', value: mobileControl.value });
      if (res.success && res.data?.otp_token) {
        this.smsOtpSent.set(true);
        this.smsOtpToken.set(res.data.otp_token);
        this.smsTimer.start(RESEND_COOLDOWN_SECONDS);
        this.snackBar.open(MSG_CONTACT_OTP_SENT, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      } else {
        this.snackBar.open(res.message || MSG_CONTACT_OTP_SEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      }
    } catch {
      this.snackBar.open(MSG_CONTACT_OTP_SEND_FAILED, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
    } finally {
      this.isSendingSmsOtp.set(false);
    }
  }

  // ── Registration form methods ────────────────────────────────────────

  onCaptchaTypeChange(type: string): void {
    this.captchaType.set(type);
  }

  onCaptchaTokenChange(token: string): void {
    this.captchaToken.set(token);
  }

  onCountrySelectToggle(opened: boolean): void {
    if (opened) {
      setTimeout(() => this.countrySearchInput()?.nativeElement.focus());
    } else {
      this.countrySearchTerm.set('');
      const el = this.countrySearchInput()?.nativeElement;
      if (el) el.value = '';
    }
  }

  onStateSelectToggle(opened: boolean): void {
    if (opened) {
      setTimeout(() => this.stateSearchInput()?.nativeElement.focus());
    } else {
      this.stateSearchTerm.set('');
      const el = this.stateSearchInput()?.nativeElement;
      if (el) el.value = '';
    }
  }

  async onCountryChange(): Promise<void> {
    const countryId = this.registerForm.get('country_id')!.value;
    this.registerForm.patchValue({ state_id: null });

    if (!countryId) {
      this.states.set([]);
      this.registerForm.get('state_id')!.disable();
      return;
    }

    this.statesLoading.set(true);
    this.registerForm.get('state_id')!.disable();
    try {
      const res = await this.locationApi.getStates(countryId);
      if (res.success) {
        this.states.set(res.data);
        if (res.data.length > 0) {
          this.registerForm.get('state_id')!.enable();
        }
      }
    } catch {
      this.states.set([]);
    } finally {
      this.statesLoading.set(false);
    }
  }

  async onSubmit(): Promise<void> {
    if (this.registerForm.invalid) {
      this.registerForm.markAllAsTouched();
      return;
    }

    this.isLoading.set(true);
    const { confirm_password, email_otp_code, mobile_otp_code, ...payload } = this.registerForm.getRawValue();

    if (this.needsEmailOtp() && this.emailOtpToken()) {
      payload.email_otp_token = this.emailOtpToken();
      payload.email_otp_code = email_otp_code;
    }

    if (this.needsSmsOtp() && this.smsOtpToken()) {
      payload.mobile_otp_token = this.smsOtpToken();
      payload.mobile_otp_code = mobile_otp_code;
    }

    if (this.captchaType()) {
      const captcha = this.captchaRef();
      if (captcha) {
        payload.captcha_token = await captcha.execute();
        if (this.captchaType() === 'image') {
          payload.captcha_answer = captcha.captchaAnswer.value || '';
        }
      }
    }

    try {
      const res = await firstValueFrom(
        this.furnitureAuth.register({
          email: payload.email,
          password: payload.password,
          first_name: payload.first_name,
          last_name: payload.last_name,
          phone: payload.mobile_no || null,
        }),
      );
      if (res.needs_onboarding) {
        // Self-signup: user lands on the onboarding picker to choose
        // an org name + CRM template. Welcome message stays on that
        // page (it has full context to brand it).
        await this.router.navigateByUrl('/onboarding');
      } else {
        // Legacy path (kept for any existing flow that ships a
        // fully-set-up org synchronously). Goes straight to dashboard.
        this.snackBar.open(
          `Welcome to ${res.organization_slug}! You're signed in as ${res.role_name}.`,
          SNACKBAR_ACTION,
          { duration: SNACKBAR_DURATION_LONG },
        );
        await this.router.navigateByUrl('/user');
      }
    } catch (err: unknown) {
      const msg =
        (err as { error?: { detail?: string; message?: string } })?.error?.detail ??
        (err as { error?: { detail?: string; message?: string } })?.error?.message ??
        MSG_REGISTRATION_FAILED;
      this.snackBar.open(msg, SNACKBAR_ACTION, { duration: SNACKBAR_DURATION });
      this.captchaRef()?.refresh();
    } finally {
      this.isLoading.set(false);
    }
  }

  // ── Private ──────────────────────────────────────────────────────────

  private async loadCountries(): Promise<void> {
    try {
      const res = await this.locationApi.getCountries();
      if (res.success) {
        this.countries.set(res.data);
      }
    } catch {
      this.countries.set([]);
    }
  }
}
