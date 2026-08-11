/**
 * Settings → Integrations → WhatsApp Business card.
 *
 * Differs structurally from GoogleCardComponent and MetaCardComponent
 * because WhatsApp Cloud API is NOT OAuth — there's no consent
 * redirect. The operator pastes 4 long-lived values (phone_id,
 * waba_id, access_token, verify_token) into an inline form and the
 * backend validates them against `graph.facebook.com` before
 * persisting (Step 3.5.1). App Secret is sourced from the platform
 * env (`WHATSAPP_APP_SECRET`) — one shared Meta App across tenants,
 * so no per-org paste. One click, one network round-trip, either
 * success or a Meta error message inline.
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
import { CommonModule, DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
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
  WhatsAppTemplate,
} from './integrations-api.service';
import { EmbeddedSignupCancelled, WhatsAppFbSdkService } from './whatsapp-fb-sdk.service';
import { PhoneHealthCardComponent } from '../../whatsapp/phone-health/phone-health-card.component';
import { WhatsAppNumbersService } from '../../whatsapp/shared/whatsapp-numbers.service';

interface WhatsAppConnectForm {
  phone_id: FormControl<string>;
  waba_id: FormControl<string>;
  access_token: FormControl<string>;
  verify_token: FormControl<string>;
  api_version: FormControl<string>;
  rate_limit_per_sec: FormControl<number>;
}

@Component({
  selector: 'app-whatsapp-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    DatePipe,
    LucideAngularModule,
    ReactiveFormsModule,
    PhoneHealthCardComponent,
  ],
  templateUrl: './whatsapp-card.component.html',
})
export class WhatsAppCardComponent implements OnInit {
  readonly status = input<WhatsAppStatus | null>(null);

  readonly changed = output<void>();
  readonly inlineError = signal<string | null>(null);

  private readonly api = inject(IntegrationsApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly fb = inject(FormBuilder);
  private readonly fbSdk = inject(WhatsAppFbSdkService);
  private readonly numbersService = inject(WhatsAppNumbersService);

  /** Step 27b — every connected WhatsApp phone for this org. The
   *  card renders a per-row list when there are 2+. The default
   *  `status` projection still drives the "Connected as …" header
   *  so single-number orgs see no visual change. */
  protected readonly numbers = this.numbersService.numbers;
  protected readonly hasMultiple = (): boolean => (this.numbersService.numbers()?.length ?? 0) >= 2;

  ngOnInit(): void {
    // Best-effort — failure is silent; the multi-number block just
    // doesn't render. The card still works exactly as before.
    this.numbersService
      .refresh()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ error: () => undefined });
  }

  /** Manual-paste form visibility. Collapsed by default — the hero
   *  "Connect WhatsApp" button (Embedded Signup) is the primary path.
   *  Operators on self-hosted Meta Apps expand the Advanced section
   *  to reveal it. */
  protected readonly formExpanded = signal(false);
  /** Outer "Advanced — paste credentials manually" collapsible.
   *  Wraps the entire 5-field form (which itself has an inner
   *  Advanced section for api_version + rate_limit). Distinct
   *  from `formExpanded` so the manual form stays in DOM only
   *  when the Advanced section is open. */
  protected readonly manualAdvancedExpanded = signal(false);
  /** Inner advanced section (api_version + rate_limit_per_sec) of
   *  the manual form. */
  protected readonly advancedExpanded = signal(false);
  /** Embedded Signup orchestration in-flight — SDK loading, popup
   *  open, or backend exchange. Drives the hero button spinner. */
  protected readonly embeddedConnecting = signal(false);

  /** Per-button in-flight flags drive spinner state. Four separate
   *  signals (not one shared) so concurrent actions can't reset each
   *  other's UI. */
  protected readonly connecting = signal(false);
  protected readonly testing = signal(false);
  protected readonly disconnecting = signal(false);
  protected readonly syncing = signal(false);
  /** Last successful sync counts — toast text. Cleared after 5s by
   *  the template's CSS transition; no JS timer needed. */
  protected readonly syncResult = signal<{
    added: number;
    updated: number;
    removed: number;
  } | null>(null);

  /** Cached templates for the connected org. Surfaces every status
   *  (APPROVED / PENDING / REJECTED / PAUSED / DISABLED) so the
   *  operator can see what's waiting on Meta's review — the campaign
   *  picker only shows APPROVED, so without this surface the operator
   *  has to leave the app for WhatsApp Manager to check approval state. */
  protected readonly templates = signal<WhatsAppTemplate[]>([]);
  protected readonly templatesExpanded = signal(false);
  protected readonly templatesLoading = signal(false);
  protected readonly templatesLoaded = signal(false);
  protected readonly templatesError = signal<string | null>(null);

  protected readonly templateCounts = computed(() => {
    const counts = { APPROVED: 0, PENDING: 0, REJECTED: 0, PAUSED: 0, DISABLED: 0 };
    for (const t of this.templates()) {
      const k = (t.status ?? '').toUpperCase() as keyof typeof counts;
      if (k in counts) counts[k] += 1;
    }
    return counts;
  });

  protected readonly form: FormGroup<WhatsAppConnectForm> = this.fb.nonNullable.group({
    phone_id: this.fb.nonNullable.control('', Validators.required),
    waba_id: this.fb.nonNullable.control('', Validators.required),
    access_token: this.fb.nonNullable.control('', Validators.required),
    verify_token: this.fb.nonNullable.control('', Validators.required),
    api_version: this.fb.nonNullable.control('v18.0', Validators.required),
    rate_limit_per_sec: this.fb.nonNullable.control(50, [
      Validators.required,
      Validators.min(1),
      Validators.max(1000),
    ]),
  });

  // --- derived UI flags --------------------------------------------

  protected readonly currentStatus = computed(() => this.status()?.status ?? 'disconnected');
  protected readonly isConnected = computed(() => this.currentStatus() === 'connected');
  protected readonly isError = computed(() => {
    const s = this.currentStatus();
    return s === 'error' || s === 'expired';
  });
  protected readonly isDisconnected = computed(() => this.currentStatus() === 'disconnected');

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
      const patch: Partial<{
        phone_id: string;
        waba_id: string;
        api_version: string;
        rate_limit_per_sec: number;
      }> = {};
      if (s.phone_id) patch.phone_id = s.phone_id;
      if (s.waba_id) patch.waba_id = s.waba_id;
      if (s.api_version) patch.api_version = s.api_version;
      if (s.rate_limit_per_sec !== null && s.rate_limit_per_sec !== undefined) {
        patch.rate_limit_per_sec = s.rate_limit_per_sec;
      }
      if (Object.keys(patch).length > 0) {
        this.form.patchValue(patch);
      }
    });

    // Templates auto-load when the card is connected so the count
    // pills render without requiring an explicit expand. On
    // disconnect/error transitions we wipe the cache so a reconnect
    // refetches with the new credentials.
    effect(() => {
      if (this.isConnected()) {
        if (!this.templatesLoaded() && !this.templatesLoading()) {
          this.refreshTemplates();
        }
      } else if (this.templatesLoaded() || this.templates().length > 0) {
        this.templates.set([]);
        this.templatesLoaded.set(false);
        this.templatesExpanded.set(false);
        this.templatesError.set(null);
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
    this.form.patchValue({ access_token: '' });
  }

  toggleAdvanced(): void {
    this.advancedExpanded.update((v) => !v);
  }

  toggleManualAdvanced(): void {
    this.manualAdvancedExpanded.update((v) => !v);
    if (!this.manualAdvancedExpanded()) {
      // Collapsing the outer wrapper also closes the inner form so a
      // re-expand starts on the friendly default surface.
      this.formExpanded.set(false);
    }
  }

  /**
   * Embedded Signup orchestration — the hero "Connect WhatsApp"
   * button. Loads Meta's FB JS SDK on demand, opens the ES popup,
   * harvests the (code, phone_number_id, waba_id) triple, and POSTs
   * it to the Step-2 backend `/embedded-signup/exchange` endpoint.
   *
   * Error surfaces:
   *  - Cancelled popup → friendly toast, card stays disconnected.
   *  - SDK load failure → inline error, retry tooltip.
   *  - Backend 4xx/5xx → inline error with the backend's user_message.
   */
  async connectEmbedded(): Promise<void> {
    if (this.embeddedConnecting()) return;
    this.inlineError.set(null);
    this.embeddedConnecting.set(true);
    try {
      const config = await new Promise<{
        app_id: string;
        config_id: string;
        graph_api_version: string;
      }>((resolve, reject) => {
        this.api
          .getWhatsAppEmbeddedSignupConfig()
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({ next: resolve, error: reject });
      });

      if (!config.app_id || !config.config_id) {
        this.inlineError.set(
          'Embedded Signup is not configured on this server. ' +
            'Use the Advanced manual flow below or contact your admin.',
        );
        return;
      }

      await this.fbSdk.loadSdk(config.app_id, config.graph_api_version);
      const result = await this.fbSdk.openSignup(config.config_id);

      await new Promise<void>((resolve, reject) => {
        this.api
          .exchangeWhatsAppEmbeddedSignup({
            code: result.code,
            phone_number_id: result.phoneNumberId,
            waba_id: result.wabaId,
          })
          .pipe(takeUntilDestroyed(this.destroyRef))
          .subscribe({
            next: () => resolve(),
            error: reject,
          });
      });

      this.changed.emit();
    } catch (err) {
      if (err instanceof EmbeddedSignupCancelled) {
        // user_cancelled is non-fatal — surface a soft inline note
        // rather than the red error banner. Popup-blocked / load-
        // failed are real errors and get the banner.
        if (err.reason === 'user_cancelled') {
          this.inlineError.set(null);
        } else {
          this.inlineError.set(err.message);
        }
      } else if (err instanceof HttpErrorResponse) {
        this.inlineError.set(extractApiError(err));
      } else {
        this.inlineError.set(err instanceof Error ? err.message : 'Unable to connect WhatsApp.');
      }
    } finally {
      this.embeddedConnecting.set(false);
    }
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
          this.form.patchValue({ access_token: '' });
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

  /** Pull approved templates from Meta into the local cache. Drives
   *  the Settings card's "Sync templates" button — only visible when
   *  the account is connected (the API rejects with 409 otherwise,
   *  but hiding the button avoids the round-trip). */
  syncTemplates(): void {
    if (this.syncing()) return;
    this.inlineError.set(null);
    this.syncResult.set(null);
    this.syncing.set(true);
    this.api
      .syncWhatsAppTemplates()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (result) => {
          this.syncing.set(false);
          this.syncResult.set({
            added: result.added,
            updated: result.updated,
            removed: result.removed,
          });
          this.refreshTemplates();
        },
        error: (err: HttpErrorResponse) => {
          this.syncing.set(false);
          this.inlineError.set(extractApiError(err));
        },
      });
  }

  toggleTemplates(): void {
    this.templatesExpanded.update((v) => !v);
  }

  /** Re-fetch the cached templates list. Called automatically on
   *  first connect and after each successful sync; safe to invoke
   *  repeatedly (the loading guard suppresses overlapping requests). */
  refreshTemplates(): void {
    if (this.templatesLoading()) return;
    this.templatesLoading.set(true);
    this.templatesError.set(null);
    this.api
      .listWhatsAppTemplates()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.templates.set(rows);
          this.templatesLoading.set(false);
          this.templatesLoaded.set(true);
        },
        error: (err: HttpErrorResponse) => {
          this.templatesLoading.set(false);
          this.templatesError.set(extractApiError(err));
        },
      });
  }
}
