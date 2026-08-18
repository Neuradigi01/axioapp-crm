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

interface SmtpFormShape {
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

  protected readonly activeTab = signal<Tab>('smtp');
  protected readonly redirecting = signal<'gmail' | 'microsoft' | null>(null);
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly passwordVisible = signal(false);

  protected readonly form: FormGroup<SmtpFormShape> = this.fb.group<SmtpFormShape>({
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
