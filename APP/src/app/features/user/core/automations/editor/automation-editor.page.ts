import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LucideAngularModule } from 'lucide-angular';

import { extractApiError } from '@core/services/api-error.util';
import { FurnitureAuthService } from '../../auth/auth.service';
import { TemplatesApiService } from '../../templates/templates-api.service';

import {
  AutomationsApiService,
  DryRunResult,
  EventCatalogEntry,
  TriggerChannel,
  TriggerRead,
} from '../automations-api.service';
import { ConditionBuilderComponent } from './condition-builder.component';
import { EventInfoCardComponent } from './event-info-card.component';
import { TemplatePickerComponent } from './template-picker.component';

/**
 * Trigger editor — `/user/automations/new` for create, `/:id` for
 * edit. Composes:
 *
 *   1. Header bar: name, enabled toggle, Save / Save & Test buttons.
 *   2. Four stacked cards: "When this happens" (event picker),
 *      "Only if" (condition builder), "Then send" (channel +
 *      template picker), "To" (recipient resolver + delay).
 *   3. Right sidebar: sample-payload paste-tester for Save & Test.
 *
 * Save flow: POST or PATCH the trigger → toast → stay on the same
 * URL (route swaps from /new to /:id on first save). Save & Test
 * runs the same save then opens the dry-run modal pre-filled with
 * the event's sample payload.
 */

type ChannelOption = '' | TriggerChannel;

const CHANNEL_OPTIONS: Array<{ value: TriggerChannel; label: string }> = [
  { value: 'email', label: 'Email' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'sms', label: 'SMS' },
  { value: 'facebook', label: 'Facebook Messenger' },
  { value: 'instagram', label: 'Instagram Direct' },
  { value: 'push', label: 'Push notification' },
];

const RESOLVER_OPTIONS: Array<{ value: string; label: string; needsConfig: boolean }> = [
  { value: 'contact.email', label: "Contact's email", needsConfig: false },
  { value: 'contact.phone', label: "Contact's phone", needsConfig: false },
  { value: 'user.email', label: "User's email (system events)", needsConfig: false },
  { value: 'custom', label: 'Custom JSONPath', needsConfig: true },
];

@Component({
  selector: 'app-automation-editor-page',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    EventInfoCardComponent,
    ConditionBuilderComponent,
    TemplatePickerComponent,
  ],
  templateUrl: './automation-editor.page.html',
})
export class AutomationEditorPageComponent {
  private readonly api = inject(AutomationsApiService);
  private readonly templatesApi = inject(TemplatesApiService);
  private readonly auth = inject(FurnitureAuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly CHANNEL_OPTIONS = CHANNEL_OPTIONS;
  protected readonly RESOLVER_OPTIONS = RESOLVER_OPTIONS;

  // --- form ---------------------------------------------------------

  protected readonly form = new FormGroup({
    name: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(120)],
    }),
    event_type: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    channel: new FormControl<ChannelOption>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    template_id: new FormControl<string>('', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    enabled: new FormControl<boolean>(true, { nonNullable: true }),
    delay_seconds: new FormControl<number>(0, {
      nonNullable: true,
      validators: [Validators.min(0), Validators.max(60 * 60 * 24 * 30)],
    }),
    recipient_resolver: new FormControl<string>('contact.email', {
      nonNullable: true,
      validators: [Validators.required],
    }),
    recipient_resolver_config_path: new FormControl<string>('', {
      nonNullable: true,
    }),
  });

  protected readonly conditions = signal<Record<string, unknown>>({});

  // --- state --------------------------------------------------------

  protected readonly trigger = signal<TriggerRead | null>(null);
  protected readonly catalog = signal<EventCatalogEntry[]>([]);
  protected readonly templateName = signal<string | null>(null);

  protected readonly loadError = signal<string | null>(null);
  protected readonly saveError = signal<string | null>(null);
  protected readonly toast = signal<string | null>(null);
  protected readonly saving = signal<boolean>(false);

  protected readonly pickerOpen = signal<boolean>(false);
  protected readonly testModalOpen = signal<boolean>(false);
  protected readonly testPayloadText = signal<string>('');
  protected readonly testResult = signal<DryRunResult | null>(null);
  protected readonly testRunning = signal<boolean>(false);

  protected readonly canWrite = computed(() => this.auth.hasPermission('automations.write'));

  protected readonly selectedEntry = computed<EventCatalogEntry | null>(() => {
    const et = this.form.controls.event_type.value;
    return this.catalog().find((e) => e.event_type === et) ?? null;
  });

  protected readonly samplePayload = computed<Record<string, unknown>>(
    () => this.selectedEntry()?.sample_payload ?? {},
  );

  protected readonly channelLocked = computed<boolean>(() => this.trigger() !== null);

  constructor() {
    // Load the catalog once.
    this.api
      .listEventTypes()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (entries) => this.catalog.set(entries),
        error: () => {
          // Non-fatal — the editor still works; the event picker
          // just shows no autocomplete.
        },
      });

    // Load the trigger when the route carries an :id.
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      if (id) this.loadTrigger(id);
    });

    // When the picked template changes, fetch its name once for
    // the chip label.
    effect(() => {
      const id = this.form.controls.template_id.value;
      if (!id) {
        this.templateName.set(null);
        return;
      }
      this.templatesApi
        .get(id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (t) => this.templateName.set(t.name),
          error: () => this.templateName.set(null),
        });
    });

    // When the operator switches channel mid-edit, clear the
    // picked template — it almost certainly won't fit the new
    // channel.
    this.form.controls.channel.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        if (this.form.controls.template_id.value) {
          this.form.controls.template_id.setValue('');
          this.templateName.set(null);
        }
      });
  }

  // --- load + hydrate -----------------------------------------

  private loadTrigger(id: string): void {
    this.loadError.set(null);
    this.api
      .get(id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (row) => {
          this.trigger.set(row);
          this.form.patchValue(
            {
              name: row.name,
              event_type: row.event_type,
              channel: row.channel as ChannelOption,
              template_id: row.template_id,
              enabled: row.enabled,
              delay_seconds: row.delay_seconds,
              recipient_resolver: row.recipient_resolver,
              recipient_resolver_config_path: String(
                (row.recipient_resolver_config as Record<string, unknown>)?.['path'] ?? '',
              ),
            },
            { emitEvent: false },
          );
          // Channel is locked once a trigger exists — keep this
          // disabled so the operator doesn't break the template
          // link by accident.
          this.form.controls.channel.disable({ emitEvent: false });
          this.conditions.set(row.conditions || {});
        },
        error: (err: HttpErrorResponse) => {
          this.loadError.set(extractApiError(err) ?? 'Could not load automation.');
        },
      });
  }

  // --- template picker ----------------------------------------

  protected openPicker(): void {
    if (this.canWrite() && this.form.controls.channel.value) {
      this.pickerOpen.set(true);
    }
  }

  protected onTemplatePicked(template: { id: string; name: string }): void {
    this.form.controls.template_id.setValue(template.id);
    this.templateName.set(template.name);
    this.pickerOpen.set(false);
  }

  protected closePicker(): void {
    this.pickerOpen.set(false);
  }

  // --- conditions binding -------------------------------------

  protected onConditionsChange(next: Record<string, unknown>): void {
    this.conditions.set(next);
  }

  // --- save flow ----------------------------------------------

  protected save(thenTest: boolean = false): void {
    if (!this.canWrite()) return;
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      this.saveError.set('Fix the highlighted fields and try again.');
      return;
    }
    const v = this.form.getRawValue();
    if (v.recipient_resolver === 'custom' && !v.recipient_resolver_config_path.trim()) {
      this.saveError.set('Custom resolver requires a JSONPath.');
      return;
    }

    this.saveError.set(null);
    this.saving.set(true);

    const existing = this.trigger();
    const config =
      v.recipient_resolver === 'custom' ? { path: v.recipient_resolver_config_path.trim() } : {};

    const payload = {
      name: v.name,
      event_type: v.event_type,
      channel: v.channel as TriggerChannel,
      template_id: v.template_id,
      enabled: v.enabled,
      conditions: this.conditions(),
      delay_seconds: v.delay_seconds,
      recipient_resolver: v.recipient_resolver,
      recipient_resolver_config: config,
    };

    const obs = existing ? this.api.update(existing.id, payload) : this.api.create(payload);

    obs.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (row) => {
        this.saving.set(false);
        this.trigger.set(row);
        this.toast.set(existing ? 'Saved.' : 'Created.');
        if (!existing) {
          void this.router.navigate(['/user/automations', row.id], { replaceUrl: true });
        }
        if (thenTest) {
          this.openTestModal(row.id);
        }
      },
      error: (err: HttpErrorResponse) => {
        this.saving.set(false);
        this.saveError.set(extractApiError(err) ?? 'Could not save automation.');
      },
    });
  }

  protected saveAndTest(): void {
    this.save(true);
  }

  // --- dry-run modal -------------------------------------------

  protected openTestModal(_triggerId?: string): void {
    const sample = this.selectedEntry()?.sample_payload ?? {};
    this.testPayloadText.set(JSON.stringify(sample, null, 2));
    this.testResult.set(null);
    this.testModalOpen.set(true);
  }

  protected closeTestModal(): void {
    this.testModalOpen.set(false);
  }

  protected onTestPayloadInput(value: string): void {
    this.testPayloadText.set(value);
  }

  protected runDryRun(): void {
    const id = this.trigger()?.id;
    if (!id) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(this.testPayloadText());
    } catch {
      this.testResult.set({
        would_match: false,
        skip_reason: 'invalid_json',
        would_send_to: null,
        rendered_subject: null,
        rendered_body: null,
      });
      return;
    }
    this.testRunning.set(true);
    this.api
      .dryRun(id, parsed)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          this.testRunning.set(false);
          this.testResult.set(res);
        },
        error: () => {
          this.testRunning.set(false);
          this.testResult.set({
            would_match: false,
            skip_reason: 'request_failed',
            would_send_to: null,
            rendered_subject: null,
            rendered_body: null,
          });
        },
      });
  }

  protected dismissToast(): void {
    this.toast.set(null);
  }

  protected resolverNeedsConfig(): boolean {
    return this.form.controls.recipient_resolver.value === 'custom';
  }
}
