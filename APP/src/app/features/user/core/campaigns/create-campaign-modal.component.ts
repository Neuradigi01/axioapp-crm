import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';

import { ConversationChannel } from '../conversations/conversations-api.service';
import { extractApiError } from '@core/services/api-error.util';
import {
  Campaign,
  CampaignsApiService,
} from './campaigns-api.service';

/**
 * Create-campaign modal.
 *
 * Fields:
 *   - Name
 *   - Channel (whatsapp / sms / email / web / facebook / instagram)
 *   - Audience filter: q / source / tag (same shape as /contacts list).
 *     Empty filter = everyone in the org.
 *   - Template with `{{full_name}}` placeholder support
 *   - Schedule_at (optional, datetime-local) â€” if blank, send now-ish
 *     when the operator clicks Start.
 *
 * The campaign is created in `status='draft'`. The operator clicks
 * Start on the list/detail page to actually dispatch.
 */
@Component({
  selector: 'app-create-campaign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule],
  templateUrl: './create-campaign-modal.component.html',
})
export class CreateCampaignModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CampaignsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Output() readonly created = new EventEmitter<Campaign>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // String constants holding literal `{{...}}` so the template can
  // render them as text without Angular trying to interpolate them.
  protected readonly varFullName = '{{full_name}}';
  protected readonly varPhone = '{{phone}}';
  protected readonly templatePlaceholder =
    'Hi {{full_name}} â€” our Diwali sale is live! 20% off everything this week.';

  protected readonly channels: ReadonlyArray<{
    value: ConversationChannel;
    label: string;
  }> = [
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'sms', label: 'SMS' },
    { value: 'email', label: 'Email' },
    { value: 'facebook', label: 'Facebook' },
    { value: 'instagram', label: 'Instagram' },
    { value: 'web', label: 'Web' },
  ];

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    channel: this.fb.control<ConversationChannel>('whatsapp', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    audience_q: this.fb.control<string | null>(null),
    audience_source: this.fb.control<string | null>(null),
    audience_tag: this.fb.control<string | null>(null),
    template: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(4096)],
    }),
    schedule_at: this.fb.control<string | null>(null),
  });

  protected save(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const audience: { q?: string; source?: string; tag?: string } = {};
    if (v.audience_q?.trim()) audience.q = v.audience_q.trim();
    if (v.audience_source?.trim()) audience.source = v.audience_source.trim();
    if (v.audience_tag?.trim()) audience.tag = v.audience_tag.trim();

    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .create({
        name: v.name,
        channel: v.channel,
        audience_filter: audience,
        template: v.template,
        schedule_at: v.schedule_at
          ? new Date(v.schedule_at).toISOString()
          : null,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (campaign) => {
          this.submitting.set(false);
          this.created.emit(campaign);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(
            extractApiError(err) ?? 'Could not create campaign.',
          );
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }

}
