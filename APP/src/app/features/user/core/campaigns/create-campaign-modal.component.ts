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
import { FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { LucideAngularModule } from 'lucide-angular';
import { EMPTY, Subject, of } from 'rxjs';
import { catchError, debounceTime, switchMap } from 'rxjs/operators';

import { ConversationChannel } from '../conversations/conversations-api.service';
import { SendFromPickerComponent } from '../whatsapp/shared/send-from-picker.component';
import { AbTestSectionComponent } from './ab/ab-test-section.component';
import { extractApiError } from '@core/services/api-error.util';
import { ContactGroup, ContactGroupsApiService } from '../contacts/groups/groups-api.service';
import { ContactListItem, ContactsApiService } from '../contacts/contacts-api.service';
import { PipelineStage, PipelinesApiService } from '../pipelines/pipelines-api.service';
import {
  IntegrationsApiService,
  WhatsAppCapacity,
} from '../settings/integrations/integrations-api.service';
import {
  EmailSendersApiService,
  UnifiedSender,
} from '../settings/integrations/email-senders-api.service';
import { OrgSettings, SettingsApiService } from '../settings/settings-api.service';
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
import { FieldErrorComponent } from '../shared/forms/field-error.component';
import { MobileSelectComponent, MobileSelectOption } from '../shared/forms/mobile-select.component';
import { MobileDateTimeComponent } from '../shared/forms/mobile-datetime.component';

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
 * Templates-only: the operator picks a published template from the
 * central library. WhatsApp positional `{{n}}` placeholders each get
 * a static/contact-field binding; other channels resolve named
 * `{{contact.first_name}}` variables per-recipient at dispatch time.
 *
 * The modal is split into three sequential steps so the form isn't
 * one long scroll: **Basics** (name, channel, audience), **Content**
 * (email sender identity + template picker + bindings), and **Send**
 * (schedule, WA send-from, A/B toggle).
 */
@Component({
  selector: 'app-create-campaign-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    FormsModule,
    RouterLink,
    LucideAngularModule,
    SendFromPickerComponent,
    AbTestSectionComponent,
    TemplateStatusBadgeComponent,
    MobileSelectComponent,
    MobileDateTimeComponent,
    FieldErrorComponent,
  ],
  templateUrl: './create-campaign-modal.component.html',
})
export class CreateCampaignModalComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(CampaignsApiService);
  private readonly integrationsApi = inject(IntegrationsApiService);
  private readonly templatesApi = inject(TemplatesApiService);
  private readonly groupsApi = inject(ContactGroupsApiService);
  private readonly contactsApi = inject(ContactsApiService);
  private readonly pipelinesApi = inject(PipelinesApiService);
  private readonly emailSendersApi = inject(EmailSendersApiService);
  private readonly settingsApi = inject(SettingsApiService);
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

  /** Live preview of the paged contacts matching the current
   *  Custom-filter inputs. Populated only in filter mode so the
   *  operator can visually confirm who they're targeting before
   *  scheduling. Grows by ``AUDIENCE_PREVIEW_LIMIT`` each time the
   *  operator clicks "Load more" — earlier pages stay in the list so
   *  their tick-boxes aren't lost when scrolling. */
  protected readonly audiencePreviewRows = signal<ContactListItem[]>([]);
  protected readonly audiencePreviewLoading = signal(false);
  protected readonly audiencePreviewLoadingMore = signal(false);
  /** Preview page size — number of contacts fetched per round-trip.
   *  Small enough that the list stays scannable, large enough that
   *  "Load more" doesn't feel like a poll. */
  private readonly AUDIENCE_PREVIEW_LIMIT = 25;
  /** Current preview page (1-based). Reset to 1 on any filter change;
   *  incremented by ``loadMoreAudience`` and appended to the row list. */
  protected readonly audiencePreviewPage = signal<number>(1);

  /** Pipeline stages for the lead-stage dropdown, loaded lazily the
   *  first time the operator opens Custom-filter mode. Empty until
   *  the fetch resolves. */
  protected readonly pipelineStages = signal<PipelineStage[]>([]);
  private pipelineStagesLoaded = false;

  protected readonly pipelineStageOptions = computed<MobileSelectOption[]>(() =>
    [...this.pipelineStages()]
      .sort((a, b) => a.display_order - b.display_order)
      .map((s) => ({ value: s.key, label: s.name })),
  );

  /** Hard-coded lists that mirror the backend Lead enums — kept in
   *  lock-step with ``core.leads.models.LeadStatus`` / ``LeadSource``. */
  protected readonly leadStatusOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'active', label: 'Active' },
    { value: 'won', label: 'Won' },
    { value: 'lost', label: 'Lost' },
  ];
  protected readonly leadSourceOptions: ReadonlyArray<MobileSelectOption> = [
    { value: 'manual', label: 'Manual' },
    { value: 'bulk_import', label: 'Bulk import' },
    // Multi-form track: the `widget` enum stays canonical on the
    // backend, but every UI surface renders it as "Forms" — the source
    // bucket now stands for "any form-sourced lead", regardless of
    // which specific form the visitor submitted to.
    { value: 'widget', label: 'Forms' },
    { value: 'google_ads', label: 'Google Ads' },
    { value: 'meta_ads', label: 'Meta Ads' },
    { value: 'whatsapp_flow', label: 'WhatsApp flow' },
    { value: 'walk_in', label: 'Walk-in' },
  ];

  /** Multi-select selections for the lead-linked dropdowns. Empty
   *  array = no filter on that facet. Backed by chip UI in the
   *  template. */
  protected readonly leadStatusFilter = signal<string[]>([]);
  protected readonly leadStageFilter = signal<string[]>([]);
  protected readonly leadSourceFilter = signal<string[]>([]);

  protected toggleLeadStatus(value: string): void {
    this.leadStatusFilter.update((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
    this.audiencePreview$.next();
  }
  protected toggleLeadStage(value: string): void {
    this.leadStageFilter.update((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
    this.audiencePreview$.next();
  }
  protected toggleLeadSource(value: string): void {
    this.leadSourceFilter.update((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value],
    );
    this.audiencePreview$.next();
  }

  protected leadStatusLabel(value: string): string {
    return this.leadStatusOptions.find((o) => o.value === value)?.label ?? value;
  }
  protected leadStageLabel(value: string): string {
    return this.pipelineStageOptions().find((o) => o.value === value)?.label ?? value;
  }
  protected leadSourceLabel(value: string): string {
    return this.leadSourceOptions.find((o) => o.value === value)?.label ?? value;
  }

  protected onAddLeadStatus(value: string | null): void {
    if (value && !this.leadStatusFilter().includes(value)) {
      this.leadStatusFilter.update((prev) => [...prev, value]);
      this.audiencePreview$.next();
    }
  }
  protected onAddLeadStage(value: string | null): void {
    if (value && !this.leadStageFilter().includes(value)) {
      this.leadStageFilter.update((prev) => [...prev, value]);
      this.audiencePreview$.next();
    }
  }
  protected onAddLeadSource(value: string | null): void {
    if (value && !this.leadSourceFilter().includes(value)) {
      this.leadSourceFilter.update((prev) => [...prev, value]);
      this.audiencePreview$.next();
    }
  }

  /** Collapsed state for the Matching-contacts panel. Once the
   *  operator has finished picking contacts they can click "Hide" to
   *  free up vertical space — the selected chip strip stays visible
   *  so the choice is still obvious. Manual-only toggle: typing a
   *  new search doesn't force it back open, mirroring the shopping-
   *  cart pattern (checkout continues to work with the drawer closed). */
  protected readonly audiencePreviewCollapsed = signal(false);

  protected toggleAudiencePreviewCollapsed(): void {
    this.audiencePreviewCollapsed.update((v) => !v);
  }

  /** Contacts the operator has hand-picked from the preview list.
   *  Stored as a Map (id → ContactListItem) so the chip strip can
   *  render each picked contact's name even after the preview
   *  refreshes with a different search. Non-empty = the campaign is
   *  scoped to exactly these ids at save time (overrides q/source/tag).
   *  Empty = "use the filter as-is", i.e. dynamic resolution at
   *  dispatch. */
  protected readonly selectedContactMap = signal<Map<string, ContactListItem>>(new Map());

  /** Derived: array view of the selection for template iteration. */
  protected readonly selectedContactList = computed<ContactListItem[]>(() =>
    Array.from(this.selectedContactMap().values()),
  );

  protected isContactSelected(id: string): boolean {
    return this.selectedContactMap().has(id);
  }

  protected toggleContactSelected(c: ContactListItem): void {
    const next = new Map(this.selectedContactMap());
    if (next.has(c.id)) next.delete(c.id);
    else next.set(c.id, c);
    this.selectedContactMap.set(next);
  }

  protected removeSelectedContact(id: string): void {
    const next = new Map(this.selectedContactMap());
    next.delete(id);
    this.selectedContactMap.set(next);
  }

  protected selectAllShown(): void {
    const next = new Map(this.selectedContactMap());
    for (const c of this.audiencePreviewRows()) next.set(c.id, c);
    this.selectedContactMap.set(next);
  }

  protected clearSelection(): void {
    this.selectedContactMap.set(new Map());
  }

  // --- WhatsApp send capacity state (Step 3.5.16) --------------------

  /** Signal mirror of `form.controls.channel.value` so the capacity-
   *  warning `computed()` blocks below react to channel changes
   *  (form controls aren't signals on their own). Synced via the
   *  valueChanges subscription in the constructor. */
  protected readonly channelSignal = signal<ConversationChannel | null>(null);

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
   *  rejected WA) are a hard no-op — no selection change, no error.
   *  Clicking the currently-selected template toggles it off so the
   *  operator can back out to "no template" and edit the body inline
   *  without having to pick a different one first. */
  protected onRowClick(row: PickerRow): void {
    if (!this.isRowSelectable(row)) return;
    if (this.selectedTemplateId() === row.id) {
      this.selectedTemplateId.set(null);
      return;
    }
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

  // --- Campaigns v1 Step 03 — Email sender identity state -----------

  /** Verified sender identities the org can dispatch through — a merged
   *  list of live OAuth mailboxes (`kind: 'gmail' | 'microsoft'`) AND
   *  verified SMTP senders (`kind: 'smtp'`, migration 0213). Fetched
   *  lazily the first time the channel switches to Email so WhatsApp-
   *  only orgs never pay the roundtrip. `null` = not fetched yet;
   *  `[]` = fetched and org has zero verified senders of either kind
   *  (drives the empty-state banner in the template). Only rows with
   *  `verified === true` are kept — pending SMTP senders and OAuth
   *  mailboxes with dead refresh tokens are filtered out. */
  protected readonly emailAccounts = signal<UnifiedSender[] | null>(null);
  protected readonly emailAccountsLoading = signal(false);

  /** Campaigns v1 Step 07c — proactive CAN-SPAM check. Populated on
   *  first Email-channel flip; ``false`` here means the operator hasn't
   *  set Store Profile → address_line1, which will hard-block Start.
   *  Rendered as a red banner with a link to Settings → Store Profile
   *  so they can fix it without reading a raw 400 later. */
  protected readonly orgSettings = signal<OrgSettings | null>(null);
  protected readonly orgSettingsLoading = signal(false);
  protected readonly orgAddressMissing = computed<boolean>(() => {
    const s = this.orgSettings();
    if (s === null) return false; // unknown → don't scare the user
    return !(s.address_line1 && s.address_line1.trim().length > 0);
  });

  /** Merge tags the operator can insert into the Subject line via the
   *  "Insert variable ▾" affordance. Named-variable syntax matching the
   *  dispatcher's per-contact resolution path. */
  protected readonly subjectMergeTags: ReadonlyArray<{ value: string; label: string }> = [
    { value: '{{first_name}}', label: 'First name' },
    { value: '{{full_name}}', label: 'Full name' },
    { value: '{{email}}', label: 'Email' },
  ];
  /** Bound as a component property because Angular's template parser
   *  would otherwise mis-interpret the ``{{`` in the placeholder as a
   *  binding expression. */
  protected readonly subjectPlaceholder = 'Your monthly deals, {{first_name}} 🎁';

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

  // --- stepper ------------------------------------------------------

  /** Labels shown in the horizontal step indicator at the top of the
   *  modal. Kept as a template constant so the template can `@for` and
   *  the ordinal (1/2/3) drives both display and routing. */
  protected readonly steps: ReadonlyArray<{ n: 1 | 2 | 3; label: string }> = [
    { n: 1, label: 'Basics' },
    { n: 2, label: 'Content' },
    { n: 3, label: 'Send' },
  ];

  /** Which of the three panels is visible. Advancement is gated by
   *  ``step1Complete`` / ``step2Complete`` so operators can't skip
   *  past required fields. Back-navigation is always allowed. */
  protected readonly step = signal<1 | 2 | 3>(1);

  /** True when the current step is reachable — used by the stepper
   *  header buttons to enable/disable the crumb click target. */
  protected stepReachable(target: 1 | 2 | 3): boolean {
    if (target <= this.step()) return true;
    if (target === 2) return this.step1Complete();
    return this.step1Complete() && this.step2Complete();
  }

  /** Signal-visible mirror of the fields step 1 requires. The form
   *  controls themselves aren't signals; without this bridge the
   *  ``canAdvance`` computed wouldn't invalidate on keystrokes. */
  protected readonly nameValue = signal<string>('');

  /** Step 1 (Basics) is complete when the campaign has a name AND the
   *  audience selection is coherent — "Everyone" is always valid, a
   *  saved group must be picked, a custom filter must include at
   *  least one condition or handpicked contact. */
  protected readonly step1Complete = computed<boolean>(() => {
    if (!this.nameValue().trim()) return false;
    // Channel must be picked explicitly — the operator has to consciously
    // choose WhatsApp or Email before the wizard advances. Prevents
    // accidental "wrong channel" submits when the trigger reads
    // "Select…" but the user click-throughs.
    if (!this.channelSignal()) return false;
    const mode = this.audienceMode();
    if (mode === 'everyone') return true;
    if (mode === 'group') return this.selectedGroupId() !== null;
    // filter mode
    if (this.selectedContactMap().size > 0) return true;
    const v = this.form.getRawValue();
    return Boolean(
      v.audience_q?.trim() ||
      v.audience_tag?.trim() ||
      this.leadStatusFilter().length > 0 ||
      this.leadStageFilter().length > 0 ||
      this.leadSourceFilter().length > 0,
    );
  });

  /** Step 2 (Content) requires a picked template plus every WA
   *  ``{{n}}`` variable filled in. Email also requires mailbox +
   *  sender name + subject (mirrors ``emailBranchIncomplete``). */
  protected readonly step2Complete = computed<boolean>(() => {
    if (this.selectedTemplateId() === null) return false;
    const bindings = this.variables();
    for (const n of this.templateVariableNumbers()) {
      const b = bindings[String(n)];
      if (!b || !b.value.trim()) return false;
    }
    if (this.isEmailChannel() && this.emailBranchIncomplete()) return false;
    return true;
  });

  protected goToStep(target: 1 | 2 | 3): void {
    // Free backwards nav. Forwards nav gated by step completeness so
    // the operator can't leap over a required field via a header click.
    if (target < this.step()) {
      this.step.set(target);
      return;
    }
    if (target === 2 && !this.step1Complete()) return;
    if (target === 3 && (!this.step1Complete() || !this.step2Complete())) return;
    this.step.set(target);
  }

  protected nextStep(): void {
    const s = this.step();
    if (s === 1 && this.step1Complete()) this.step.set(2);
    else if (s === 2 && this.step2Complete()) this.step.set(3);
  }

  protected prevStep(): void {
    const s = this.step();
    if (s === 2) this.step.set(1);
    else if (s === 3) this.step.set(2);
  }

  // --- form ---------------------------------------------------------

  /** Campaigns v1 scope locked to WhatsApp + Email (memory
   *  ``project_campaigns_scope.md``). Legacy campaigns on other
   *  channels still render on the list page; the create flow just
   *  doesn't offer them so a user can't start a broken one. */
  protected readonly channels: ReadonlyArray<{
    value: ConversationChannel;
    label: string;
  }> = [
    { value: 'whatsapp', label: 'WhatsApp' },
    { value: 'email', label: 'Email' },
  ];

  protected readonly form = this.fb.group({
    name: this.fb.control('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(255)],
    }),
    // No default — force the operator to pick a channel explicitly.
    // The trigger renders "Select…" until then, and the step-1 Next
    // button stays disabled (see `step1Complete`) so nobody advances
    // with an accidental channel choice.
    channel: this.fb.control<ConversationChannel | null>(null, {
      validators: [Validators.required],
    }),
    audience_q: this.fb.control<string | null>(null),
    audience_tag: this.fb.control<string | null>(null),
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
    // Campaigns v1 Step 03 — Email sender identity + subject + preheader.
    // Every control below is nullable so WhatsApp submits stay clean.
    // Required-when-Email is enforced in `save()` before we hit the
    // API, and the backend echoes the same check with a 422.
    email_account_id: this.fb.control<string | null>(null),
    // Migration 0213 — alternate sender identity for Email campaigns
    // that dispatch through a verified SMTP row instead of an OAuth
    // mailbox. Exactly one of email_account_id / smtp_sender_id is
    // set for Email; both null for non-Email. `_setSenderFromComposite`
    // maintains the invariant on picker changes.
    smtp_sender_id: this.fb.control<string | null>(null),
    sender_name: this.fb.control<string | null>(null, [Validators.maxLength(120)]),
    reply_to: this.fb.control<string | null>(null, [Validators.email, Validators.maxLength(320)]),
    subject: this.fb.control<string | null>(null, [Validators.maxLength(998)]),
    preheader: this.fb.control<string | null>(null, [Validators.maxLength(200)]),
  });

  constructor() {
    // Mirror the three Email-branch form fields into `emailBranchState`
    // so `emailBranchIncomplete` (a signal-computed) re-evaluates on
    // every keystroke / dropdown pick. Reactive-forms `valueChanges`
    // is what actually notifies us — the signal is just the bridge to
    // Angular signal reactivity.
    const _pushEmailBranchState = () => {
      const v = this.form.getRawValue();
      this.emailBranchState.set({
        email_account_id: v.email_account_id ?? null,
        smtp_sender_id: v.smtp_sender_id ?? null,
        sender_name: v.sender_name ?? '',
        subject: v.subject ?? '',
        reply_to: v.reply_to ?? '',
      });
    };
    this.form.controls.email_account_id.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.smtp_sender_id.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.sender_name.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.subject.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);
    this.form.controls.reply_to.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(_pushEmailBranchState);

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
        // Skip the branch-specific side-effects until the operator
        // actually picks a channel (initial state is null now).
        if (!channel) return;
        this._loadTemplates(channel);
        if (channel === 'whatsapp' && this.capacity() === null) {
          this._loadCapacity();
        }
        // Campaigns v1 Step 03 — lazy-fetch verified mailboxes the
        // first time the operator picks Email. When they switch away,
        // clear the mailbox selection so the payload never carries a
        // stale email_account_id on a WA campaign.
        if (channel === 'email') {
          if (this.emailAccounts() === null) {
            this._loadEmailAccounts();
          }
          if (this.orgSettings() === null) {
            this._loadOrgSettings();
          }
          // A/B testing + Send-From are WhatsApp-only knobs. Clear any
          // toggle the operator left on before flipping to Email so the
          // payload doesn't carry `is_ab_test: true` into an Email
          // campaign that has no variant selector rendered.
          this.form.patchValue({
            send_from_phone_id: null,
            is_ab_test: false,
            variant_a_template_id: null,
            variant_b_template_id: null,
            winner_metric: null,
          });
        } else {
          this.form.patchValue({
            email_account_id: null,
            smtp_sender_id: null,
            sender_name: null,
            reply_to: null,
            subject: null,
            preheader: null,
          });
        }
      });

    // Bridge the Name control into a signal so ``step1Complete`` re-
    // evaluates on every keystroke (form controls aren't signals).
    this.form.controls.name.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((v) => this.nameValue.set(v ?? ''));

    // No initial channel load — templates + capacity fetch lazily the
    // first time the operator picks WhatsApp or Email (see the channel
    // `valueChanges` subscription above).

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

    // Contact-row preview — same debounced trigger, populated only
    // in Custom-filter mode so the operator can eyeball the target set.
    this.audiencePreview$
      .pipe(
        debounceTime(300),
        switchMap(() => this._currentAudiencePreviewRowsObservable()),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        this.audiencePreviewRows.set(rows);
        this.audiencePreviewLoading.set(false);
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

  /** WhatsApp branch gate. Reads through ``channelSignal`` so the
   *  ``@if (isWhatsAppChannel())`` guards + capacity banner re-render
   *  the moment the operator flips the channel — matches the
   *  Email-side pattern below. */
  protected isWhatsAppChannel(): boolean {
    return this.channelSignal() === 'whatsapp';
  }

  /** Campaigns v1 Step 03 — Email branch gate for the modal's
   *  conditional field render + submit disable. Mirrors the
   *  `channel === 'email'` check but reads through channelSignal so
   *  computed()s can subscribe. */
  protected isEmailChannel(): boolean {
    return this.channelSignal() === 'email';
  }

  /** Insert a merge tag at the end of the subject value. A future
   *  polish step could preserve caret position; end-of-string is the
   *  standard fallback most builders offer. */
  protected onInsertSubjectTag(token: string): void {
    const ctrl = this.form.controls.subject;
    const current = ctrl.value ?? '';
    ctrl.setValue(current + token);
    ctrl.markAsDirty();
  }

  /** Signal mirror of the three Email-branch form fields so the
   *  `emailBranchIncomplete` computed re-evaluates when the operator
   *  types in Sender name / Subject or picks a mailbox. Without this,
   *  the computed reads `form.getRawValue()` — which isn't a signal —
   *  so Angular never invalidates the cache and Save Draft stays
   *  disabled even when every field is filled. */
  protected readonly emailBranchState = signal<{
    email_account_id: string | null;
    smtp_sender_id: string | null;
    sender_name: string;
    subject: string;
    reply_to: string;
  }>({
    email_account_id: null,
    smtp_sender_id: null,
    sender_name: '',
    subject: '',
    reply_to: '',
  });

  /** Basic email shape check for the optional Reply-to field. Kept
   *  loose on purpose — the authoritative check runs on the backend
   *  via Pydantic's `EmailStr`; this one just catches the common
   *  "typed a name instead of an email" case so the operator sees
   *  the error inline in Step 2 instead of after clicking Save on
   *  Step 3. */
  private static isPlausibleEmail(v: string): boolean {
    return /^\S+@\S+\.\S+$/.test(v);
  }

  /** True when the operator typed something into Reply-to that
   *  clearly isn't an email (missing `@` or `.`). Blocks Next on
   *  Step 2 so the backend never gets to 422 on it. */
  protected readonly replyToInvalid = computed<boolean>(() => {
    if (!this.isEmailChannel()) return false;
    const v = this.emailBranchState().reply_to.trim();
    if (!v) return false; // Empty is fine — the field is optional.
    return !CreateCampaignModalComponent.isPlausibleEmail(v);
  });

  /** True when the Email branch is missing any of its required fields
   *  OR the optional Reply-to is malformed. Drives the disabled state
   *  on Next / Save Draft so the operator can't send a payload the
   *  backend would 422. */
  protected readonly emailBranchIncomplete = computed<boolean>(() => {
    if (!this.isEmailChannel()) return false;
    const v = this.emailBranchState();
    // Exactly one of the two sender ids must be set (migration 0213).
    // The picker's `_setSenderFromComposite` maintains the invariant on
    // every change, so here we just need at least one non-empty.
    const hasSender = !!v.email_account_id || !!v.smtp_sender_id;
    if (
      !hasSender ||
      !(v.sender_name && v.sender_name.trim()) ||
      !(v.subject && v.subject.trim())
    ) {
      return true;
    }
    return this.replyToInvalid();
  });

  private _loadEmailAccounts(): void {
    this.emailAccountsLoading.set(true);
    this.emailSendersApi
      .list()
      .pipe(
        catchError(() => of<UnifiedSender[]>([])),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((rows) => {
        // Only sendable senders — verified SMTP identities and OAuth
        // mailboxes with a live refresh token. Backend already skips
        // disconnected OAuth rows from the list, but filtering here
        // is belt-and-braces and mirrors what other pickers do.
        const sendable = rows.filter((r) => r.verified);
        this.emailAccounts.set(sendable);
        this.emailAccountsLoading.set(false);
        // Auto-pick the sender when there's exactly one. Delegates to
        // the same handler as manual selection so the OAuth vs SMTP
        // form-control routing stays in one spot.
        if (sendable.length === 1 && !this.currentSenderCompositeValue()) {
          this._setSenderFromComposite(this._composeSenderValue(sendable[0]));
        }
      });
  }

  /** Compose the "kind:id" string a UnifiedSender row is identified by
   *  in the sender-picker `<select>`. Two-part key because the id
   *  alone doesn't distinguish an SMTP row from an OAuth row (two
   *  independent UUID spaces). */
  protected _composeSenderValue(sender: UnifiedSender): string {
    return `${sender.kind}:${sender.id}`;
  }

  /** Options for the shared `crm-mobile-select` — mirrors the label
   *  format used by the old native `<select>` so the picker reads the
   *  same. Derived from `emailAccounts()` so it re-evaluates when the
   *  senders list resolves. */
  protected readonly senderOptions = computed<readonly MobileSelectOption[]>(() =>
    (this.emailAccounts() ?? []).map((a) => ({
      value: this._composeSenderValue(a),
      label: `[${a.kind === 'gmail' ? 'Gmail' : a.kind === 'microsoft' ? 'Outlook' : 'SMTP'}] ${a.from_address}${a.display_name ? ' · ' + a.display_name : ''}`,
    })),
  );

  /** Read the currently-selected sender back out of the two mutually-
   *  exclusive form controls as the same "kind:id" composite the
   *  picker binds to. Returns '' when neither control is set. */
  protected currentSenderCompositeValue(): string {
    const oauth = this.form.controls.email_account_id.value;
    if (oauth) {
      const row = (this.emailAccounts() ?? []).find((r) => r.id === oauth && r.kind !== 'smtp');
      if (row) return this._composeSenderValue(row);
      // Row not (yet) loaded — best-effort default to gmail; the
      // dropdown will re-sync once the fetch resolves.
      return `gmail:${oauth}`;
    }
    const smtp = this.form.controls.smtp_sender_id.value;
    if (smtp) return `smtp:${smtp}`;
    return '';
  }

  /** Picker `<select>` change handler. Splits the "kind:id" composite
   *  and routes the id into either `email_account_id` (OAuth) or
   *  `smtp_sender_id` (SMTP), clearing the sibling so the payload
   *  never carries both — the backend rejects that with 422 via the
   *  ``_email_channel_requires_sender_and_subject`` validator. */
  protected onSenderPicked(compositeValue: string | null): void {
    this._setSenderFromComposite(compositeValue);
  }

  private _setSenderFromComposite(compositeValue: string | null): void {
    if (!compositeValue) {
      this.form.controls.email_account_id.setValue(null);
      this.form.controls.smtp_sender_id.setValue(null);
      return;
    }
    const idx = compositeValue.indexOf(':');
    const kind = idx > 0 ? compositeValue.slice(0, idx) : '';
    const id = idx > 0 ? compositeValue.slice(idx + 1) : '';
    if (!id) return;
    if (kind === 'smtp') {
      this.form.controls.email_account_id.setValue(null);
      this.form.controls.smtp_sender_id.setValue(id);
      this.form.controls.smtp_sender_id.markAsDirty();
    } else {
      this.form.controls.email_account_id.setValue(id);
      this.form.controls.smtp_sender_id.setValue(null);
      this.form.controls.email_account_id.markAsDirty();
    }
  }

  private _loadOrgSettings(): void {
    this.orgSettingsLoading.set(true);
    this.settingsApi
      .get()
      .pipe(
        catchError(() => of<OrgSettings | null>(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((row) => {
        this.orgSettings.set(row);
        this.orgSettingsLoading.set(false);
      });
  }

  protected onAudienceModeChange(mode: 'everyone' | 'group' | 'filter'): void {
    this.audienceMode.set(mode);
    if (mode !== 'group') {
      this.selectedGroupId.set(null);
    }
    if (mode !== 'filter') {
      this.form.patchValue({
        audience_q: null,
        audience_tag: null,
      });
      this.leadStatusFilter.set([]);
      this.leadStageFilter.set([]);
      this.leadSourceFilter.set([]);
      this.clearSelection();
    } else if (!this.pipelineStagesLoaded) {
      // Lazy-load leads pipeline stages the first time the operator
      // enters Custom-filter mode. The dropdown reads through
      // ``pipelineStages()`` so the render just fills in when it arrives.
      this._loadPipelineStages();
    }
  }

  private _loadPipelineStages(): void {
    this.pipelineStagesLoaded = true;
    this.pipelinesApi
      .getByKey('leads')
      .pipe(
        catchError(() => of<{ stages: PipelineStage[] } | null>(null)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((res) => {
        this.pipelineStages.set(res?.stages ?? []);
      });
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
    // filter mode — the rows observable owns the count in this mode
    // (contacts.list returns items+total in one call, so we don't need
    // a second round-trip through the groups previewSize endpoint,
    // which rejects empty filter payloads anyway). EMPTY here means
    // the count subscriber never fires and never fights the rows
    // subscriber over `audienceCount` / `audienceCountLoading`.
    return EMPTY;
  }

  /** Rows companion to the count observable. Only Custom-filter mode
   *  fetches — Everyone and Saved-group modes clear the list.
   *  Sends q/source/tag + lead_* through the contacts list endpoint
   *  and takes one page at a time. On a fresh filter change this
   *  resets the page counter to 1 and replaces the row list. Also
   *  pipes ``resp.total`` into ``audienceCount`` — one round-trip
   *  covers both the row preview and the header count, replacing the
   *  groups previewSize call in filter mode (which rejects empty
   *  filters). */
  private _currentAudiencePreviewRowsObservable() {
    const mode = this.audienceMode();
    if (mode !== 'filter') {
      this.audiencePreviewLoading.set(false);
      this.audiencePreviewPage.set(1);
      return of<ContactListItem[]>([]);
    }
    // Filter-change reset: page back to 1 and clear the accumulated
    // row list so the fresh page fully replaces the old set. Load
    // more increments the page after the fetch instead of before, so
    // page(1) is always the state that lands here from the debounced
    // filter subject.
    this.audiencePreviewPage.set(1);
    this.audiencePreviewLoading.set(true);
    this.audienceCountLoading.set(true);
    return this._fetchAudiencePage(1).pipe(
      switchMap((resp) => {
        this.audienceCount.set(resp.total);
        this.audienceCountLoading.set(false);
        return of(resp.items);
      }),
      catchError(() => {
        this.audienceCount.set(null);
        this.audienceCountLoading.set(false);
        return of<ContactListItem[]>([]);
      }),
    );
  }

  private _fetchAudiencePage(page: number) {
    const v = this.form.getRawValue();
    const q = v.audience_q?.trim() || undefined;
    const tag = v.audience_tag?.trim() || undefined;
    return this.contactsApi.list({
      q,
      tag: tag ? [tag] : undefined,
      lead_status: this.leadStatusFilter().length ? this.leadStatusFilter() : undefined,
      lead_stage: this.leadStageFilter().length ? this.leadStageFilter() : undefined,
      lead_source: this.leadSourceFilter().length ? this.leadSourceFilter() : undefined,
      page,
      size: this.AUDIENCE_PREVIEW_LIMIT,
    });
  }

  /** True when there are more contacts server-side than the preview
   *  has already rendered — drives the "Load more" button visibility. */
  protected readonly hasMoreAudience = computed<boolean>(() => {
    const total = this.audienceCount();
    if (total === null) return false;
    return this.audiencePreviewRows().length < total;
  });

  /** Fetch the next page of audience preview rows and append them to
   *  the current list. Independent of the debounced filter subject so
   *  it doesn't clobber the accumulated rows. */
  protected loadMoreAudience(): void {
    if (this.audiencePreviewLoadingMore()) return;
    if (!this.hasMoreAudience()) return;
    const nextPage = this.audiencePreviewPage() + 1;
    this.audiencePreviewLoadingMore.set(true);
    this._fetchAudiencePage(nextPage)
      .pipe(
        catchError(() => of({ items: [] as ContactListItem[], total: 0, page: nextPage, size: 0 })),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((resp) => {
        this.audiencePreviewRows.update((prev) => [...prev, ...resp.items]);
        this.audiencePreviewPage.set(nextPage);
        this.audiencePreviewLoadingMore.set(false);
      });
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

  /** Channel-aware central-library load. Only pulls templates the
   *  operator can actually send on the selected channel: published +
   *  active, plus `external_status='approved'` for WhatsApp (Meta
   *  rejects sends of unapproved HSMs, and pending/n_a rows just
   *  clutter the picker). Non-WA channels have no external review, so
   *  every published+active row qualifies. */
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
      // Skip inactive rows — Owner/Admin flipped them off to block
      // exactly this use. The picker only shows things campaigns can
      // actually send. Templates library page keeps showing everything.
      is_active: true,
      limit: 200,
    };
    if (channel === 'whatsapp') {
      filter.external_status = 'approved';
    }
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
    const pickedSize = this.selectedContactMap().size;
    const count = pickedSize > 0 ? pickedSize : this.audienceCount();
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
      const picked = Array.from(this.selectedContactMap().keys());
      if (picked.length > 0) {
        // Explicit selection wins over q/tag/lead_* — send goes to
        // exactly the ticked contacts.
        audience.contact_ids = picked;
      } else {
        if (v.audience_q?.trim()) audience.q = v.audience_q.trim();
        if (v.audience_tag?.trim()) audience.tag = v.audience_tag.trim();
        if (this.leadStatusFilter().length) audience.lead_status = this.leadStatusFilter();
        if (this.leadStageFilter().length) audience.lead_stage = this.leadStageFilter();
        if (this.leadSourceFilter().length) audience.lead_source = this.leadSourceFilter();
      }
    }
    // 'everyone' mode leaves `audience` as {} — backend treats as
    // "all org contacts" (already the existing default behaviour).

    // Channel is picked explicitly on step 1 (no default); step1Complete
    // gates progression, but a rogue Save keystroke could still fire —
    // catch it before we build a payload with a null channel.
    if (!v.channel) {
      this.submitError.set('Pick a channel on step 1 before saving.');
      return;
    }
    const channel = v.channel;
    // Templates-only: campaigns always send through the central
    // library, never free-text or inline HTML. Guard here even though
    // the Next button on step 2 already blocks progression without a
    // template, so a rogue Save keystroke can't slip past.
    if (this.selectedTemplateId() === null) {
      this.submitError.set('Pick a template on step 2 before saving.');
      return;
    }
    const bindings = this.variables();
    for (const n of this.templateVariableNumbers()) {
      const b = bindings[String(n)];
      if (!b || !b.value.trim()) {
        this.submitError.set(`Fill in a value for variable {{${n}}}.`);
        return;
      }
    }

    // Campaigns v1 Step 03 — Email required-field guard. Backend
    // enforces the same invariant; catching it client-side keeps the
    // error inline instead of round-tripping a 422.
    if (channel === 'email') {
      const missing: string[] = [];
      // Migration 0213 — accept either sender kind (OAuth or SMTP).
      // Picker maintains the exactly-one invariant on selection.
      if (!v.email_account_id && !v.smtp_sender_id) missing.push('a sender identity');
      if (!(v.sender_name && v.sender_name.trim())) missing.push('a sender name');
      if (!(v.subject && v.subject.trim())) missing.push('a subject');
      if (missing.length) {
        this.submitError.set(`Email campaigns need ${missing.join(', ')}.`);
        return;
      }
    }

    this.submitting.set(true);
    this.submitError.set(null);
    this.api
      .create({
        name: v.name,
        channel,
        audience_filter: audience,
        template: null,
        template_id: this.selectedTemplateId(),
        template_variables: this.variables(),
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
        // Campaigns v1 Step 03 — Email sender identity + subject + preheader.
        // Null on non-Email channels so backend + DB row stay clean.
        // Migration 0213 — send exactly one of email_account_id /
        // smtp_sender_id (picker maintains the invariant); the other
        // one is null.
        email_account_id: channel === 'email' ? (v.email_account_id ?? null) : null,
        smtp_sender_id: channel === 'email' ? (v.smtp_sender_id ?? null) : null,
        sender_name: channel === 'email' ? (v.sender_name ?? null) : null,
        reply_to: channel === 'email' ? (v.reply_to ?? null) : null,
        subject: channel === 'email' ? (v.subject ?? null) : null,
        preheader: channel === 'email' ? (v.preheader ?? null) : null,
        body_html: null,
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
