/**
 * Add-sender-identity modal shown from the Email Sender card. Three
 * tabs at the top:
 *
 *   1. Gmail    — button that kicks off the existing Gmail OAuth
 *                 consent flow (reused via `EmailAccountsApiService`).
 *   2. Microsoft — same for Microsoft Graph.
 *   3. SMTP     — form (from-address, display name, host, port,
 *                 username, password, TLS mode) → POST creates the
 *                 pending row + the backend emails a 6-digit code to
 *                 the from-address. The parent then shows the
 *                 verify-code sub-modal.
 *
 * On successful SMTP submit we emit `smtpCreated({sender, from})` so
 * the parent can open the verify-code modal without a full refetch.
 * OAuth taps close the modal via `cancelled` (the browser is about to
 * navigate away for consent).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  output,
  signal,
} from '@angular/core';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';
import { distinctUntilChanged } from 'rxjs/operators';

import { extractApiError } from '@core/services/api-error.util';
import { commonValidators } from '../../shared/validators';
import {
  MobileSelectComponent,
  MobileSelectOption,
} from '../../shared/forms/mobile-select.component';
import { EmailAccountsApiService } from '../../services/email-accounts-api.service';
import {
  CreateSmtpSenderPayload,
  EmailSendersApiService,
  SmtpSender,
  SmtpTlsMode,
} from './email-senders-api.service';

type Tab = 'gmail' | 'microsoft' | 'smtp';
type ProviderId =
  | 'custom'
  | 'gmail'
  | 'outlook'
  | 'zoho'
  | 'titan'
  | 'hostinger'
  | 'godaddy'
  | 'yahoo'
  | 'sendgrid'
  | 'mailgun';

/** Turnkey SMTP defaults for the ten providers that cover ~95% of
 *  hosted email in the wild. Picking one auto-fills host + port + TLS
 *  mode + optional username override so operators never see the
 *  "STARTTLS on port 465?" footgun that ate hours of debugging. */
interface ProviderPreset {
  id: ProviderId;
  label: string;
  host: string;
  port: number;
  tlsMode: SmtpTlsMode;
  /** Some providers require a fixed username string that ISN'T the
   *  from-address (e.g. SendGrid uses the literal word "apikey"). */
  usernameOverride?: string;
  /** Provider-specific gotcha rendered under the password field. */
  passwordHint?: string;
}

const PROVIDER_PRESETS: Record<ProviderId, ProviderPreset> = {
  custom: {
    id: 'custom',
    label: 'Custom SMTP server',
    host: '',
    port: 587,
    tlsMode: 'starttls',
  },
  gmail: {
    id: 'gmail',
    label: 'Gmail / Google Workspace',
    host: 'smtp.gmail.com',
    port: 465,
    tlsMode: 'tls',
    passwordHint:
      'Gmail requires an App Password, not your account password. Generate one at myaccount.google.com/apppasswords (needs 2-Step Verification turned on).',
  },
  outlook: {
    id: 'outlook',
    label: 'Outlook / Microsoft 365',
    host: 'smtp.office365.com',
    port: 587,
    tlsMode: 'starttls',
    passwordHint:
      'Use your Outlook mailbox password. If MFA is enabled on the account, generate an App Password in the Microsoft security settings.',
  },
  zoho: {
    id: 'zoho',
    label: 'Zoho Mail',
    host: 'smtp.zoho.com',
    port: 465,
    tlsMode: 'tls',
    passwordHint:
      'If 2FA is on, generate an App Password in Zoho account settings → Security → App Passwords.',
  },
  titan: {
    id: 'titan',
    label: 'Titan / Namecheap Private Email',
    host: 'smtp.titan.email',
    port: 465,
    tlsMode: 'tls',
    passwordHint:
      'Use your Titan mailbox password. If sending fails with "authentication failed", check your Titan inbox for a suspension notice (usually caused by missing DKIM).',
  },
  hostinger: {
    id: 'hostinger',
    label: 'Hostinger',
    host: 'smtp.hostinger.com',
    port: 465,
    tlsMode: 'tls',
  },
  godaddy: {
    id: 'godaddy',
    label: 'GoDaddy (Workspace / Professional Email)',
    host: 'smtpout.secureserver.net',
    port: 465,
    tlsMode: 'tls',
  },
  yahoo: {
    id: 'yahoo',
    label: 'Yahoo Mail',
    host: 'smtp.mail.yahoo.com',
    port: 465,
    tlsMode: 'tls',
    passwordHint:
      'Yahoo requires an App Password. Generate one at Account Security → Generate app password.',
  },
  sendgrid: {
    id: 'sendgrid',
    label: 'SendGrid',
    host: 'smtp.sendgrid.net',
    port: 587,
    tlsMode: 'starttls',
    usernameOverride: 'apikey',
    passwordHint:
      'Username is the literal word "apikey" (already filled). Password is your SendGrid API key — create one under Settings → API Keys with Mail Send access.',
  },
  mailgun: {
    id: 'mailgun',
    label: 'Mailgun',
    host: 'smtp.mailgun.org',
    port: 587,
    tlsMode: 'starttls',
    passwordHint:
      'Username is your Mailgun postmaster address (e.g. postmaster@mg.yourdomain.com). Password is the SMTP password from Mailgun → Sending → Domain settings.',
  },
};

/** Canonical port for each TLS mode — used to auto-snap the port
 *  field when the user changes TLS mode in Custom mode, so nobody
 *  submits port 587 + Implicit TLS by mistake. */
const CANONICAL_PORT: Record<SmtpTlsMode, number> = {
  starttls: 587,
  tls: 465,
  none: 25,
};

interface SmtpFormShape {
  provider: FormControl<ProviderId>;
  from_address: FormControl<string>;
  display_name: FormControl<string>;
  smtp_host: FormControl<string>;
  smtp_port: FormControl<number>;
  smtp_username: FormControl<string>;
  smtp_password: FormControl<string>;
  tls_mode: FormControl<SmtpTlsMode>;
}

@Component({
  selector: 'app-add-sender-identity-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule, MobileSelectComponent],
  templateUrl: './add-sender-identity-modal.component.html',
})
export class AddSenderIdentityModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly sendersApi = inject(EmailSendersApiService);
  private readonly oauthApi = inject(EmailAccountsApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly cancelled = output<void>();
  readonly smtpCreated = output<{ sender: SmtpSender; from: string }>();

  protected readonly tlsModeOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'starttls', label: 'STARTTLS (port 587, recommended)' },
    { value: 'tls', label: 'Implicit TLS (port 465)' },
    { value: 'none', label: 'None (localhost relay only)' },
  ];

  /** Provider select options — Custom first (default), then hosted
   *  providers alphabetised for scannability. Rendered in a
   *  `crm-mobile-select` above the SMTP form. */
  protected readonly providerOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'custom', label: PROVIDER_PRESETS.custom.label },
    { value: 'gmail', label: PROVIDER_PRESETS.gmail.label },
    { value: 'godaddy', label: PROVIDER_PRESETS.godaddy.label },
    { value: 'hostinger', label: PROVIDER_PRESETS.hostinger.label },
    { value: 'mailgun', label: PROVIDER_PRESETS.mailgun.label },
    { value: 'outlook', label: PROVIDER_PRESETS.outlook.label },
    { value: 'sendgrid', label: PROVIDER_PRESETS.sendgrid.label },
    { value: 'titan', label: PROVIDER_PRESETS.titan.label },
    { value: 'yahoo', label: PROVIDER_PRESETS.yahoo.label },
    { value: 'zoho', label: PROVIDER_PRESETS.zoho.label },
  ];

  protected readonly activeTab = signal<Tab>('smtp');
  protected readonly redirecting = signal<'gmail' | 'microsoft' | null>(null);
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly passwordVisible = signal(false);

  protected readonly form: FormGroup<SmtpFormShape> = this.fb.group<SmtpFormShape>({
    provider: this.fb.control<ProviderId>('custom', { nonNullable: true }),
    from_address: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, commonValidators.email, Validators.maxLength(254)],
    }),
    display_name: this.fb.control<string>('', {
      nonNullable: true,
      // Optional. If provided, must match the name shape (blocks digits, emoji, etc.).
      validators: [commonValidators.name, Validators.maxLength(128)],
    }),
    smtp_host: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, commonValidators.hostname, Validators.maxLength(253)],
    }),
    smtp_port: this.fb.control<number>(587, {
      nonNullable: true,
      validators: [Validators.required, Validators.min(1), Validators.max(65535)],
    }),
    smtp_username: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(254)],
    }),
    smtp_password: this.fb.control<string>('', {
      nonNullable: true,
      // Kept generous (4096) — enterprise SMTP secrets can exceed the
      // 256 the spec suggests as a "safe starting point"; matches
      // pre-existing behaviour to avoid regressing real installs.
      validators: [Validators.required, Validators.maxLength(4096)],
    }),
    tls_mode: this.fb.control<SmtpTlsMode>('starttls', {
      nonNullable: true,
      validators: [commonValidators.picklist(['starttls', 'tls', 'none'])],
    }),
  });

  private readonly formStatus = toSignal(this.form.statusChanges, {
    initialValue: this.form.status,
  });
  protected readonly isSmtpValid = computed(() => this.formStatus() === 'VALID');

  /** Reactive mirror of the provider control — drives the readonly
   *  toggle on host/port/TLS + the password hint under the field. */
  private readonly providerSignal = toSignal(this.form.controls.provider.valueChanges, {
    initialValue: this.form.controls.provider.value,
  });

  /** True when a hosted-provider preset is selected. Host / port /
   *  TLS-mode inputs become read-only in that case — the operator
   *  only enters their email + password. Custom mode leaves everything
   *  editable and adds the port-auto-snap-on-tls-change behaviour. */
  protected readonly isPresetProvider = computed(() => this.providerSignal() !== 'custom');

  /** Provider-specific "gotcha" text under the password field. Nulls
   *  out for Custom + providers with no notable auth quirks. */
  protected readonly passwordHint = computed<string | null>(() => {
    const preset = PROVIDER_PRESETS[this.providerSignal()];
    return preset.passwordHint ?? null;
  });

  constructor() {
    // Provider change → apply preset host/port/TLS/username in one
    // shot. Preserves any password already typed (users often paste
    // that first, then pick their provider).
    this.form.controls.provider.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((provider) => this.applyPreset(provider));

    // TLS-mode change on Custom → auto-snap port to the canonical
    // value (587 for STARTTLS, 465 for TLS, 25 for none) so the
    // port ↔ mode mismatch trap can't happen. On preset providers
    // the port is read-only so this only fires when the user is
    // configuring their own host.
    this.form.controls.tls_mode.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((mode) => {
        if (this.form.controls.provider.value !== 'custom') return;
        this.form.controls.smtp_port.setValue(CANONICAL_PORT[mode], { emitEvent: false });
      });

    // Auto-fill username from the from-address as the operator types.
    // Skipped for providers that mandate a fixed username string
    // (SendGrid → "apikey"). Only fills when the username field is
    // still empty so we never overwrite a manual entry.
    this.form.controls.from_address.valueChanges
      .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
      .subscribe((email) => {
        const provider = this.form.controls.provider.value;
        const preset = PROVIDER_PRESETS[provider];
        if (preset.usernameOverride) return;
        const usernameCtrl = this.form.controls.smtp_username;
        if (!usernameCtrl.value.trim() && email.trim()) {
          usernameCtrl.setValue(email.trim(), { emitEvent: false });
        }
      });
  }

  /** Apply the selected provider's defaults to the host/port/TLS/
   *  username fields AND toggle the disabled state so the operator
   *  can't accidentally edit a preset's canonical settings.
   *
   *  `emitEvent: false` on the writes so we don't re-trigger the
   *  tls_mode auto-snap listener (which would then reset the port to
   *  CANONICAL_PORT — the preset's port is what we actually want,
   *  and for well-known providers it always matches CANONICAL_PORT
   *  anyway). */
  private applyPreset(providerId: ProviderId): void {
    const preset = PROVIDER_PRESETS[providerId];
    if (providerId === 'custom') {
      // Flipping BACK to Custom re-enables the advanced fields so
      // the operator can point at their own server. Preserves the
      // last-picked values (a "let me edit what's here" gesture).
      this.form.controls.smtp_host.enable({ emitEvent: false });
      this.form.controls.smtp_port.enable({ emitEvent: false });
      this.form.controls.tls_mode.enable({ emitEvent: false });
      this.form.controls.smtp_username.enable({ emitEvent: false });
      return;
    }
    this.form.controls.smtp_host.setValue(preset.host, { emitEvent: false });
    this.form.controls.smtp_port.setValue(preset.port, { emitEvent: false });
    this.form.controls.tls_mode.setValue(preset.tlsMode, { emitEvent: false });
    // Lock the advanced fields — the preset has the canonical values
    // for this provider, editing them would break the connection.
    this.form.controls.smtp_host.disable({ emitEvent: false });
    this.form.controls.smtp_port.disable({ emitEvent: false });
    this.form.controls.tls_mode.disable({ emitEvent: false });
    if (preset.usernameOverride) {
      this.form.controls.smtp_username.setValue(preset.usernameOverride, { emitEvent: false });
      this.form.controls.smtp_username.disable({ emitEvent: false });
    } else {
      this.form.controls.smtp_username.enable({ emitEvent: false });
    }
  }

  selectTab(tab: Tab): void {
    if (this.submitting() || this.redirecting() !== null) return;
    this.activeTab.set(tab);
    this.error.set(null);
  }

  togglePassword(): void {
    this.passwordVisible.update((v) => !v);
  }

  connectGmail(): void {
    if (this.redirecting() !== null) return;
    this.redirecting.set('gmail');
    this.error.set(null);
    this.oauthApi
      .authorizeGmail()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.redirecting.set(null);
          this.error.set(extractApiError(err) ?? 'Gmail connect failed. Please try again.');
        },
      });
  }

  connectMicrosoft(): void {
    if (this.redirecting() !== null) return;
    this.redirecting.set('microsoft');
    this.error.set(null);
    this.oauthApi
      .authorizeMicrosoft()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: ({ url }) => {
          window.location.assign(url);
        },
        error: (err: HttpErrorResponse) => {
          this.redirecting.set(null);
          this.error.set(extractApiError(err) ?? 'Microsoft connect failed. Please try again.');
        },
      });
  }

  submitSmtp(): void {
    if (this.submitting()) return;
    this.form.markAllAsTouched();
    if (this.form.invalid) return;
    this.error.set(null);
    this.submitting.set(true);
    const raw = this.form.getRawValue();
    // `provider` is a UI-only aid — the backend gets host / port / TLS
    // mode directly and has no concept of the preset chosen.
    const payload: CreateSmtpSenderPayload = {
      from_address: raw.from_address.trim().toLowerCase(),
      display_name: raw.display_name.trim() || null,
      smtp_host: raw.smtp_host.trim(),
      smtp_port: raw.smtp_port,
      smtp_username: raw.smtp_username.trim(),
      smtp_password: raw.smtp_password,
      tls_mode: raw.tls_mode,
    };
    this.sendersApi
      .createSmtp(payload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (sender) => {
          this.submitting.set(false);
          this.smtpCreated.emit({ sender, from: payload.from_address });
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(extractApiError(err) ?? 'Could not create SMTP sender.');
        },
      });
  }

  cancel(): void {
    if (this.submitting() || this.redirecting() !== null) return;
    this.cancelled.emit();
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.cancel();
    }
  }
}
