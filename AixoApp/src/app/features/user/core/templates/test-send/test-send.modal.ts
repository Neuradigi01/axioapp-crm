import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';

import { TemplateRead, TemplateTestSendRead, TemplatesApiService } from '../templates-api.service';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
// E.164 with mandatory country code — must be `+<code><digits>`,
// matches the shared backend / form validator so what the operator
// types here matches what a contact record accepts.
const PHONE_RE = /^\+[1-9]\d{7,14}$/;

/**
 * Test-send modal — wraps the Step-5 endpoint.
 *
 * Validates the recipient per channel client-side (email-shape vs.
 * digits-8-to-15) before POST so the operator gets fast feedback,
 * then hands off to ``POST /api/v1/templates/{id}/test-send``.
 * Backend's `InvalidRecipient` is still surfaced if the client-side
 * check misses an edge case.
 *
 * The sample-context editor is a small JSON textarea (collapsed by
 * default). Operators who want to render a specific contact's name
 * type the JSON in; otherwise the backend's default sample payload
 * is used.
 */
@Component({
  selector: 'app-test-send-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, LucideAngularModule],
  templateUrl: './test-send.modal.html',
})
export class TestSendModalComponent {
  private readonly api = inject(TemplatesApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly template = input.required<TemplateRead>();
  readonly closed = output<void>();

  protected readonly recipient = signal<string>('');
  protected readonly sampleContextText = signal<string>('');
  protected readonly sampleContextOpen = signal<boolean>(false);

  protected readonly submitting = signal<boolean>(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<TemplateTestSendRead | null>(null);

  protected readonly channelLabel = computed(() => {
    switch (this.template().channel) {
      case 'email':
        return 'Email recipient';
      case 'whatsapp':
        return 'WhatsApp phone';
      case 'sms':
        return 'SMS phone';
      default:
        return 'Recipient';
    }
  });

  protected readonly placeholder = computed(() => {
    switch (this.template().channel) {
      case 'email':
        return 'you@example.com';
      case 'whatsapp':
      case 'sms':
        return '+919876543210';
      default:
        return 'channel-handle';
    }
  });

  protected readonly recipientValid = computed(() => {
    const v = this.recipient().trim();
    if (!v) return false;
    if (this.template().channel === 'email') return EMAIL_RE.test(v);
    if (this.template().channel === 'whatsapp' || this.template().channel === 'sms') {
      // Strip visual separators but keep the leading `+` — the country
      // code is mandatory.
      const cleaned = v.replace(/[\s()-]/g, '');
      return PHONE_RE.test(cleaned);
    }
    return v.length > 0;
  });

  protected readonly canSubmit = computed(() => !this.submitting() && this.recipientValid());

  protected onRecipientInput(value: string): void {
    this.recipient.set(value);
  }

  protected onSampleContextInput(value: string): void {
    this.sampleContextText.set(value);
  }

  protected toggleSampleContext(): void {
    this.sampleContextOpen.update((v) => !v);
  }

  protected submit(): void {
    if (!this.canSubmit()) return;
    this.submitting.set(true);
    this.error.set(null);
    this.result.set(null);

    let sample: Record<string, unknown> | null = null;
    const raw = this.sampleContextText().trim();
    if (raw) {
      try {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') {
          sample = parsed as Record<string, unknown>;
        } else {
          this.submitting.set(false);
          this.error.set('Sample context must be a JSON object.');
          return;
        }
      } catch {
        this.submitting.set(false);
        this.error.set('Sample context is not valid JSON.');
        return;
      }
    }

    this.api
      .testSend(this.template().id, {
        recipient: this.recipient().trim(),
        sample_context: sample,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.submitting.set(false);
          this.result.set(row);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.error.set(extractApiError(err) ?? 'Test send failed.');
        },
      });
  }

  protected close(): void {
    if (this.submitting()) return;
    this.closed.emit();
  }
}
