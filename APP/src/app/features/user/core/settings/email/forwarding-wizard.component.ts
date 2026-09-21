/**
 * Forwarding-setup wizard (tasks/email-inbound-forwarding Step 6).
 *
 * 3-step flow that walks the operator from "which provider?" through
 * "copy this address" to "did the test email arrive?":
 *
 *   1. Pick provider — 6 cards (Gmail / Google Workspace / Outlook.com
 *      / Outlook 365 / Zoho / Custom). Click advances.
 *   2. Copy address — user names the endpoint. Clicking Next creates
 *      it on the server and displays the composed
 *      ``f-<token>@<inbound-domain>`` address with a big copy button.
 *   3. Follow guide + test — provider-specific step list from
 *      :mod:`provider-guides`. Backend status endpoint is polled every
 *      5s until the first message arrives or the 5min ceiling hits.
 *
 * ``created`` output fires when Step 2 successfully creates the
 * endpoint; ``closed`` fires when the user closes the wizard (on Step
 * 3 success, timeout, or explicit close). The parent tab reloads its
 * list on either signal.
 */
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  inject,
  output,
  signal,
} from '@angular/core';
import { FormBuilder, FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { LucideAngularModule } from 'lucide-angular';
import { Subscription } from 'rxjs';
import { extractApiError } from '@core/services/api-error.util';

import { ToastService } from '../../../../../shared/components/toast/toast.service';
import { InboundAddressesService } from './inbound-addresses.service';
import type { ForwardedAddress } from './models';
import { PROVIDER_GUIDES, PROVIDER_ORDER, type ProviderGuide } from './provider-guides';
import { TestInboundStatusService, type PollTick } from './test-inbound-status.service';

type WizardStep = 1 | 2 | 3;
type WizardStatus = 'waiting' | 'received' | 'timeout';

@Component({
  selector: 'app-forwarding-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [LucideAngularModule, ReactiveFormsModule],
  templateUrl: './forwarding-wizard.component.html',
})
export class ForwardingWizardComponent implements OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(InboundAddressesService);
  private readonly poll = inject(TestInboundStatusService);
  private readonly toast = inject(ToastService);

  readonly step = signal<WizardStep>(1);
  readonly providerKey = signal<string | null>(null);
  readonly creating = signal(false);
  readonly created = signal<ForwardedAddress | null>(null);
  readonly status = signal<WizardStatus>('waiting');

  readonly providerOrder = PROVIDER_ORDER;
  readonly guides = PROVIDER_GUIDES;

  protected readonly form: {
    label: FormControl<string>;
  } = {
    label: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.minLength(1), Validators.maxLength(128)],
    }),
  };

  private _pollSub: Subscription | null = null;

  /** Fires when the wizard closes for any reason — Step-3 success,
   * timeout, or explicit close. Parent tab reloads its list on this. */
  readonly closed = output<void>();

  activeGuide(): ProviderGuide | null {
    const key = this.providerKey();
    return key ? this.guides[key] : null;
  }

  pickProvider(key: string): void {
    if (!this.guides[key]) return;
    this.providerKey.set(key);
    this.step.set(2);
    // Pre-fill the label from the provider title so the operator has
    // a sensible default they can edit.
    const guide = this.guides[key];
    if (!this.form.label.value) {
      this.form.label.setValue(`Support inbox — ${guide.title}`);
    }
  }

  backToStep1(): void {
    if (this.creating() || this.created()) return;
    this.step.set(1);
  }

  createAndAdvance(): void {
    if (this.creating() || this.created()) return;
    if (this.form.label.invalid) {
      this.form.label.markAsTouched();
      return;
    }
    this.creating.set(true);
    this.api
      .create({
        label: this.form.label.value.trim(),
        auto_create_contact: true,
      })
      .subscribe({
        next: (row) => {
          this.created.set(row);
          this.creating.set(false);
          this.step.set(3);
          this._startPolling(row.id);
        },
        error: (err) => {
          this.creating.set(false);
          this.toast.error(extractApiError(err) ?? 'Could not create the address.');
        },
      });
  }

  async copyAddress(): Promise<void> {
    const row = this.created();
    if (!row) return;
    await navigator.clipboard.writeText(row.forwarding_address);
    this.toast.success('Address copied to clipboard.');
  }

  close(): void {
    this._stopPolling();
    this.closed.emit();
  }

  private _startPolling(endpointId: string): void {
    this._stopPolling();
    this._pollSub = this.poll.poll(endpointId).subscribe({
      next: (tick: PollTick) => {
        if (tick.kind === 'received') {
          this.status.set('received');
        } else if (tick.kind === 'timeout') {
          this.status.set('timeout');
        }
      },
    });
  }

  private _stopPolling(): void {
    this._pollSub?.unsubscribe();
    this._pollSub = null;
  }

  ngOnDestroy(): void {
    this._stopPolling();
  }
}
