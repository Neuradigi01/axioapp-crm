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
import { SendFromPickerComponent } from '../whatsapp/shared/send-from-picker.component';
import { AbTestSectionComponent } from './ab/ab-test-section.component';
import { extractApiError } from '@core/services/api-error.util';
import {
  ContactGroup,
  ContactGroupsApiService,
  GroupFilter,
} from '../contacts/groups/groups-api.service';
import {
  IntegrationsApiService,
  WhatsAppCapacity,
} from '../settings/integrations/integrations-api.service';
import {
  AudienceFilter,
  Campaign,
  CampaignsApiService,
  TemplateVariableBinding,
} from './campaigns-api.service';
import {
  TemplateCategory,
  TemplateChannel,
  TemplateExternalStatus,
  TemplateListQuery,
  TemplateRead,
  TemplatesApiService,
} from '../templates/templates-api.service';
import { TemplateStatusBadgeComponent } from '../templates/template-status-badge.component';

/**
 * Step 15 — local picker row. Both the WhatsApp and non-WhatsApp
 * branches feed into this shape so the rest of the modal compiles
 * unchanged after the central-library swap. Body lives on `body`
 * (mapped from the central row's ``body_text``); WA's ``{{n}}``
 * positional placeholders are detected from this same field.
 *
 * Campaigns v1 Step 01 — carry `category`, `language`, and
 * `externalStatus` so the picker can render badges + a subtitle line
 * and disable non-approved WA rows without another lookup.
 */
interface PickerRow {
  id: string;
  name: string;
  body: string;
  channel: ConversationChannel;
  subject: string | null;
  category: TemplateCategory;
  language: string;
  externalStatus: TemplateExternalStatus;
  /** Campaigns v1 Step 02 — Meta's rejection text on WhatsApp rows,
   *  fed into the status badge's hover tooltip so the operator sees
   *  why a template can't be selected without leaving the CRM. */
  externalRejectionReason: string | null;
}

function toPickerRow(row: TemplateRead): PickerRow {
  return {
    id: row.id,
    name: row.name,
    body: row.body_text,
    channel: row.channel as ConversationChannel,
    subject: row.subject,
    category: row.category,
    language: row.language,
    externalStatus: row.external_status,
    externalRejectionReason: row.external_rejection_reason,
  };
}

const CATEGORY_LABEL: Record<TemplateCategory, string> = {
  marketing: 'Marketing',
  transactional: 'Transactional',
  service: 'Service',
};

/** Step 15 — the campaign channel set includes ``'web'`` for the
 *  embedded web widget; the central template library doesn't carry
 *  web templates. The `_loadTemplates` path short-circuits for any
 *  channel not in this set, leaving the operator with the free-text
 *  fallback. Push templates exist in the library (Step 13) but
 *  aren't a campaign channel yet; they re-enter this set when push
 *  send transport ships. */
const _TEMPLATE_CHANNELS: ReadonlySet<ConversationChannel> = new Set<ConversationChannel>([
  'whatsapp',
  'email',
  'sms',
  'facebook',
  'instagram',
]);

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
  imports: [
    ReactiveFormsModule,
    RouterLink,
    LucideAngularModule,
    SendFromPickerComponent,
    AbTestSectionComponent,
    TemplateStatusBadgeComponent,
  ],
  templateUrl: './create-campaign-modal.component.html',
})
export class CreateCampaignModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CampaignsApiService);
  private readonly integrationsApi = inject(IntegrationsApiService);
  private readonly templatesApi = inject(TemplatesApiService);
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
  protected readonly audienceMode = signal<'everyone' | 'group' | 'filter'>('everyone');
  protected readonly groups = signal<ContactGroup[]>([]);
  protected readonly groupsLoaded = signal(false);
  protected readonly selectedGroupId = signal<string | null>(null);

  protected readonly audienceCount = signal<number | null>(null);
  protected readonly audienceCountLoading = signal(false);
  private readonly audiencePreview$ = new Subject<void>();

  // --- WhatsApp send capacity state (Step 3.5.16) --------------------

  /** Signal mirror of `form.controls.channel.value` so the capacity-
   *  warning `computed()` blocks below react to channel changes
   *  (form controls aren't signals on their own). Synced via the
   *  valueChanges subscription in the constructor. */
  protected readonly channelSignal = signal<ConversationChannel>('whatsapp');

  /** `null` = not yet loaded or WhatsApp not connected (409). The
   *  banner is hidden in both cases — the user sees no error, and
   *  the existing "no approved templates" empty state already
   *  signals the disconnected branch. */
  protected readonly capacity = signal<WhatsAppCapacity | null>(null);
  protected readonly capacityLoading = signal(false);

  // --- Central template picker state (Step 15) ---------------------

  /** Templates available for the currently-selected channel. Loaded
   *  from the central library — `GET /api/v1/templates?channel=…
   *  &internal_status=published(&external_status=approved for WA)`.
   *  Replaces the legacy WA-only integrations endpoint. */
  protected readonly templates = signal<PickerRow[]>([]);

  /** Per-channel cache so toggling channels doesn't refetch. Cleared
   *  only if the modal is re-mounted. */
  private readonly templatesCache = new Map<ConversationChannel, PickerRow[]>();

  /** Slim id+name projection for the A/B section's template dropdowns.
   *  WhatsApp: only offer approved templates. Since Step 01 broadened
   *  the picker query to include pending/rejected rows (so users see
   *  status inline), the A/B dropdowns must re-filter — the server
   *  would reject a pending/rejected variant anyway. */
  protected approvedTemplatesForPicker(): Array<{
    id: string;
    name: string;
  }> {
    return this.templates()
      .filter((t) => (t.channel === 'whatsapp' ? t.externalStatus === 'approved' : true))
      .map((t) => ({ id: t.id, name: t.name }));
  }

  /** WA picker row is selectable only when Meta has approved it.
   *  Non-WA channels have no external review — every published row
   *  is selectable. */
  protected isRowSelectable(row: PickerRow): boolean {
    if (row.channel !== 'whatsapp') return true;
    return row.externalStatus === 'approved';
  }

  /** Subtitle line under the template name: `Category · lang · body preview`.
   *  Body clipped to ~80 chars so long templates don't blow the row height. */
  protected rowSubtitle(row: PickerRow): string {
    const category = CATEGORY_LABEL[row.category] ?? row.category;
    const preview = (row.body ?? '').replace(/\s+/g, ' ').trim();
    const clipped = preview.length > 80 ? preview.slice(0, 77) + '…' : preview;
    const language = row.language || '—';
    return clipped ? `${category} · ${language} · ${clipped}` : `${category} · ${language}`;
  }

  /** Click handler for a picker row. Non-selectable rows (pending /
   *  rejected WA) are a hard no-op — no selection change, no error. */
  protected onRowClick(row: PickerRow): void {
    if (!this.isRowSelectable(row)) return;
    this.selectedTemplateId.set(row.id);
  }
  protected readonly templatesLoading = signal(false);
  protected readonly templatesLoaded = signal(false);
  protected readonly selectedTemplateId = signal<string | null>(null);
  /** Variable bindings per `{{n}}`. Key is the variable number as
   *  string ('1','2',...) to match backend's JSONB shape. Only
   *  populated for WhatsApp templates (Meta's positional HSM shape).
   *  Other channels use named `{{contact.first_name}}` variables that
   *  the dispatcher resolves per-contact at send time — no operator
   *  bindings to capture. */
  protected readonly variables = signal<Record<string, TemplateVariableBinding>>({});

  protected readonly contactFieldOptions: ReadonlyArray<{
    value: string;
    label: string;
  }> = [
    { value: 'full_name', label: 'Contact full name' },
    { value: 'phone', label: 'Contact phone' },
    { value: 'email', label: 'Contact email' },
  ];

  protected readonly selectedTemplate = computed<PickerRow | null>(
    () => this.templates().find((t) => t.id === this.selectedTemplateId()) ?? null,
  );

  protected readonly templateVariableNumbers = computed<number[]>(() => {
    const t = this.selectedTemplate();
    if (!t) return [];
    // Match the backend's _VARIABLE_RE — distinct, sorted. Empty for
    // non-WA templates (they use named variables, not positional).
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
    // Step 27b — multi-number Send-From selector. Null = use org
    // default. The dropdown self-hides when the org has < 2
    // connected phones (the SendFromPickerComponent enforces that
    // at render time).
    send_from_phone_id: this.fb.control<string | null>(null),
    // Step 29 — A/B testing knobs. `is_ab_test` is the master
    // gate; the section component reads the other four fields.
    is_ab_test: this.fb.control<boolean>(false, { nonNullable: true }),
    variant_a_template_id: this.fb.control<string | null>(null),
    variant_b_template_id: this.fb.control<string | null>(null),
    split_ratio: this.fb.control<number>(50, { nonNullable: true }),
    winner_metric: this.fb.control<'reply_rate' | 'read_rate' | 'click_rate' | null>(null),
    winner_holdback_hours: this.fb.control<number>(24, {
      nonNullable: true,
    }),
  });

  protected readonly isWhatsApp = computed(
    () =>
      // computed reads channel via valueChanges — track manually
      false,
  );

  constructor() {
    // Step 15 — load templates whenever the channel changes. Each
    // channel's published templates come from the central library;
    // the picker reset clears any stale selection from the prior
    // channel so the operator doesn't accidentally submit an
    // out-of-channel template_id.
    this.form.controls.channel.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((channel) => {
        this.channelSignal.set(channel);
        this.selectedTemplateId.set(null);
        this._loadTemplates(channel);
        if (channel === 'whatsapp' && this.capacity() === null) {
          this._loadCapacity();
        }
      });

    // Initial load — default channel is whatsapp.
    this._loadTemplates(this.form.controls.channel.value);
    if (this.form.controls.channel.value === 'whatsapp') {
      this._loadCapacity();
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
      return this.groupsApi.previewSize({ group_id: gid }).pipe(
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
    return this.groupsApi.previewSize({ filter_json: filter }).pipe(
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

  /** Step 15 — channel-aware central-library load. Campaigns v1 Step 01
   *  broadened the WhatsApp query: instead of pre-filtering to
   *  `external_status=approved`, we now fetch every published WA
   *  template (approved, pending, rejected) so the picker can show
   *  status + rejection reason inline and the operator understands
   *  why a template can't be selected. Non-approved rows render
   *  disabled — see `isRowSelectable`. */
  private _loadTemplates(channel: ConversationChannel): void {
    const cached = this.templatesCache.get(channel);
    if (cached) {
      this.templates.set(cached);
      this.templatesLoaded.set(true);
      this.templatesLoading.set(false);
      return;
    }
    this.templatesLoading.set(true);
    this.templatesLoaded.set(false);
    this.templates.set([]);
    // The campaign channel set includes 'web' for the widget; the
    // central library doesn't carry web templates (push covers that
    // surface — Step 13). For 'web' the picker just returns no rows,
    // and the operator falls through to the free-text body.
    if (!_TEMPLATE_CHANNELS.has(channel)) {
      this.templatesLoading.set(false);
      this.templatesLoaded.set(true);
      this.templates.set([]);
      return;
    }
    const filter: TemplateListQuery = {
      channel: channel as TemplateChannel,
      internal_status: 'published',
      limit: 200,
    };
    this.templatesApi
      .list(filter)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (res) => {
          const rows: PickerRow[] = res.items.map((row) => toPickerRow(row));
          this.templatesCache.set(channel, rows);
          this.templates.set(rows);
          this.templatesLoaded.set(true);
          this.templatesLoading.set(false);
        },
        error: () => {
          this.templatesLoading.set(false);
          this.templatesLoaded.set(true);
          this.templates.set([]);
          // Don't block the modal on template load failure — operator
          // can still use the free-text fallback.
        },
      });
  }

  private _loadCapacity(): void {
    this.capacityLoading.set(true);
    this.integrationsApi
      .getWhatsAppCapacity()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (c) => {
          this.capacity.set(c);
          this.capacityLoading.set(false);
        },
        error: () => {
          // 409 (WhatsApp not connected) and any transient error fall
          // through to the same null state — the banner stays hidden
          // and the existing "no templates" empty state already tells
          // the operator to connect WhatsApp.
          this.capacity.set(null);
          this.capacityLoading.set(false);
        },
      });
  }

  /** Refresh the capacity banner — bound to the banner's "Refresh"
   *  button. Re-fetches even when the previous load succeeded. */
  protected refreshCapacity(): void {
    this._loadCapacity();
  }

  /** Coloured-band hint for the banner. `null` when capacity isn't
   *  loaded yet or WhatsApp isn't connected. */
  protected readonly capacityBand = computed<'green' | 'amber' | 'red' | null>(() => {
    const c = this.capacity();
    if (!c || c.is_unlimited) return null;
    if (c.usage_percent >= 90) return 'red';
    if (c.usage_percent >= 70) return 'amber';
    return 'green';
  });

  /** Banner severity for the audience-vs-quota cross-check. `error`
   *  when the selected audience exceeds remaining quota; `warning`
   *  when it would consume >50% of remaining. `null` otherwise. */
  protected readonly audienceQuotaWarning = computed<{
    kind: 'error' | 'warning';
    message: string;
  } | null>(() => {
    const c = this.capacity();
    if (!c || c.is_unlimited) return null;
    if (this.channelSignal() !== 'whatsapp') return null;
    const count = this.audienceCount();
    if (count === null || count <= 0) return null;
    if (count > c.remaining) {
      const skipped = count - c.remaining;
      return {
        kind: 'error',
        message: `${count.toLocaleString()} contacts selected, but only ${c.remaining.toLocaleString()} sends remaining today. ${skipped.toLocaleString()} will be skipped or queue for tomorrow.`,
      };
    }
    if (c.remaining > 0 && count > c.remaining * 0.5) {
      const pct = Math.round((count / c.remaining) * 100);
      return {
        kind: 'warning',
        message: `This campaign will use ${pct}% of today's remaining quota.`,
      };
    }
    return null;
  });

  /** Send button gate — disables the submit when WhatsApp quota is
   *  exhausted. Non-WhatsApp channels are never gated. */
  protected readonly quotaBlocksSubmit = computed<boolean>(() => {
    const c = this.capacity();
    if (!c) return false;
    if (c.is_unlimited) return false;
    if (this.channelSignal() !== 'whatsapp') return false;
    return c.remaining === 0;
  });

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
        this.submitError.set('Pick a saved group, or switch to a different audience mode.');
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

    // Step 15 — decide template vs template_id mode. Any channel with
    // a selected template_id sends through the central library; the
    // free-text fallback fires only when no template is picked.
    const useTemplatePicker = this.selectedTemplateId() !== null;

    if (useTemplatePicker) {
      // WA's positional `{{n}}` placeholders require operator-supplied
      // bindings before the dispatcher can render per-contact. Named
      // variables on other channels resolve automatically from the
      // contact row — no bindings to validate.
      const bindings = this.variables();
      for (const n of this.templateVariableNumbers()) {
        const b = bindings[String(n)];
        if (!b || !b.value.trim()) {
          this.submitError.set(`Fill in a value for variable {{${n}}}.`);
          return;
        }
      }
    } else if (!v.template.trim()) {
      this.submitError.set('Provide a message body or pick a template.');
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
        schedule_at: v.schedule_at ? new Date(v.schedule_at).toISOString() : null,
        // Step 27b — null on single-number orgs (picker hidden);
        // when set, the dispatcher pins the campaign to this
        // specific WhatsApp phone instead of the org default.
        send_from_phone_id: v.send_from_phone_id ?? null,
        // Step 29 — A/B test config. Server defaults take over
        // when is_ab_test is false; the variant pair + metric are
        // required otherwise (server validates).
        is_ab_test: v.is_ab_test ?? false,
        variant_a_template_id: v.is_ab_test ? (v.variant_a_template_id ?? null) : null,
        variant_b_template_id: v.is_ab_test ? (v.variant_b_template_id ?? null) : null,
        split_ratio: v.split_ratio ?? 50,
        winner_metric: v.is_ab_test ? (v.winner_metric ?? null) : null,
        winner_holdback_hours: v.winner_holdback_hours ?? 24,
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (campaign) => {
          this.submitting.set(false);
          this.created.emit(campaign);
        },
        error: (err: HttpErrorResponse) => {
          this.submitting.set(false);
          this.submitError.set(extractApiError(err) ?? 'Could not create campaign.');
        },
      });
  }

  protected close(): void {
    this.cancel.emit();
  }
}
