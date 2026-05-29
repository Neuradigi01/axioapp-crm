import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  EventEmitter,
  Output,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { Subject, of } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { ConversationChannel } from '../conversations/conversations-api.service';
import { extractApiError } from '@core/services/api-error.util';
import {
  ContactGroup,
  ContactGroupsApiService,
  GroupFilter,
} from '../contacts/groups/groups-api.service';
import {
  IntegrationsApiService,
  WhatsAppTemplate,
} from '../settings/integrations/integrations-api.service';
import {
  AudienceFilter,
  Campaign,
  CampaignsApiService,
  TemplateVariableBinding,
} from './campaigns-api.service';

/**
 * Create-campaign modal.
 *
 * Two template authoring modes drive the body input:
 *
 *  - **Free text** (non-WA channels, or WA-text-fallback): textarea
 *    with `{{full_name}}` Mustache placeholder for the legacy
 *    contact-name interpolation.
 *  - **WA template picker** (Step 3.5.5 — channel='whatsapp'):
 *    dropdown of approved templates loaded from
 *    `GET /api/v1/integrations/whatsapp/templates?status=APPROVED`.
 *    Selecting a template shows a body preview + one input per
 *    `{{n}}` placeholder; each input has a "Static text" / "Contact
 *    field" toggle so the operator can either pin a literal value
 *    or bind to a contact attribute (full_name / phone / email).
 *    Step 3.5.6 dispatch resolves the field bindings per contact.
 *
 * Schema-level validation (backend `CampaignCreate`) enforces
 * "exactly one of template or template_id" — this modal serializes
 * the right shape based on the selected mode.
 */
@Component({
  selector: 'app-create-campaign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, LucideAngularModule],
  templateUrl: './create-campaign-modal.component.html',
})
export class CreateCampaignModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CampaignsApiService);
  private readonly integrationsApi = inject(IntegrationsApiService);
  private readonly groupsApi = inject(ContactGroupsApiService);
  private readonly destroyRef = inject(DestroyRef);

  @Output() readonly created = new EventEmitter<Campaign>();
  @Output() readonly cancel = new EventEmitter<void>();

  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);

  // --- Audience builder state (Step 3.5.9) --------------------------

  /** Three modes — Everyone (default), Saved group, Custom filter.
   *  Per Step 3.5.9 pre-implementation choice (a) — "Everyone" is
   *  the safest default for a fresh campaign. */
  protected readonly audienceMode = signal<'everyone' | 'group' | 'filter'>(
    'everyone',
  );
  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly groupsLoaded = signal(false);
  protected readonly selectedGroupId = signal<string | null>(null);

  protected readonly audienceCount = signal<number | null>(null);
  protected readonly audienceCountLoading = signal(false);
  private readonly audiencePreview$ = new Subject<void>();

  // --- WhatsApp template picker state -------------------------------

  protected readonly templates = signal<WhatsAppTemplate[]>([]);
  protected readonly templatesLoading = signal(false);
  protected readonly templatesLoaded = signal(false);
  protected readonly selectedTemplateId = signal<string | null>(null);
  /** Variable bindings per `{{n}}`. Key is the variable number as
   *  string ('1','2',...) to match backend's JSONB shape. */
  protected readonly variables = signal<Record<string, TemplateVariableBinding>>({});

  protected readonly contactFieldOptions: ReadonlyArray<{
    value: string;
    label: string;
  }> = [
    { value: 'full_name', label: 'Contact full name' },
    { value: 'phone', label: 'Contact phone' },
    { value: 'email', label: 'Contact email' },
  ];

  protected readonly selectedTemplate = computed<WhatsAppTemplate | null>(
    () =>
      this.templates().find((t) => t.id === this.selectedTemplateId()) ??
      null,
  );

  protected readonly templateVariableNumbers = computed<number[]>(() => {
    const t = this.selectedTemplate();
    if (!t) return [];
    // Match the backend's _VARIABLE_RE — distinct, sorted.
    const found = new Set<number>();
    const re = /\{\{(\d+)\}\}/g;
    let m: RegExpExecArray | null;
    while ((m = re.exec(t.body)) !== null) {
      found.add(parseInt(m[1], 10));
    }
    return [...found].sort((a, b) => a - b);
  });

  // --- form ---------------------------------------------------------

  protected readonly varFullName = '{{full_name}}';
  protected readonly varPhone = '{{phone}}';
  protected readonly templatePlaceholder =
    'Hi {{full_name}} — our Diwali sale is live! 20% off everything this week.';

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
    // Free-text body — required ONLY when no template is selected for
    // a WA campaign, OR for any non-WA channel. The submit handler
    // does the conditional check rather than dynamic Validators.
    template: this.fb.control<string>('', {
      nonNullable: true,
      validators: [Validators.maxLength(4096)],
    }),
    schedule_at: this.fb.control<string | null>(null),
  });

  protected readonly isWhatsApp = computed(() =>
    // computed reads channel via valueChanges — track manually
    false,
  );

  constructor() {
    // Load templates whenever the channel flips to WhatsApp. Single
    // shot — once cached we don't re-fetch on every channel toggle.
    this.form.controls.channel.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((channel) => {
        if (channel === 'whatsapp' && !this.templatesLoaded()) {
          this._loadTemplates();
        }
      });

    // Initial load — default channel is whatsapp.
    if (this.form.controls.channel.value === 'whatsapp') {
      this._loadTemplates();
    }

    // Load saved groups once for the audience builder dropdown.
    this._loadGroups();

    // Audience-size preview — debounced, runs on mode/filter/group changes.
    this.audiencePreview$
      .pipe(
        debounceTime(300),
        switchMap(() => this._currentAudiencePreviewObservable()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((count) => {
        this.audienceCount.set(count);
        this.audienceCountLoading.set(false);
      });

    // Recompute audience preview whenever any of the audience inputs
    // change. The mode signal + filter form controls all feed in.
    effect(() => {
      // tracks audienceMode + selectedGroupId
      this.audienceMode();
      this.selectedGroupId();
      this.audiencePreview$.next();
    });
    this.form.controls.audience_q.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());
    this.form.controls.audience_source.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());
    this.form.controls.audience_tag.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.audiencePreview$.next());

    // Reset variable bindings whenever the selected template changes
    // — pre-fill each `{{n}}` with an empty static binding.
    effect(() => {
      const nums = this.templateVariableNumbers();
      if (this.selectedTemplate() === null) {
        this.variables.set({});
        return;
      }
      const next: Record<string, TemplateVariableBinding> = {};
      for (const n of nums) {
        next[String(n)] = { kind: 'static', value: '' };
      }
      this.variables.set(next);
    });
  }

  protected isWhatsAppChannel(): boolean {
    return this.form.controls.channel.value === 'whatsapp';
  }

  protected onAudienceModeChange(mode: 'everyone' | 'group' | 'filter'): void {
    this.audienceMode.set(mode);
    if (mode !== 'group') {
      this.selectedGroupId.set(null);
    }
    if (mode !== 'filter') {
      this.form.patchValue({
        audience_q: null,
        audience_source: null,
        audience_tag: null,
      });
    }
  }

  protected onSelectedGroupChange(groupId: string): void {
    this.selectedGroupId.set(groupId || null);
  }

  private _loadGroups(): void {
    this.groupsApi
      .list(1, 100)
      .pipe(
        catchError(() => of({ items: [], total: 0, page: 1, size: 0 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((response) => {
        this.groups.set(response.items);
        this.groupsLoaded.set(true);
      });
  }

  private _currentAudiencePreviewObservable() {
    const mode = this.audienceMode();
    if (mode === 'everyone') {
      // "Everyone" = empty filter. The preview-size endpoint rejects
      // both-empty payloads, so we skip the call and show null.
      this.audienceCountLoading.set(false);
      return of(null);
    }
    if (mode === 'group') {
      const gid = this.selectedGroupId();
      if (!gid) {
        this.audienceCountLoading.set(false);
        return of(null);
      }
      this.audienceCountLoading.set(true);
      return this.groupsApi
        .previewSize({ group_id: gid })
        .pipe(
          switchMap((r) => of(r.count)),
          catchError(() => of(null)),
        );
    }
    // filter mode — call shape uses `GroupFilter` (the
    // preview-size endpoint is owned by the groups API and only
    // accepts q/source/tag; `group_id` belongs to the campaign-side
    // AudienceFilter shape, not the preview request).
    const filter: GroupFilter = {};
    const v = this.form.getRawValue();
    if (v.audience_q?.trim()) filter.q = v.audience_q.trim();
    if (v.audience_source?.trim()) filter.source = v.audience_source.trim();
    if (v.audience_tag?.trim()) filter.tag = v.audience_tag.trim();
    if (!filter.q && !filter.source && !filter.tag) {
      this.audienceCountLoading.set(false);
      return of(null);
    }
    this.audienceCountLoading.set(true);
    return this.groupsApi
      .previewSize({ filter_json: filter })
      .pipe(
        switchMap((r) => of(r.count)),
        catchError(() => of(null)),
      );
  }

  protected onTemplateChange(templateId: string): void {
    this.selectedTemplateId.set(templateId || null);
  }

  protected onVariableKindChange(varNum: number, kind: 'static' | 'field'): void {
    const current = this.variables();
    const key = String(varNum);
    const existing = current[key] ?? { kind: 'static', value: '' };
    this.variables.set({
      ...current,
      [key]: {
        kind,
        // Switching mode clears the value so the operator picks fresh.
        value: existing.kind === kind ? existing.value : '',
      },
    });
  }

  protected onVariableValueChange(varNum: number, value: string): void {
    const current = this.variables();
    const key = String(varNum);
    const existing = current[key] ?? { kind: 'static', value: '' };
    this.variables.set({
      ...current,
      [key]: { kind: existing.kind, value },
    });
  }

  private _loadTemplates(): void {
    this.templatesLoading.set(true);
    this.integrationsApi
      .listWhatsAppTemplates({ status: 'APPROVED' })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (rows) => {
          this.templates.set(rows);
          this.templatesLoaded.set(true);
          this.templatesLoading.set(false);
        },
        error: () => {
          this.templatesLoading.set(false);
          // Don't block the modal on template load failure — operator
          // can still use the free-text fallback.
        },
      });
  }

  protected save(): void {
    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    // Audience serialization is mode-driven (Step 3.5.9):
    //   - everyone → empty object (backend interprets as "all contacts")
    //   - group    → { group_id }
    //   - filter   → { q?, source?, tag? } (only fields with values)
    // Mixing modes is impossible by construction here, and the
    // backend's AudienceFilter validator double-checks.
    const audience: AudienceFilter = {};
    const mode = this.audienceMode();
    if (mode === 'group') {
      const gid = this.selectedGroupId();
      if (!gid) {
        this.submitError.set(
          'Pick a saved group, or switch to a different audience mode.',
        );
        return;
      }
      audience.group_id = gid;
    } else if (mode === 'filter') {
      if (v.audience_q?.trim()) audience.q = v.audience_q.trim();
      if (v.audience_source?.trim()) audience.source = v.audience_source.trim();
      if (v.audience_tag?.trim()) audience.tag = v.audience_tag.trim();
    }
    // 'everyone' mode leaves `audience` as {} — backend treats as
    // "all org contacts" (already the existing default behaviour).

    // Decide template vs template_id mode.
    const useTemplatePicker =
      v.channel === 'whatsapp' && this.selectedTemplateId() !== null;

    if (useTemplatePicker) {
      // Validate every variable has a non-empty value.
      const bindings = this.variables();
      for (const n of this.templateVariableNumbers()) {
        const b = bindings[String(n)];
        if (!b || !b.value.trim()) {
          this.submitError.set(
            `Fill in a value for variable {{${n}}}.`,
          );
          return;
        }
      }
    } else if (!v.template.trim()) {
      this.submitError.set(
        'Provide a message body or pick a WhatsApp template.',
      );
      return;
    }

    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .create({
        name: v.name,
        channel: v.channel,
        audience_filter: audience,
        template: useTemplatePicker ? null : v.template,
        template_id: useTemplatePicker ? this.selectedTemplateId() : null,
        template_variables: useTemplatePicker ? this.variables() : null,
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
