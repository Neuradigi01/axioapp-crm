/**
 * Settings → Integrations → WhatsApp Business card.
 *
 * Differs structurally from GoogleCardComponent and MetaCardComponent
 * because WhatsApp Cloud API is NOT OAuth — there's no consent
 * redirect. The operator pastes 5 long-lived values (phone_id,
 * waba_id, access_token, app_secret, verify_token) into an inline
 * form and the backend validates them against `graph.facebook.com`
 * before persisting (Step 3.5.1). One click, one network round-trip,
 * either success or a Meta error message inline.
 *
 * State machine:
 *
 *                 ┌────────────────────────────────────────┐
 *                 │      Disconnected  (initial)           │
 *                 │  ┌──────────────────────────────────┐  │
 *                 │  │  Header: 🅦 + "Not connected"    │  │
 *                 │  │  Body  : "Connect WhatsApp" CTA  │  │
 *                 │  │          ↓ click                 │  │
 *                 │  │          expand form (5 fields)  │  │
 *                 │  │          ↓ submit                │  │
 *                 │  └──────────────────────────────────┘  │
 *                 └─────────────────┬──────────────────────┘
 *                                   │ POST /connect → 200
 *                                   ▼
 *                 ┌────────────────────────────────────────┐
 *                 │       Connected                        │
 *                 │  ┌──────────────────────────────────┐  │
 *                 │  │  Header: 🟢 Connected            │  │
 *                 │  │  Body  : display_phone_number,   │  │
 *                 │  │          verified_name           │  │
 *                 │  │          [Test]   [Disconnect]   │  │
 *                 │  └──────────────────────────────────┘  │
 *                 └────────────────────────────────────────┘
 *                                   │ Meta rejects /test
 *                                   ▼
 *                 ┌────────────────────────────────────────┐
 *                 │       Error                            │
 *                 │  ┌──────────────────────────────────┐  │
 *                 │  │  Header: 🔴 Error                │  │
 *                 │  │  Body  : red banner + last_error │  │
 *                 │  │          [Reconnect] [Disconnect]│  │
 *                 │  └──────────────────────────────────┘  │
 *                 └────────────────────────────────────────┘
 *
 * Reconnect prefills `phone_id` / `waba_id` from the sidecar config
 * (those persist across disconnect for exactly this reason — the
 * operator shouldn't have to retype identifiers when only the token
 * was rotated). Tokens NEVER prefill (backend doesn't expose them).
 */
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  FormBuilder,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import {
  IntegrationsApiService,
  WhatsAppStatus,
} from './integrations-api.service';


interface WhatsAppConnectForm {
  phone_id: FormControl<string>;
  waba_id: FormControl<string>;
  access_token: FormControl<string>;
  app_secret: FormControl<string>;
  verify_token: FormControl<string>;
  api_version: FormControl<string>;
}


@Component({
  selector: 'app-whatsapp-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './whatsapp-card.component.html',
})
export class WhatsAppCardComponent {
  readonly status = input<WhatsAppStatus | null>(null);

  readonly changed = output<void>();
  readonly inlineError = signal<string | null>(null);

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder);

  /** Connect form panel visibility. Auto-expands the first time an
   *  Owner clicks Connect on a disconnected card; stays closed
   *  after successful submit so the connected view isn't crowded. */
  protected readonly formExpanded = signal(false);
  /** Advanced section (api_version) collapsed by default — most
   *  operators use the v18.0 default. */
  protected readonly advancedExpanded = signal(false);

  /** Per-button in-flight flags drive spinner state. Three separate
   *  signals (not one shared) so two simultaneous actions can't both
   *  reset each other's UI. */
  protected readonly connecting = signal(false);
  protected readonly testing = signal(false);
  protected readonly disconnecting = signal(false);

  protected readonly form: FormGroup<WhatsAppConnectForm> = this.fb.nonNullable.group({
    phone_id: this.fb.nonNullable.control('', Validators.required),
    waba_id: this.fb.nonNullable.control('', Validators.required),
    access_token: this.fb.nonNullable.control('', Validators.required),
    app_secret: this.fb.nonNullable.control('', Validators.required),
    verify_token: this.fb.nonNullable.control('', Validators.required),
    api_version: this.fb.nonNullable.control('v18.0', Validators.required),
  });

  // --- derived UI flags --------------------------------------------

  protected readonly currentStatus = computed(
    () => this.status()?.status ?? 'disconnected',
  );
  protected readonly isConnected = computed(
    () => this.currentStatus() === 'connected',
  );
  protected readonly isError = computed(() => {
    const s = this.currentStatus();
    return s === 'error' || s === 'expired';
  });
  protected readonly isDisconnected = computed(
    () => this.currentStatus() === 'disconnected',
  );

  constructor() {
    // Prefill phone_id + waba_id from the sidecar whenever the parent
    // hands us a status row with those fields set — covers both the
    // post-disconnect reconnect flow (sidecar survives) and the
    // post-error reconnect flow.
    effect(() => {
      const s = this.status();
      if (!s || this.isConnected()) {
        return;
      }
      const patch: Partial<Record<keyof WhatsAppConnectForm, string>> = {};
      if (s.phone_id) patch.phone_id = s.phone_id;
      if (s.waba_id) patch.waba_id = s.waba_id;
      if (s.api_version) patch.api_version = s.api_version;
      if (Object.keys(patch).length > 0) {
        this.form.patchValue(patch);
      }
    });
  }

  // --- actions -----------------------------------------------------

  openForm(): void {
    this.inlineError.set(null);
    this.formExpanded.set(true);
  }

  cancelForm(): void {
    this.formExpanded.set(false);
    this.inlineError.set(null);
    // Wipe secrets — leave phone_id / waba_id / api_version so a
    // re-open doesn't lose the prefilled identifiers.
    this.form.patchValue({ access_token: '', app_secret: '' });
  }

  toggleAdvanced(): void {
    this.advancedExpanded.update((v) => !v);
  }

  connect(): void {
    if (this.form.invalid || this.connecting()) {
      this.form.markAllAsTouched();
      return;
    }
    this.inlineError.set(null);
    this.connecting.set(true);
    this.api
      .connectWhatsApp(this.form.getRawValue())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.connecting.set(false);
          this.formExpanded.set(false);
          this.form.patchValue({ access_token: '', app_secret: '' });
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.connecting.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  test(): void {
    if (this.testing()) return;
    this.inlineError.set(null);
    this.testing.set(true);
    this.api
      .testWhatsApp()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.testing.set(false);
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.testing.set(false);
          this.inlineError.set(extractApiError(err));
          // Parent refresh anyway — backend flipped status to `error`
          // and persisted `last_error`, so the card needs the new
          // projection to render the red banner correctly.
          this.changed.emit();
        },
      });
  }

  disconnect(): void {
    if (this.disconnecting()) return;
    if (
      !confirm(
        'Disconnect WhatsApp? Campaigns will stop sending until you reconnect. The phone_id / waba_id will be remembered so you can paste a fresh token to reconnect later.',
      )
    ) {
      return;
    }
    this.inlineError.set(null);
    this.disconnecting.set(true);
    this.api
      .disconnectWhatsApp()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.disconnecting.set(false);
          this.changed.emit();
        },
        error: (err: HttpErrorResponse) => {
          this.disconnecting.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  reconnect(): void {
    this.openForm();
  }
}
